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
