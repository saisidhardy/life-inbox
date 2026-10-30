"""Tests for File Upload, Extraction, Task Breakdown, Note Enhancement,
Related Notes, and Completed/Dismissed Task views.
"""

import importlib
import io
import sys

import pytest
from fastapi.testclient import TestClient

from app.rate_limit import analyze_rate_limiter


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """Client with dedicated test database and mock AI provider."""
    test_db_path = tmp_path / "life_inbox_upload_test.db"
    uploads_dir = tmp_path / "uploads"
    uploads_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{test_db_path}")
    monkeypatch.setenv("AI_PROVIDER", "mock")
    monkeypatch.delenv("APP_TOKEN", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANALYZE_RATE_LIMIT_PER_MINUTE", raising=False)
    monkeypatch.delenv("ANALYZE_DAILY_CAP", raising=False)

    analyze_rate_limiter.reset()

    sys.modules.pop("app.ai_provider", None)
    sys.modules.pop("app.database", None)
    sys.modules.pop("app.main", None)
    sys.modules.pop("app.upload_extract", None)

    main = importlib.import_module("app.main")
    database = importlib.import_module("app.database")
    upload_extract = importlib.import_module("app.upload_extract")

    # Override upload dir to tmp_path
    monkeypatch.setattr(upload_extract, "UPLOAD_DIR", uploads_dir)
    monkeypatch.setattr(main, "UPLOAD_DIR", uploads_dir)

    with TestClient(main.app) as test_client:
        yield test_client

    database.engine.dispose()
    sys.modules.pop("app.main", None)
    sys.modules.pop("app.database", None)
    sys.modules.pop("app.ai_provider", None)
    sys.modules.pop("app.upload_extract", None)
    analyze_rate_limiter.reset()


def test_text_document_upload_and_auto_process(client):
    """Uploading a text document extracts text, creates an inbox item, and auto-processes with AI."""
    content = b"# Q4 Marketing Plan\nNeed to finalize the Q4 marketing budget by next Friday #marketing #budget"
    file_tuple = ("q4_plan.txt", io.BytesIO(content), "text/plain")

    response = client.post("/api/upload?auto_process=true", files={"file": file_tuple})
    assert response.status_code == 200
    data = response.json()

    assert data["item"]["id"] > 0
    assert data["stored_filename"].endswith(".txt")
    assert data["item"]["item_type"] in ("text", "document")
    assert data["file_url"].startswith("/api/uploads/")
    assert data["extracted_length"] > 0

    assert data["auto_analysis"] is not None
    assert "extracted_tasks" in data["auto_analysis"]


def test_image_upload_and_metadata_extraction(client):
    """Uploading an image generates an image inbox item with image dimensions/metadata."""
    # 1x1 transparent PNG bytes
    png_bytes = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x06\x00\x00\x00\x1f\x15c4\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05"
        b"\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    file_tuple = ("screenshot.png", io.BytesIO(png_bytes), "image/png")

    response = client.post("/api/upload?auto_process=false", files={"file": file_tuple})
    assert response.status_code == 200
    data = response.json()

    assert data["item"]["item_type"] == "image"

    # Verify item is retrievable via GET /api/items
    items_res = client.get("/api/items")
    assert items_res.status_code == 200
    items = items_res.json()
    assert len(items) == 1
    assert items[0]["item_type"] == "image"
    assert items[0]["source_url"] == data["file_url"]


def test_file_download_and_traversal_prevention(client):
    """Files saved to the uploads directory can be retrieved and directory traversal is blocked."""
    content = b"Confidential notes for project Apollo"
    file_tuple = ("apollo.txt", io.BytesIO(content), "text/plain")

    upload_res = client.post("/api/upload", files={"file": file_tuple})
    assert upload_res.status_code == 200
    stored_filename = upload_res.json()["stored_filename"]

    # Valid download
    download_res = client.get(f"/api/uploads/{stored_filename}")
    assert download_res.status_code == 200
    assert download_res.content == content

    # Directory traversal attempts
    assert client.get("/api/uploads/../main.py").status_code in (400, 404)
    assert client.get("/api/uploads/%2e%2e/database.py").status_code in (400, 404)


def test_task_decomposition_and_subtasks_application(client):
    """Task decomposition breaks a high-level task into subtasks, and apply-subtasks creates them."""
    client.post(
        "/api/items",
        json={"raw_text": "Prepare presentation slides for board meeting"},
    )
    # Run analysis to create the task
    client.post("/api/analyze")

    tasks_res = client.get("/api/tasks?status=open")
    assert tasks_res.status_code == 200
    tasks = tasks_res.json()
    assert len(tasks) >= 1
    parent_task = tasks[0]

    # Call task decomposition endpoint
    decomp_res = client.post(f"/api/tasks/{parent_task['id']}/decompose")
    assert decomp_res.status_code == 200
    decomp_data = decomp_res.json()
    assert decomp_data["task_id"] == parent_task["id"]
    assert len(decomp_data["subtasks"]) >= 2
    assert all("title" in st for st in decomp_data["subtasks"])

    # Apply the subtasks
    apply_payload = {
        "subtasks": [
            {
                "title": "Gather latest revenue metrics",
                "priority": "High",
                "estimated_minutes": 25,
            },
            {
                "title": "Review layout and export presentation PDF",
                "priority": "Medium",
                "estimated_minutes": 15,
            },
        ]
    }
    apply_res = client.post(f"/api/tasks/{parent_task['id']}/apply-subtasks", json=apply_payload)
    assert apply_res.status_code == 200
    created_tasks = apply_res.json()
    assert len(created_tasks) == 2
    assert created_tasks[0]["text"] == "Gather latest revenue metrics"
    assert created_tasks[0]["status"] == "open"
    assert created_tasks[0]["priority"] == "High"

    # Verify task counts updated in database
    all_tasks = client.get("/api/tasks?status=open").json()
    assert len(all_tasks) >= 3


def test_note_enhancement_and_related_items(client):
    """AI note enhancement generates TL;DR, action items, risks, and discovers related notes."""
    # Create two related notes
    n1 = client.post(
        "/api/items?auto_process=false",
        json={"raw_text": "Kickoff meeting for Project Quantum: database migration to Postgres #infra #quantum"},
    ).json()

    client.post(
        "/api/items?auto_process=false",
        json={"raw_text": "Benchmarking Postgres connection pool latency for Project Quantum #infra #postgres"},
    ).json()

    # Enhance note 1
    enhance_res = client.post(f"/api/items/{n1['id']}/enhance")
    assert enhance_res.status_code == 200
    enhance_data = enhance_res.json()
    assert enhance_data["item_id"] == n1["id"]
    assert len(enhance_data["tldr"]) > 0
    assert len(enhance_data["key_points"]) > 0
    assert len(enhance_data["key_takeaways"]) > 0

    # Discover related items
    related_res = client.get(f"/api/items/{n1['id']}/related")
    assert related_res.status_code == 200
    related_data = related_res.json()
    assert related_data["item_id"] == n1["id"]
    assert len(related_data["related_items"]) >= 1
    assert "quantum" in related_data["related_items"][0]["snippet"].lower()


def test_task_filtering_and_completed_dismissed_views(client):
    """Tasks can be completed, dismissed, reopened, and filtered cleanly by status."""
    # Seed notes and run analysis to populate tasks
    client.post(
        "/api/items",
        json={"raw_text": "Call dentist to schedule appointment for wisdom teeth"},
    )
    client.post(
        "/api/items",
        json={"raw_text": "Buy groceries: almond milk, bread"},
    )
    client.post("/api/analyze")

    open_tasks = client.get("/api/tasks?status=open").json()
    assert len(open_tasks) >= 2

    task1_id = open_tasks[0]["id"]
    task2_id = open_tasks[1]["id"]

    # Complete task 1
    c_res = client.post(f"/api/tasks/{task1_id}/complete")
    assert c_res.status_code == 200
    assert c_res.json()["status"] == "completed"

    # Dismiss task 2
    d_res = client.post(f"/api/tasks/{task2_id}/dismiss")
    assert d_res.status_code == 200
    assert d_res.json()["status"] == "dismissed"

    # Verify filtering
    completed_view = client.get("/api/tasks?status=completed").json()
    assert any(t["id"] == task1_id for t in completed_view)
    assert not any(t["id"] == task2_id for t in completed_view)

    dismissed_view = client.get("/api/tasks?status=dismissed").json()
    assert any(t["id"] == task2_id for t in dismissed_view)
    assert not any(t["id"] == task1_id for t in dismissed_view)

    # Verify stats endpoint reports completed and dismissed counts accurately
    stats = client.get("/api/stats").json()
    assert stats["completed_tasks"] >= 1
    assert stats["dismissed_tasks"] >= 1

    # Reopen completed task
    r_res = client.post(f"/api/tasks/{task1_id}/reopen")
    assert r_res.status_code == 200
    assert r_res.json()["status"] == "open"

    # Verify it is back in open tasks
    open_again = client.get("/api/tasks?status=open").json()
    assert any(t["id"] == task1_id for t in open_again)
