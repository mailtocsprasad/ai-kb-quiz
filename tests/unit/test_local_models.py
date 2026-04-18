import pytest
from engine.router import route

LOCAL_MODELS = ["qwen2.5:14b", "phi4:14b"]

TASKS = ["summarize_chunk", "score_answer"]
CHEAP_CASES = [(t, qt) for t in TASKS for qt in [None, "fill_in", "conceptual", "code"]]


@pytest.mark.parametrize("model", LOCAL_MODELS)
def test_local_mode_routes_all_tasks_to_local(model):
    for task in ["generate_question", "evaluate_answer", "summarize_chunk", "score_answer"]:
        for qtype in [None, "fill_in", "conceptual", "code"]:
            assert route(task, qtype, "local") == "local", (
                f"{model}: expected local for ({task}, {qtype})"
            )


@pytest.mark.parametrize("model", LOCAL_MODELS)
def test_hybrid_cheap_tasks_go_local(model):
    assert route("summarize_chunk", None, "hybrid") == "local"
    assert route("generate_question", "fill_in", "hybrid") == "local"
    assert route("evaluate_answer", "fill_in", "hybrid") == "local"
    assert route("score_answer", "conceptual", "hybrid") == "local"


@pytest.mark.parametrize("model", LOCAL_MODELS)
def test_hybrid_complex_tasks_go_premium(model):
    assert route("generate_question", "conceptual", "hybrid") == "premium"
    assert route("generate_question", "code", "hybrid") == "premium"
    assert route("evaluate_answer", "conceptual", "hybrid") == "premium"
    assert route("evaluate_answer", "code", "hybrid") == "premium"


@pytest.mark.parametrize("model", LOCAL_MODELS)
def test_model_name_is_valid_ollama_tag(model):
    name, tag = model.split(":")
    assert name and tag, f"Invalid Ollama model name format: {model}"
