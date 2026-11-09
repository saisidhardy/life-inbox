"""Tests for Integrations Hub:
- Inbound Webhook API (Apple Shortcuts, Zapier, Make, curl)
- Google Calendar and RFC 5545 iCalendar (.ics) exports
- Outbound Webhook dispatching for Slack & Discord
- External issue links for GitHub and Linear
"""

import importlib
import sys
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.rate_limit import analyze_rate_limiter


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """Test client with isolated SQLite database and mock AI provider."""
    test_db_path = tmp_path / "life_inbox_integrations_test.db"
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
    sys.modules.pop("app.integrations", None)

    main = importlib.import_module("app.main")
    database = importlib.import_module("app.database")

    with TestClient(main.app) as test_client:
        yield test_client

    database.engine.dispose()
    sys.modules.pop("app.main", None)
    sys.modules.pop("app.database", None)
    sys.modules.pop("app.ai_provider", None)
    sys.modules.pop("app.integrations", None)
    analyze_rate_limiter.reset()


def test_inbound_webhook_ingests_note_and_tasks(client):
    """Inbound webhook parses note text, saves note, and extracts action items."""
    payload = {
        "text": "Need to prepare the pitch deck for investors by Friday #fundraising #deck",
        "source": "ios_shortcut",
        "auto_process": True,
        "tags": ["urgent"],
    }

    res = client.post("/api/webhooks/inbound", json=payload)
    assert res.status_code == 201
    data = res.json()
    assert data["status"] == "received"
    assert data["item_id"] > 0
    assert data["extracted_tasks_count"] >= 1
    assert "ios_shortcut" in data["message"]

    # Verify task was added to open tasks
    tasks = client.get("/api/tasks?status=open").json()
    assert len(tasks) >= 1
    assert any("pitch deck" in t["text"].lower() or "prepare" in t["text"].lower() for t in tasks)


def test_inbound_webhook_supports_webhook_secret_auth(tmp_path, monkeypatch):
    """Inbound webhook respects APP_TOKEN via X-Webhook-Secret header."""
    test_db_path = tmp_path / "life_inbox_auth_webhook_test.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{test_db_path}")
    monkeypatch.setenv("APP_TOKEN", "supersecrettoken99")
    monkeypatch.setenv("AI_PROVIDER", "mock")

    analyze_rate_limiter.reset()
    sys.modules.pop("app.main", None)
    sys.modules.pop("app.database", None)
    main = importlib.import_module("app.main")

    with TestClient(main.app) as auth_client:
        payload = {"text": "Quick thought from Apple Shortcuts", "source": "shortcuts"}

        # Unauthed request -> 401
        res_unauth = auth_client.post("/api/webhooks/inbound", json=payload)
        assert res_unauth.status_code == 401

        # Authed via X-Webhook-Secret -> 201
        res_auth = auth_client.post(
            "/api/webhooks/inbound",
            json=payload,
            headers={"X-Webhook-Secret": "supersecrettoken99"},
        )
        assert res_auth.status_code == 201
        assert res_auth.json()["status"] == "received"


def test_calendar_export_json_and_ics(client):
    """Task calendar endpoint generates valid Google Calendar URL and RFC 5545 .ics."""
    # Seed a task
    client.post(
        "/api/webhooks/inbound",
        json={"text": "Review architecture security specs by Friday", "source": "test"},
    )
    tasks = client.get("/api/tasks?status=open").json()
    assert len(tasks) >= 1
    task_id = tasks[0]["id"]

    # JSON calendar format
    res_json = client.get(f"/api/tasks/{task_id}/calendar?format=json")
    assert res_json.status_code == 200
    cal_data = res_json.json()
    assert "calendar.google.com" in cal_data["google_calendar_url"]
    assert "BEGIN:VCALENDAR" in cal_data["ics_content"]
    assert "BEGIN:VEVENT" in cal_data["ics_content"]
    assert cal_data["scheduled_date"] is not None

    # ICS raw download format
    res_ics = client.get(f"/api/tasks/{task_id}/calendar?format=ics")
    assert res_ics.status_code == 200
    assert "text/calendar" in res_ics.headers["content-type"]
    assert b"BEGIN:VCALENDAR" in res_ics.content
    assert b"SUMMARY:Task:" in res_ics.content


def test_dispatch_outbound_webhook(client, monkeypatch):
    """Outbound webhook dispatches briefings to Slack or Discord."""
    mock_post = MagicMock()
    mock_post.return_value.status_code = 200
    monkeypatch.setattr("requests.post", mock_post)

    # Dispatch daily briefing to Slack
    slack_payload = {
        "webhook_url": "https://hooks.slack.com/services/T000/B000/XXXXX",
        "payload_type": "daily_briefing",
    }
    res_slack = client.post("/api/integrations/dispatch", json=slack_payload)
    assert res_slack.status_code == 200
    assert res_slack.json()["status"] == "delivered"
    assert res_slack.json()["destination"] == "slack_or_generic"

    # Verify mock was called
    assert mock_post.called
    sent_json = mock_post.call_args[1]["json"]
    assert "Life Inbox — Daily Executive Briefing" in sent_json["text"]

    # Dispatch custom alert to Discord
    mock_post.reset_mock()
    discord_payload = {
        "webhook_url": "https://discord.com/api/webhooks/123/XYZ",
        "payload_type": "custom",
        "custom_text": "Production deployment v1.2 ready",
    }
    res_discord = client.post("/api/integrations/dispatch", json=discord_payload)
    assert res_discord.status_code == 200
    assert res_discord.json()["destination"] == "discord"
    assert "Production deployment v1.2 ready" in mock_post.call_args[1]["json"]["content"]


def test_external_issue_links(client):
    """External links endpoint generates GitHub and Linear pre-filled URLs."""
    client.post(
        "/api/webhooks/inbound",
        json={"text": "Need to fix database connection pool exhaustion under load by tomorrow", "source": "test"},
    )
    tasks = client.get("/api/tasks?status=open").json()
    assert len(tasks) >= 1
    task_id = tasks[0]["id"]

    res = client.get(f"/api/tasks/{task_id}/external-links")
    assert res.status_code == 200
    data = res.json()
    assert data["task_id"] == task_id
    assert "github.com" in data["github_issue_url"]
    assert "issues/new" in data["github_issue_url"]
    assert "linear.app/new" in data["linear_issue_url"]


def test_daily_briefing_endpoint(client):
    """Daily briefing synthesizes today's focus, health score, and top tasks."""
    client.post(
        "/api/webhooks/inbound",
        json={"text": "Need to review customer renewal contract today #urgent", "source": "test"},
    )
    res = client.get("/api/briefing/today")
    assert res.status_code == 200
    data = res.json()
    assert "date" in data
    assert any(g in data["greeting"] for g in ["Good morning", "Good afternoon", "Good evening"])
    assert data["open_tasks_count"] >= 1
    assert 0 <= data["inbox_health_score"] <= 100
    assert len(data["ai_focus_summary"]) > 0
    assert len(data["recommended_actions"]) >= 1


def test_eisenhower_matrix_endpoint(client):
    """Eisenhower matrix partitions open tasks into 4 quadrants."""
    client.post(
        "/api/webhooks/inbound",
        json={"text": "Need to rotate production API keys immediately", "source": "test"},
    )
    client.post(
        "/api/webhooks/inbound",
        json={"text": "Need to buy groceries by tomorrow", "source": "test"},
    )

    res = client.get("/api/tasks/matrix")
    assert res.status_code == 200
    data = res.json()
    assert "q1_do_first" in data
    assert "q2_schedule" in data
    assert "q3_delegate" in data
    assert "q4_eliminate" in data
    total_in_quadrants = (
        len(data["q1_do_first"])
        + len(data["q2_schedule"])
        + len(data["q3_delegate"])
        + len(data["q4_eliminate"])
    )
    assert total_in_quadrants >= 2


def test_task_update_patch_endpoint(client):
    """PATCH /api/tasks/{task_id} allows editing title, priority, and timing inline."""
    client.post(
        "/api/webhooks/inbound",
        json={"text": "Need to update initial payment gateway handler #todo", "source": "test"},
    )
    tasks = client.get("/api/tasks?status=open").json()
    assert len(tasks) >= 1
    task_id = tasks[0]["id"]

    # Patch text, priority, and timing
    patch_payload = {
        "text": "Refactored payment gateway handler",
        "priority": "High",
        "timing_text": "by Thursday 5pm",
    }
    patch_res = client.patch(f"/api/tasks/{task_id}", json=patch_payload)
    assert patch_res.status_code == 200
    updated = patch_res.json()
    assert updated["text"] == "Refactored payment gateway handler"
    assert updated["priority"] == "High"
    assert updated["timing_text"] == "by Thursday 5pm"

    # Verify task retains updated fields on GET
    refetched = client.get("/api/tasks?status=all").json()
    matching = next(t for t in refetched if t["id"] == task_id)
    assert matching["text"] == "Refactored payment gateway handler"
    assert matching["priority"] == "High"


def test_integrations_diagnostics_endpoint(client):
    """GET /api/integrations/diagnostics verifies health of all connectors."""
    res = client.get("/api/integrations/diagnostics")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "healthy"
    assert "timestamp" in data
    assert len(data["connectors"]) >= 6

    names = [c["name"] for c in data["connectors"]]
    assert any("Shortcuts" in n for n in names)
    assert any("Calendar" in n for n in names)
    assert any("Slack" in n or "Discord" in n for n in names)
    assert any("GitHub" in n or "Linear" in n for n in names)
    assert any("Database" in n for n in names)

    for conn in data["connectors"]:
        assert conn["status"] == "operational"
        assert conn["latency_ms"] >= 0


def test_workspace_export_json_and_markdown(client):
    """Workspace export returns full workspace in JSON and Markdown formats."""
    client.post(
        "/api/webhooks/inbound",
        json={"text": "Quarterly financial review note #finance", "source": "test"},
    )

    # Export JSON
    res_json = client.get("/api/backup/export?format=json")
    assert res_json.status_code == 200
    json_data = res_json.json()
    assert json_data["version"] == "1.0"
    assert json_data["total_items"] >= 1
    assert len(json_data["items"]) >= 1

    # Export Markdown
    res_md = client.get("/api/backup/export?format=markdown")
    assert res_md.status_code == 200
    assert "text/markdown" in res_md.headers["content-type"]
    assert "# Life Inbox — Workspace Export" in res_md.text
    assert "## 📋 Tasks" in res_md.text
    assert "## 📝 Notes & Items" in res_md.text


def test_workspace_import_restore(client):
    """Workspace import restores notes and tasks atomically."""
    backup_payload = {
        "items": [
            {"raw_text": "Restored architecture design note #tech"},
            {"raw_text": "Restored hiring goals note #hr"},
        ],
        "tasks": [
            {"text": "Deploy microservice v2", "priority": "High", "timing_text": "tomorrow"},
            {"text": "Interview backend engineer", "priority": "Medium", "timing_text": "Friday"},
        ],
    }

    res = client.post("/api/backup/import", json=backup_payload)
    assert res.status_code == 200
    import_data = res.json()
    assert import_data["status"] == "restored"
    assert import_data["items_imported"] == 2
    assert import_data["tasks_imported"] == 2

    # Check imported tasks exist in tasks endpoint
    tasks = client.get("/api/tasks?status=all").json()
    task_texts = [t["text"] for t in tasks]
    assert "Deploy microservice v2" in task_texts
    assert "Interview backend engineer" in task_texts


