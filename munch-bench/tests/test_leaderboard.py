"""Tests for leaderboard generation."""

from munch_bench.evaluate import BenchmarkRun, QuestionResult
from munch_bench.leaderboard import generate_leaderboard


def _make_run(provider: str, model: str, score: float) -> BenchmarkRun:
    run = BenchmarkRun(provider=provider, model=model, timestamp="2026-04-13T00:00:00Z", token_budget=8000)
    run.results.append(QuestionResult(
        question_id="test-001", repo="test/repo", question="test?",
        difficulty="easy", category="api",
        retrieval_precision_at_5=0.8, retrieval_precision_at_10=0.6,
        retrieval_recall=0.9, retrieval_wall_time_s=0.1, retrieval_tokens=500,
        symbols_returned=["sym1", "sym2"],
        answer="test answer", model=model, provider=provider,
        inference_wall_time_s=0.5, inference_input_tokens=1000,
        inference_output_tokens=200, inference_cost_usd=0.001,
        exact_match=True, llm_judge_score=score,
        ground_truth_answer="test answer", ground_truth_symbols=["sym1"],
    ))
    return run


def test_generate_leaderboard(tmp_path):
    runs = [
        _make_run("groq", "llama-3.3-70b", 0.85),
        _make_run("openai", "gpt-4o-mini", 0.72),
        _make_run("anthropic", "claude-sonnet", 0.91),
    ]
    output = str(tmp_path / "leaderboard.html")
    generate_leaderboard(runs, output)

    with open(output) as f:
        html = f.read()

    assert "munch-bench Leaderboard" in html
    assert "groq" in html
    assert "openai" in html
    assert "anthropic" in html
    assert "chart.js" in html
