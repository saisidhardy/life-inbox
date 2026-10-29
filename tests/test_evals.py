"""Tests for Life Inbox AI evaluation suite and metrics."""

import json
from pathlib import Path
from evals.metrics import evaluate_dataset, jaccard_similarity, tasks_match
from evals.run import evaluate_mock_strategy, load_dataset


def test_eval_dataset_integrity():
    dataset = load_dataset()
    assert len(dataset) >= 25, "Dataset must have at least 25 benchmark notes"
    for item in dataset:
        assert "id" in item
        assert "type" in item
        assert "raw_text" in item
        assert "expected" in item
        assert "category" in item["expected"]
        assert "tasks" in item["expected"]


def test_jaccard_and_task_matching():
    # Exact match
    assert jaccard_similarity("send pitch deck", "send pitch deck") == 1.0
    # Partial match
    assert tasks_match("Send updated pitch deck to Alex", "Send pitch deck to Alex")
    assert tasks_match("Buy 2-inch wood screws", "2-inch wood screws")
    assert not tasks_match("Call Dave about contractor quote", "Order pizza for team")


def test_mock_strategy_evaluates_successfully():
    dataset = load_dataset()
    preds_b = evaluate_mock_strategy(dataset, strategy="structured")
    assert len(preds_b) == len(dataset)
    res = evaluate_dataset(preds_b, dataset)

    assert res["valid_json_rate"] == 1.0
    assert res["category_accuracy"] >= 0.85
    assert res["task_f1"] >= 0.80
    assert res["priority_accuracy"] >= 0.70
    assert res["due_date_accuracy"] >= 0.70


def test_eval_runner_generates_valid_output(tmp_path: Path):
    from evals.run import evaluate_mock_strategy, generate_markdown_report

    dataset = load_dataset()
    preds_a = evaluate_mock_strategy(dataset, strategy="baseline")
    preds_b = evaluate_mock_strategy(dataset, strategy="structured")

    res_a = evaluate_dataset(preds_a, dataset)
    res_b = evaluate_dataset(preds_b, dataset)

    meta = {
        "provider": "mock",
        "strategy_a_name": "Baseline",
        "strategy_b_name": "Structured",
        "strategy_a_label": "Mock (Baseline)",
        "strategy_b_label": "Mock (Structured)",
    }

    report = generate_markdown_report(res_a, res_b, meta)
    assert "# Life Inbox" in report
    assert "Benchmark Summary" in report
    assert "Winner: **Strategy B" in report

    out_file = tmp_path / "ci_eval_out.json"
    out_file.write_text(json.dumps({"a": res_a, "b": res_b}), encoding="utf-8")
    assert out_file.exists()
