import pytest
from engine.router import route


# Hybrid mode — table lookups
def test_hybrid_summarize_chunk_goes_local():
    assert route("summarize_chunk", None, "hybrid") == "local"

def test_hybrid_fill_in_generate_goes_local():
    assert route("generate_question", "fill_in", "hybrid") == "local"

def test_hybrid_conceptual_generate_goes_premium():
    assert route("generate_question", "conceptual", "hybrid") == "premium"

def test_hybrid_code_generate_goes_premium():
    assert route("generate_question", "code", "hybrid") == "premium"

def test_hybrid_fill_in_evaluate_goes_local():
    assert route("evaluate_answer", "fill_in", "hybrid") == "local"

def test_hybrid_conceptual_evaluate_goes_premium():
    assert route("evaluate_answer", "conceptual", "hybrid") == "premium"

def test_hybrid_code_evaluate_goes_premium():
    assert route("evaluate_answer", "code", "hybrid") == "premium"

def test_hybrid_score_goes_local():
    assert route("score_answer", "conceptual", "hybrid") == "local"

# Mode overrides
def test_local_mode_always_local():
    for task in ["generate_question", "evaluate_answer", "summarize_chunk", "score_answer"]:
        for qtype in ["conceptual", "code", "fill_in", None]:
            assert route(task, qtype, "local") == "local"

def test_premium_mode_always_premium():
    for task in ["generate_question", "evaluate_answer", "summarize_chunk", "score_answer"]:
        for qtype in ["conceptual", "code", "fill_in", None]:
            assert route(task, qtype, "premium") == "premium"

def test_unknown_task_type_raises():
    with pytest.raises(ValueError, match="Unknown task_type"):
        route("unknown_task", None, "hybrid")
