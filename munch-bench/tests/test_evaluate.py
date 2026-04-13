"""Tests for evaluation metrics."""

import pytest

from munch_bench.evaluate import precision_at_k, recall, exact_match, BenchmarkRun


def test_precision_at_k_perfect():
    assert precision_at_k(["a", "b", "c"], ["a", "b", "c"], 3) == 1.0


def test_precision_at_k_partial():
    assert precision_at_k(["a", "b", "c", "d", "e"], ["a", "c"], 5) == 0.4


def test_precision_at_k_none():
    assert precision_at_k(["x", "y", "z"], ["a", "b"], 3) == 0.0


def test_precision_at_k_empty_relevant():
    assert precision_at_k(["a", "b"], [], 5) == 0.0


def test_precision_at_k_empty_returned():
    assert precision_at_k([], ["a", "b"], 5) == 0.0


def test_recall_perfect():
    assert recall(["a", "b", "c"], ["a", "b", "c"]) == 1.0


def test_recall_partial():
    assert recall(["a", "b", "c", "d"], ["a", "c"]) == 1.0


def test_recall_miss():
    assert recall(["a", "b"], ["a", "c"]) == 0.5


def test_recall_empty_relevant():
    assert recall(["a", "b"], []) == 1.0  # vacuously true


def test_recall_empty_returned():
    assert recall([], ["a", "b"]) == 0.0


def test_exact_match_substring():
    assert exact_match("The function uses a radix tree for routing", "radix tree") is True


def test_exact_match_no_match():
    assert exact_match("Something completely different", "radix tree") is False


def test_exact_match_case_insensitive():
    assert exact_match("Uses a Radix Tree", "radix tree") is True


def test_benchmark_run_save_load(tmp_path):
    run = BenchmarkRun(
        provider="groq",
        model="llama-3.3-70b-versatile",
        timestamp="2026-04-13T00:00:00Z",
        token_budget=8000,
    )
    path = str(tmp_path / "test_run.json")
    run.save(path)

    loaded = BenchmarkRun.load(path)
    assert loaded.provider == "groq"
    assert loaded.model == "llama-3.3-70b-versatile"
    assert loaded.token_budget == 8000


def test_benchmark_run_summary_empty():
    run = BenchmarkRun(provider="test", model="test", timestamp="now", token_budget=8000)
    assert run.avg_llm_judge_score == 0.0
    assert run.exact_match_rate == 0.0
    assert run.total_cost_usd == 0.0
