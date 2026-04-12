# Routing table for hybrid mode: (task_type, question_type) -> "local" | "premium"
_HYBRID_TABLE: dict[tuple[str, str | None], str] = {
    ("summarize_chunk", None): "local",
    ("generate_question", "fill_in"): "local",
    ("generate_question", "conceptual"): "premium",
    ("generate_question", "code"): "premium",
    ("evaluate_answer", "fill_in"): "local",
    ("evaluate_answer", "conceptual"): "premium",
    ("evaluate_answer", "code"): "premium",
    ("score_answer", "fill_in"): "local",
    ("score_answer", "conceptual"): "local",
    ("score_answer", "code"): "local",
}

_KNOWN_TASKS = {t for t, _ in _HYBRID_TABLE}


def route(task_type: str, question_type: str | None, mode: str) -> str:
    """Return 'local' or 'premium' for a given task in the given mode.

    mode overrides:
      'local'   — always local, regardless of task
      'premium' — always premium, regardless of task
      'hybrid'  — consults _HYBRID_TABLE

    To swap in a different routing backend, replace _HYBRID_TABLE or
    subclass/wrap this function — the interface is (task_type, question_type, mode) -> str.
    """
    if task_type not in _KNOWN_TASKS:
        raise ValueError(f"Unknown task_type '{task_type}'")
    if mode == "local":
        return "local"
    if mode == "premium":
        return "premium"
    return _HYBRID_TABLE[(task_type, question_type)]
