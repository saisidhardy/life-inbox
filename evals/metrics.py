"""Evaluation metrics calculation for Life Inbox AI models and prompts."""

import re
from typing import Any, Dict, List, Set


def tokenize(text: str) -> Set[str]:
    words = re.findall(r"[a-zA-Z0-9]+", (text or "").lower())
    stopwords = {"to", "the", "a", "an", "and", "or", "for", "with", "about", "in", "on", "at", "by", "of"}
    return {w for w in words if w not in stopwords and len(w) > 1}


def jaccard_similarity(text_a: str, text_b: str) -> float:
    set_a = tokenize(text_a)
    set_b = tokenize(text_b)
    if not set_a and not set_b:
        return 1.0
    if not set_a or not set_b:
        return 0.0
    intersection = len(set_a & set_b)
    union = len(set_a | set_b)
    return intersection / union if union > 0 else 0.0


def tasks_match(pred_title: str, expected_title: str, threshold: float = 0.35) -> bool:
    """Determine if a predicted task title matches the expected task title."""
    sim = jaccard_similarity(pred_title, expected_title)
    if sim >= threshold:
        return True
    pred_clean = re.sub(r"\W+", "", pred_title.lower())
    exp_clean = re.sub(r"\W+", "", expected_title.lower())
    return pred_clean in exp_clean or exp_clean in pred_clean


def evaluate_dataset(predictions: List[Dict[str, Any]], dataset: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Calculate comprehensive evaluation metrics across predictions and ground truth."""
    total_notes = len(dataset)
    valid_json_count = 0
    correct_category_count = 0

    total_expected_tasks = 0
    total_predicted_tasks = 0
    true_positive_tasks = 0

    matched_priority_correct = 0
    matched_due_date_correct = 0
    matched_task_count = 0

    total_latency_ms = 0.0
    total_cost_usd = 0.0

    for pred, truth in zip(predictions, dataset):
        is_valid = pred.get("valid_json", False)
        if is_valid:
            valid_json_count += 1

        expected_cat = truth["expected"]["category"].lower()
        pred_cat = str(pred.get("category", "")).lower()
        if expected_cat == pred_cat or (expected_cat in pred_cat):
            correct_category_count += 1

        exp_tasks = truth["expected"].get("tasks", [])
        pred_tasks = pred.get("extracted_tasks", [])

        total_expected_tasks += len(exp_tasks)
        total_predicted_tasks += len(pred_tasks)

        # Track which expected tasks were matched to prevent double counting
        matched_exp_indices = set()

        for pt in pred_tasks:
            pt_title = pt.get("title", "") if isinstance(pt, dict) else getattr(pt, "title", "")
            pt_pri = pt.get("priority", "Medium") if isinstance(pt, dict) else getattr(pt, "priority", "Medium")
            pt_due = pt.get("due_date", None) if isinstance(pt, dict) else getattr(pt, "due_date", None)

            # Find matching expected task
            for idx, et in enumerate(exp_tasks):
                if idx in matched_exp_indices:
                    continue
                et_title = et.get("title", "")
                if tasks_match(pt_title, et_title):
                    matched_exp_indices.add(idx)
                    true_positive_tasks += 1
                    matched_task_count += 1

                    # Check priority
                    et_pri = et.get("priority", "Medium")
                    if str(pt_pri).lower() == str(et_pri).lower():
                        matched_priority_correct += 1

                    # Check due date
                    et_due = et.get("due_date", None)
                    if et_due is None and pt_due is None:
                        matched_due_date_correct += 1
                    elif et_due and pt_due:
                        if str(et_due).lower() in str(pt_due).lower() or str(pt_due).lower() in str(et_due).lower():
                            matched_due_date_correct += 1
                    break

        total_latency_ms += pred.get("latency_ms", 0.0)
        total_cost_usd += pred.get("cost_usd", 0.0)

    # Calculate rates
    valid_json_rate = round(valid_json_count / total_notes, 4) if total_notes else 0.0
    category_accuracy = round(correct_category_count / total_notes, 4) if total_notes else 0.0

    task_precision = (
        round(true_positive_tasks / total_predicted_tasks, 4) if total_predicted_tasks else 1.0
    )
    task_recall = (
        round(true_positive_tasks / total_expected_tasks, 4) if total_expected_tasks else 1.0
    )
    task_f1 = (
        round(2 * (task_precision * task_recall) / (task_precision + task_recall), 4)
        if (task_precision + task_recall) > 0
        else 0.0
    )

    priority_accuracy = (
        round(matched_priority_correct / matched_task_count, 4) if matched_task_count else 1.0
    )
    due_date_accuracy = (
        round(matched_due_date_correct / matched_task_count, 4) if matched_task_count else 1.0
    )
    avg_latency_ms = round(total_latency_ms / total_notes, 2) if total_notes else 0.0

    return {
        "total_samples": total_notes,
        "valid_json_rate": valid_json_rate,
        "category_accuracy": category_accuracy,
        "task_precision": task_precision,
        "task_recall": task_recall,
        "task_f1": task_f1,
        "priority_accuracy": priority_accuracy,
        "due_date_accuracy": due_date_accuracy,
        "avg_latency_ms": avg_latency_ms,
        "total_cost_usd": round(total_cost_usd, 6),
    }
