"""Tests for corpus loading and filtering."""

from pathlib import Path

import pytest

from munch_bench.corpus import Corpus, Question


CORPUS_DIR = Path(__file__).parent.parent / "corpus"


def test_corpus_loads():
    corpus = Corpus.load(CORPUS_DIR)
    assert len(corpus.questions) >= 100, f"Expected 100+ questions, got {len(corpus.questions)}"
    assert len(corpus.repos) >= 10, f"Expected 10+ repos, got {len(corpus.repos)}"


def test_all_questions_have_required_fields():
    corpus = Corpus.load(CORPUS_DIR)
    for q in corpus.questions:
        assert q.id, f"Question missing id"
        assert q.repo, f"Question {q.id} missing repo"
        assert q.question, f"Question {q.id} missing question"
        assert q.ground_truth_answer, f"Question {q.id} missing ground_truth_answer"
        assert q.difficulty in ("easy", "medium", "hard"), f"Question {q.id} has invalid difficulty: {q.difficulty}"


def test_question_ids_are_unique():
    corpus = Corpus.load(CORPUS_DIR)
    ids = [q.id for q in corpus.questions]
    assert len(ids) == len(set(ids)), f"Duplicate question IDs found: {[x for x in ids if ids.count(x) > 1]}"


def test_filter_by_repo():
    corpus = Corpus.load(CORPUS_DIR)
    flask = corpus.filter(repo="pallets/flask")
    assert len(flask.questions) > 0
    assert all(q.repo == "pallets/flask" for q in flask.questions)


def test_filter_by_difficulty():
    corpus = Corpus.load(CORPUS_DIR)
    hard = corpus.filter(difficulty="hard")
    assert len(hard.questions) > 0
    assert all(q.difficulty == "hard" for q in hard.questions)


def test_filter_by_category():
    corpus = Corpus.load(CORPUS_DIR)
    arch = corpus.filter(category="architecture")
    assert len(arch.questions) > 0
    assert all(q.category == "architecture" for q in arch.questions)


def test_filter_combined():
    corpus = Corpus.load(CORPUS_DIR)
    filtered = corpus.filter(difficulty="easy", category="api")
    assert all(q.difficulty == "easy" and q.category == "api" for q in filtered.questions)
