"""Tests for Phase 3 AI Differentiator features:
1. Auto-processing on capture
2. 'Ask your inbox' with BM25 retrieval and citations
3. Weekly AI digest
4. AI provider abstraction and fallback
5. Cost and latency telemetry
"""

import importlib
import sys

import pytest
from fastapi.testclient import TestClient

from app.ai_provider import MockAIProvider, OpenAIProvider, estimate_cost, get_ai_provider
from app.rate_limit import analyze_rate_limiter
from app.retrieval import BM25Retriever, extract_citations_from_text


@pytest.fixture()
def ai_client(tmp_path, monkeypatch):
    """Client with dedicated SQLite test database and mock AI provider."""
    test_db_path = tmp_path / "life_inbox_ai_test.db"
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
    main = importlib.import_module("app.main")
    database = importlib.import_module("app.database")

    with TestClient(main.app) as client:
        yield client

    database.engine.dispose()
    sys.modules.pop("app.main", None)
    sys.modules.pop("app.database", None)
    sys.modules.pop("app.ai_provider", None)
    analyze_rate_limiter.reset()


# ---------------------------------------------------------------------------
# 1. Auto-Processing on Capture Tests
# ---------------------------------------------------------------------------


def test_auto_process_on_capture(ai_client):
    note_text = "Schedule Q4 roadmap sync with #team tomorrow. - [ ] Prepare presentation slides"
    res = ai_client.post("/api/items?auto_process=true", json={"raw_text": note_text})
    assert res.status_code == 200
    data = res.json()

    assert data["raw_text"] == note_text
    assert "auto_analysis" in data
    analysis = data["auto_analysis"]
    assert analysis["category"] == "Work"
    assert "#team" in analysis["suggested_tags"]
    assert len(analysis["extracted_tasks"]) >= 1
    assert "summary" in analysis
    assert len(analysis["summary"]) > 0


def test_auto_process_by_item_id(ai_client):
    created = ai_client.post(
        "/api/items",
        json={"raw_text": "Buy groceries: almond milk, bread, organic apples #shopping"},
    ).json()

    item_id = created["id"]
    res = ai_client.post(f"/api/items/{item_id}/auto-process")
    assert res.status_code == 200
    analysis = res.json()
    assert analysis["category"] == "Shopping"
    assert "#shopping" in analysis["suggested_tags"]
    assert analysis["summary"] != ""


def test_auto_process_nonexistent_item_returns_404(ai_client):
    res = ai_client.post("/api/items/999999/auto-process")
    assert res.status_code == 404
    assert "Item not found" in res.json()["detail"]


def test_process_note_text_endpoint(ai_client):
    payload = {"raw_text": "💡 Startup concept: AI automated documentation generator #saas #ideas"}
    res = ai_client.post("/api/process-note", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["category"] == "Ideas"
    assert "#ideas" in data["suggested_tags"]


# ---------------------------------------------------------------------------
# 2. 'Ask Your Inbox' & BM25 Retrieval Tests
# ---------------------------------------------------------------------------


def test_bm25_retriever_ranking():
    notes = [
        {"id": 1, "title": "Roadmap", "raw_text": "Launch new mobile application feature in November"},
        {"id": 2, "title": "Dentist", "raw_text": "Dentist appointment scheduled for Tuesday 10am"},
        {"id": 3, "title": "Grocery", "raw_text": "Buy groceries at whole foods market"},
    ]
    retriever = BM25Retriever(notes)
    results = retriever.search("mobile application roadmap", top_k=2)
    assert len(results) > 0
    top_note, top_score = results[0]
    assert top_note["id"] == 1
    assert top_score > 0.0


def test_ask_inbox_with_citations(ai_client):
    ai_client.post("/api/items", json={"raw_text": "Q4 revenue target is set to $1.2M with 15% margin #finance"})
    ai_client.post("/api/items", json={"raw_text": "Grocery shopping list: eggs, oat milk, coffee"})

    res = ai_client.post("/api/ask", json={"question": "What is our Q4 revenue target?", "top_k": 3})
    assert res.status_code == 200
    data = res.json()

    assert data["question"] == "What is our Q4 revenue target?"
    assert "answer" in data
    assert len(data["citations"]) >= 1
    # Check that citation points to Note #1
    top_citation = data["citations"][0]
    assert top_citation["id"] == 1
    assert "revenue target" in top_citation["snippet"].lower()
    assert data["notes_used_count"] >= 1
    assert data["latency_ms"] >= 0


def test_extract_citations_utility():
    from app.schemas import NoteCitation

    candidates = [
        NoteCitation(id=1, snippet="Note 1 snippet", relevance_score=1.5),
        NoteCitation(id=2, snippet="Note 2 snippet", relevance_score=1.2),
        NoteCitation(id=3, snippet="Note 3 snippet", relevance_score=0.8),
    ]

    answer = "According to [Note #2] and [Note #1], the project deadline is Friday."
    filtered = extract_citations_from_text(answer, candidates)
    cited_ids = [c.id for c in filtered]
    assert cited_ids == [1, 2]


# ---------------------------------------------------------------------------
# 3. Weekly Digest Tests
# ---------------------------------------------------------------------------


def test_weekly_digest_generation(ai_client):
    ai_client.post("/api/items", json={"raw_text": "Meeting with client #work - [ ] Finalize contract by Friday"})
    ai_client.post("/api/items", json={"raw_text": "Brainstorm AI assistant capabilities #ideas"})

    res = ai_client.get("/api/digest/weekly")
    assert res.status_code == 200
    digest = res.json()

    assert "generated_at" in digest
    assert "period" in digest
    assert digest["total_notes_in_scope"] == 2
    assert "executive_summary" in digest
    assert len(digest["executive_summary"]) > 0
    assert isinstance(digest["suggested_focus"], list)


# ---------------------------------------------------------------------------
# 4. Provider Abstraction Tests
# ---------------------------------------------------------------------------


def test_provider_factory_fallback(monkeypatch):
    # When AI_PROVIDER=mock
    monkeypatch.setenv("AI_PROVIDER", "mock")
    prov = get_ai_provider()
    assert isinstance(prov, MockAIProvider)

    # When no key is set and AI_PROVIDER is unset -> MockAIProvider
    monkeypatch.delenv("AI_PROVIDER", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    prov2 = get_ai_provider()
    assert isinstance(prov2, MockAIProvider)


def test_estimate_cost_calculation():
    # 1,000 prompt tokens = $0.00015, 1,000 completion = $0.00060 -> $0.00075
    cost = estimate_cost(1000, 1000)
    assert cost == 0.00075


def test_openai_provider_fallback_on_failure():
    # Provider with invalid key should safely fallback to mock without crashing
    provider = OpenAIProvider(api_key="sk-invalid-test-key", model_name="gpt-5-mini")
    analysis = provider.auto_process_note("Review architecture document #engineering")
    assert analysis.category == "Work"
    assert "#engineering" in analysis.suggested_tags


# ---------------------------------------------------------------------------
# 5. Cost and Latency Telemetry Tests
# ---------------------------------------------------------------------------


def test_ai_telemetry_metrics_tracking(ai_client):
    # Perform AI operations
    ai_client.post("/api/process-note", json={"raw_text": "Test AI note processing"})
    ai_client.post("/api/ask", json={"question": "Test question", "top_k": 2})

    # Query metrics endpoint
    res = ai_client.get("/api/ai/metrics")
    assert res.status_code == 200
    metrics = res.json()

    assert metrics["total_calls"] >= 2
    assert metrics["total_tokens"] > 0
    assert len(metrics["recent_calls"]) >= 2
    recent_ops = [c["operation"] for c in metrics["recent_calls"]]
    assert "auto_process" in recent_ops or "ask_inbox" in recent_ops

    # Verify /api/stats includes ai_metrics summary
    stats_res = ai_client.get("/api/stats")
    assert stats_res.status_code == 200
    stats_data = stats_res.json()
    assert "ai_metrics" in stats_data
    assert stats_data["ai_metrics"]["total_calls"] == metrics["total_calls"]
