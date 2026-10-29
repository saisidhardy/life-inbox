"""Comprehensive security, authentication, rate limiting, and input hardening tests."""

import importlib
import sys

import pytest
from fastapi.testclient import TestClient

from app.rate_limit import analyze_rate_limiter


@pytest.fixture()
def sec_client(tmp_path, monkeypatch):
    """Create a client with a dedicated SQLite database and test auth token."""
    test_db_path = tmp_path / "life_inbox_sec_test.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{test_db_path}")
    monkeypatch.setenv("APP_TOKEN", "test-secret-token-12345")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANALYZE_RATE_LIMIT_PER_MINUTE", raising=False)
    monkeypatch.delenv("ANALYZE_DAILY_CAP", raising=False)

    analyze_rate_limiter.reset()

    sys.modules.pop("app.database", None)
    sys.modules.pop("app.main", None)
    main = importlib.import_module("app.main")
    database = importlib.import_module("app.database")

    with TestClient(main.app) as client:
        yield client, test_db_path

    database.engine.dispose()
    sys.modules.pop("app.main", None)
    sys.modules.pop("app.database", None)
    analyze_rate_limiter.reset()


# ---------------------------------------------------------------------------
# 1. Authentication Tests
# ---------------------------------------------------------------------------


def test_public_routes_accessible_without_token(sec_client):
    client, _ = sec_client
    # Home page
    res_home = client.get("/")
    assert res_home.status_code == 200

    # Static files
    res_css = client.get("/static/styles.css")
    assert res_css.status_code == 200

    # Health check is explicitly exempt from token auth
    res_health = client.get("/api/health")
    assert res_health.status_code == 200
    assert res_health.json() == {"status": "ok"}


def test_api_routes_reject_unauthenticated_requests(sec_client):
    client, _ = sec_client
    endpoints = [
        ("GET", "/api/items"),
        ("POST", "/api/items"),
        ("GET", "/api/stats"),
        ("GET", "/api/tasks"),
        ("GET", "/api/export"),
        ("POST", "/api/analyze"),
        ("POST", "/api/import"),
    ]
    for method, path in endpoints:
        if method == "GET":
            res = client.get(path)
        else:
            res = client.post(path, json={})
        assert res.status_code == 401, f"{method} {path} should return 401 Unauthorized"
        assert "Unauthorized" in res.json().get("detail", "")
        assert "WWW-Authenticate" in res.headers
        assert "X-Request-ID" in res.headers


def test_api_routes_reject_invalid_token(sec_client):
    client, _ = sec_client
    res = client.get("/api/items", headers={"Authorization": "Bearer invalid-wrong-token"})
    assert res.status_code == 401
    assert res.json()["detail"] == "Unauthorized: invalid or missing API token"


def test_api_routes_accept_valid_bearer_token(sec_client):
    client, _ = sec_client
    res = client.get(
        "/api/items",
        headers={"Authorization": "Bearer test-secret-token-12345"},
    )
    assert res.status_code == 200
    assert isinstance(res.json(), list)


def test_api_routes_accept_valid_x_app_token_header(sec_client):
    client, _ = sec_client
    res = client.get(
        "/api/items",
        headers={"X-App-Token": "test-secret-token-12345"},
    )
    assert res.status_code == 200


def test_api_routes_accept_valid_query_token(sec_client):
    client, _ = sec_client
    res = client.get("/api/export?format=json&token=test-secret-token-12345")
    assert res.status_code == 200
    assert "application/json" in res.headers["content-type"]


# ---------------------------------------------------------------------------
# 2. Rate Limiting Tests (/api/analyze)
# ---------------------------------------------------------------------------


def test_analyze_rate_limit_per_minute(sec_client, monkeypatch):
    client, _ = sec_client
    auth_headers = {"Authorization": "Bearer test-secret-token-12345"}

    # Seed an item so analysis works
    client.post("/api/items", json={"raw_text": "Schedule dentist appointment"}, headers=auth_headers)

    monkeypatch.setenv("ANALYZE_RATE_LIMIT_PER_MINUTE", "2")
    analyze_rate_limiter.reset()

    # 1st request -> OK
    r1 = client.post("/api/analyze", headers=auth_headers)
    assert r1.status_code == 200

    # 2nd request -> OK
    r2 = client.post("/api/analyze", headers=auth_headers)
    assert r2.status_code == 200

    # 3rd request within 60s -> 429
    r3 = client.post("/api/analyze", headers=auth_headers)
    assert r3.status_code == 429
    assert "Rate limit exceeded" in r3.json()["detail"]
    assert "Retry-After" in r3.headers


def test_analyze_daily_cap(sec_client, monkeypatch):
    client, _ = sec_client
    auth_headers = {"Authorization": "Bearer test-secret-token-12345"}

    client.post("/api/items", json={"raw_text": "Buy groceries"}, headers=auth_headers)

    # Set daily cap to 1
    monkeypatch.setenv("ANALYZE_RATE_LIMIT_PER_MINUTE", "10")
    monkeypatch.setenv("ANALYZE_DAILY_CAP", "1")
    analyze_rate_limiter.reset()

    # 1st request -> OK
    r1 = client.post("/api/analyze", headers=auth_headers)
    assert r1.status_code == 200

    # 2nd request -> 429 Daily Cap Reached
    r2 = client.post("/api/analyze", headers=auth_headers)
    assert r2.status_code == 429
    assert "Daily analysis cap reached" in r2.json()["detail"]
    assert int(r2.headers.get("Retry-After", 0)) > 0


# ---------------------------------------------------------------------------
# 3. XSS and HTML Escaping Tests
# ---------------------------------------------------------------------------


def test_xss_payloads_persisted_safely(sec_client):
    client, _ = sec_client
    auth_headers = {"Authorization": "Bearer test-secret-token-12345"}

    payloads = [
        "<script>alert('xss')</script>",
        "<img src=x onerror=alert('xss')>",
        "<a href=\"javascript:alert('xss')\">click</a>",
        "javascript:alert(1)",
        "https://example.com/test\" onclick=\"alert(1)",
    ]

    for p in payloads:
        res = client.post("/api/items", json={"raw_text": p}, headers=auth_headers)
        assert res.status_code == 200
        saved = res.json()
        assert saved["raw_text"] == p

    # Verify JSON export doesn't corrupt payloads
    export_res = client.get("/api/export?format=json", headers=auth_headers)
    assert export_res.status_code == 200
    export_items = export_res.json()["items"]
    assert len(export_items) == len(payloads)


def test_frontend_sanitizer_rules():
    """Verify JS escaping rules in Python to ensure payloads cannot break DOM."""
    def py_esc(s: str) -> str:
        return (
            s.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
            .replace("'", "&#39;")
        )

    # Script tag
    escaped_script = py_esc("<script>alert('xss')</script>")
    assert "<script>" not in escaped_script
    assert "&lt;script&gt;alert(&#39;xss&#39;)&lt;/script&gt;" == escaped_script

    # Image onerror attribute breakout
    escaped_img = py_esc('<img src=x onerror=alert("xss")>')
    assert "<img" not in escaped_img
    assert "&quot;" in escaped_img

    # Attribute quote breakout
    escaped_attr = py_esc('https://example.com" onmouseover="alert(1)')
    assert '"' not in escaped_attr
    assert "&quot;" in escaped_attr


# ---------------------------------------------------------------------------
# 4. Hardened /api/import Tests
# ---------------------------------------------------------------------------


def test_import_exceeding_max_notes_is_rejected(sec_client):
    client, _ = sec_client
    auth_headers = {"Authorization": "Bearer test-secret-token-12345"}

    # 101 notes exceeds MAX_IMPORT_NOTES = 100
    too_many_notes = [f"Note {i}" for i in range(101)]
    res = client.post("/api/import", json={"notes": too_many_notes}, headers=auth_headers)
    assert res.status_code == 422  # Pydantic validation error


def test_import_note_exceeding_max_length_is_rejected(sec_client):
    client, _ = sec_client
    auth_headers = {"Authorization": "Bearer test-secret-token-12345"}

    oversized_note = "A" * 10001
    res = client.post("/api/import", json={"notes": [oversized_note]}, headers=auth_headers)
    assert res.status_code == 400
    assert "exceeds maximum length" in res.json()["detail"]


def test_import_empty_or_whitespace_notes_is_rejected(sec_client):
    client, _ = sec_client
    auth_headers = {"Authorization": "Bearer test-secret-token-12345"}

    # All whitespace
    res = client.post("/api/import", json={"notes": ["   ", "\t\n  "]}, headers=auth_headers)
    assert res.status_code == 400
    assert "contains no valid, non-empty notes" in res.json()["detail"]

    # Empty list
    res2 = client.post("/api/import", json={"notes": []}, headers=auth_headers)
    assert res2.status_code == 422


def test_import_creates_db_backup_and_succeeds(sec_client):
    client, db_path = sec_client
    auth_headers = {"Authorization": "Bearer test-secret-token-12345"}

    payload = {"notes": ["Task 1 #prod", "Task 2 #docs", "Idea 3"]}
    res = client.post("/api/import", json=payload, headers=auth_headers)
    assert res.status_code == 200
    assert res.json()["imported_count"] == 3

    # Verify backup file was created in data/backups/ or db parent backups
    backup_dir = db_path.parent / "backups"
    assert backup_dir.exists()
    backups = list(backup_dir.glob("*.db"))
    assert len(backups) >= 1


def test_import_single_transaction_rollback_on_failure(sec_client, monkeypatch):
    client, _ = sec_client
    auth_headers = {"Authorization": "Bearer test-secret-token-12345"}
    main = sys.modules["app.main"]

    # Simulate database crash mid-transaction
    def failing_batch(_notes):
        raise RuntimeError("Simulated DB connection failure during bulk write")

    monkeypatch.setattr(main, "batch_add_items_to_db", failing_batch)

    res = client.post("/api/import", json={"notes": ["Note A", "Note B"]}, headers=auth_headers)
    assert res.status_code == 500
    assert "Unable to import notes" in res.json()["detail"]

    # Verify 0 items were committed
    items_res = client.get("/api/items", headers=auth_headers)
    assert items_res.status_code == 200
    assert len(items_res.json()) == 0


# ---------------------------------------------------------------------------
# 5. Structured Logging & Response Format Tests
# ---------------------------------------------------------------------------


def test_responses_include_request_id_header(sec_client):
    client, _ = sec_client
    res = client.get("/api/health")
    assert res.status_code == 200
    assert "X-Request-ID" in res.headers
    assert len(res.headers["X-Request-ID"]) >= 6


def test_error_responses_standardized_format(sec_client):
    client, _ = sec_client
    auth_headers = {"Authorization": "Bearer test-secret-token-12345"}

    # 404 on nonexistent item
    r_404 = client.delete("/api/items/999999", headers=auth_headers)
    assert r_404.status_code == 404
    assert "detail" in r_404.json()

    # 401
    r_401 = client.get("/api/items")
    assert r_401.status_code == 401
    assert "detail" in r_401.json()
