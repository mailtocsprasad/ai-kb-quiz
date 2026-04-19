"""Module tests for LearnSession — require real local dependencies.

Marked @pytest.mark.local: run by default locally, skipped in CI.
Ollama must be running with phi4-mini pulled.
ChromaDB collection must exist (run kb index first).
"""
import pytest
from unittest.mock import MagicMock
from engine.question import Chunk
from engine.models.local_adapter import LocalAdapter
from engine.learn import LearnSession

_LOCAL_MODEL = "phi4:14b"


def _fake_retriever(texts: list[str]):
    chunks = [
        Chunk(heading=f"Section {i+1}", text=t, source_file="kb/test.md")
        for i, t in enumerate(texts)
    ]
    r = MagicMock()
    r.search.return_value = chunks
    return r, chunks


@pytest.mark.local
def test_learn_session_explain_real_ollama():
    """explain() returns a non-empty string from a live Ollama model."""
    retriever, _ = _fake_retriever([
        "The SSDT maps syscall numbers to kernel function addresses.",
        "Rootkits overwrite SSDT entries to intercept system calls.",
    ])
    adapter = LocalAdapter(model=_LOCAL_MODEL)
    session = LearnSession(topic="SSDT Hooking", retriever=retriever, adapter=adapter)
    answer, chunks = session.explain()
    assert isinstance(answer, str)
    assert len(answer) > 10, f"Expected a real explanation, got: {answer!r}"
    assert len(chunks) == 2


@pytest.mark.local
def test_learn_session_suggest_real_ollama():
    """suggest() returns up to 3 follow-up questions from a live model."""
    _, chunks = _fake_retriever([
        "The SSDT maps syscall numbers to kernel function addresses.",
    ])
    adapter = LocalAdapter(model=_LOCAL_MODEL)
    session = LearnSession(topic="SSDT", retriever=MagicMock(), adapter=adapter)
    suggestions = session.suggest(chunks, "SSDT Hooking")
    assert isinstance(suggestions, list)
    assert 1 <= len(suggestions) <= 3


@pytest.mark.local
def test_learn_session_follow_up_real_ollama():
    """follow_up() returns a non-empty answer from a live model."""
    retriever, _ = _fake_retriever([
        "Rootkits overwrite SSDT entries to intercept system calls.",
    ])
    adapter = LocalAdapter(model=_LOCAL_MODEL)
    session = LearnSession(topic="SSDT", retriever=retriever, adapter=adapter)
    answer, chunks = session.follow_up("How do rootkits use SSDT?")
    assert isinstance(answer, str)
    assert len(answer) > 10
