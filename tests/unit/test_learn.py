"""Unit tests for LearnSession (Task 12.5).

All tests use MockAdapter and a fake retriever — no live API or DB calls.
"""
import pytest
from unittest.mock import MagicMock, patch
from engine.question import Chunk, PTCResult
from engine.models.adapter import MockAdapter
from engine.learn import LearnSession


def _chunk(heading: str, text: str = "some text") -> Chunk:
    return Chunk(heading=heading, text=text, source_file="kb/topic.md")


def _make_retriever(chunks: list[Chunk]):
    r = MagicMock()
    r.search.return_value = chunks
    return r


# --- explain() ---

def test_explain_returns_string_and_chunks():
    chunks = [_chunk("SSDT Hooking", "The SSDT maps syscall numbers.")]
    retriever = _make_retriever(chunks)
    adapter = MockAdapter(response="SSDT explanation")
    session = LearnSession(topic="SSDT", retriever=retriever, adapter=adapter)
    answer, returned_chunks = session.explain()
    assert answer == "SSDT explanation"
    assert returned_chunks == chunks


def test_explain_returns_empty_when_no_chunks():
    retriever = _make_retriever([])
    session = LearnSession(topic="SSDT", retriever=retriever, adapter=MockAdapter())
    answer, chunks = session.explain()
    assert answer == ""
    assert chunks == []


def test_explain_prompt_contains_topic():
    chunks = [_chunk("SSDT Hooking")]
    retriever = _make_retriever(chunks)
    adapter = MockAdapter(response="ok")
    session = LearnSession(topic="SSDT Hooking", retriever=retriever, adapter=adapter)
    session.explain()
    assert "SSDT Hooking" in adapter.calls[0]


def test_explain_prompt_contains_compressed_text():
    chunks = [_chunk("SSDT Hooking", "Maps syscall numbers to kernel addresses.")]
    retriever = _make_retriever(chunks)
    adapter = MockAdapter(response="ok")
    session = LearnSession(topic="SSDT", retriever=retriever, adapter=adapter)
    session.explain()
    assert len(adapter.calls[0]) > len("SSDT")


def test_explain_calls_compress_with_summarize_chunk():
    chunks = [_chunk("SSDT Hooking")]
    retriever = _make_retriever(chunks)
    adapter = MockAdapter(response="ok")
    session = LearnSession(topic="SSDT", retriever=retriever, adapter=adapter)
    with patch("engine.learn.compress") as mock_compress:
        mock_compress.return_value = PTCResult(
            compressed_text="summary", raw_tokens=10, compressed_tokens=3
        )
        session.explain()
    mock_compress.assert_called_once_with(chunks, "summarize_chunk")


# --- suggest() ---

def test_suggest_returns_up_to_three_lines():
    chunks = [_chunk("SSDT Hooking"), _chunk("Kernel Callbacks")]
    retriever = _make_retriever(chunks)
    adapter = MockAdapter(response="Q1\nQ2\nQ3\nQ4")
    session = LearnSession(topic="SSDT", retriever=retriever, adapter=adapter)
    suggestions = session.suggest(chunks, "SSDT")
    assert len(suggestions) == 3


def test_suggest_returns_empty_list_on_adapter_error():
    chunks = [_chunk("SSDT Hooking")]
    retriever = _make_retriever(chunks)

    class BrokenAdapter:
        def generate(self, prompt: str) -> str:
            raise RuntimeError("network down")

    session = LearnSession(topic="SSDT", retriever=retriever, adapter=MockAdapter(), suggest_adapter=BrokenAdapter())
    result = session.suggest(chunks, "SSDT")
    assert result == []


def test_suggest_prompt_uses_headings_only():
    secret = "SECRET_CONTENT_NOT_IN_PROMPT"
    chunks = [_chunk("SSDT Hooking", secret)]
    retriever = _make_retriever(chunks)
    suggest_adapter = MockAdapter(response="Q1\nQ2\nQ3")
    session = LearnSession(topic="SSDT", retriever=retriever, adapter=MockAdapter(), suggest_adapter=suggest_adapter)
    session.suggest(chunks, "SSDT")
    assert secret not in suggest_adapter.calls[0]


def test_suggest_uses_context_when_provided():
    chunks = [_chunk("SSDT Hooking")]
    retriever = _make_retriever(chunks)
    suggest_adapter = MockAdapter(response="Q1\nQ2\nQ3")
    session = LearnSession(topic="SSDT", retriever=retriever, adapter=MockAdapter(), suggest_adapter=suggest_adapter)
    session.suggest(chunks, "SSDT", context="SSDT maps syscall numbers to kernel function addresses.")
    assert "SSDT maps syscall" in suggest_adapter.calls[0]


def test_suggest_context_excludes_headings_when_context_provided():
    chunks = [_chunk("Unrelated Heading")]
    retriever = _make_retriever(chunks)
    suggest_adapter = MockAdapter(response="Q1\nQ2\nQ3")
    session = LearnSession(topic="SSDT", retriever=retriever, adapter=MockAdapter(), suggest_adapter=suggest_adapter)
    session.suggest(chunks, "SSDT", context="Some focused explanation.")
    assert "Unrelated Heading" not in suggest_adapter.calls[0]


def test_suggest_uses_separate_adapter_when_provided():
    chunks = [_chunk("SSDT Hooking")]
    retriever = _make_retriever(chunks)
    main_adapter = MockAdapter(response="explanation")
    suggest_adapter = MockAdapter(response="Q1\nQ2\nQ3")
    session = LearnSession(topic="SSDT", retriever=retriever, adapter=main_adapter, suggest_adapter=suggest_adapter)
    session.suggest(chunks, "SSDT")
    assert len(suggest_adapter.calls) == 1
    assert len(main_adapter.calls) == 0


# --- follow_up() ---

def test_follow_up_anchors_query_with_topic():
    chunks = [_chunk("SSDT Hooking")]
    retriever = _make_retriever(chunks)
    session = LearnSession(topic="SSDT", retriever=retriever, adapter=MockAdapter(response="answer"))
    session.follow_up("How does hooking work?")
    retriever.search.assert_called_once_with("SSDT: How does hooking work?", top_k=4, top_n=None)


def test_follow_up_returns_empty_when_no_chunks():
    retriever = _make_retriever([])
    session = LearnSession(topic="SSDT", retriever=retriever, adapter=MockAdapter())
    answer, chunks = session.follow_up("How does hooking work?")
    assert answer == ""
    assert chunks == []


def test_follow_up_prompt_contains_question():
    chunks = [_chunk("SSDT Hooking")]
    retriever = _make_retriever(chunks)
    adapter = MockAdapter(response="answer")
    session = LearnSession(topic="SSDT", retriever=retriever, adapter=adapter)
    session.follow_up("How does hooking work?")
    assert "How does hooking work?" in adapter.calls[0]


# --- refine + store (premium sanitization) ---

def _make_store():
    store = MagicMock()
    return store


def test_explain_uses_refine_adapter_when_set():
    chunks = [_chunk("SSDT Hooking")]
    retriever = _make_retriever(chunks)
    local = MockAdapter(response="draft explanation")
    refine = MockAdapter(response="refined explanation")
    session = LearnSession(
        topic="SSDT", retriever=retriever, adapter=local, refine_adapter=refine
    )
    answer, _ = session.explain()
    assert answer == "refined explanation"
    assert len(refine.calls) == 1
    assert "draft explanation" in refine.calls[0]


def test_explain_refine_prompt_contains_topic():
    chunks = [_chunk("SSDT Hooking")]
    retriever = _make_retriever(chunks)
    refine = MockAdapter(response="refined")
    session = LearnSession(
        topic="SSDT Hooking", retriever=retriever,
        adapter=MockAdapter(response="draft"), refine_adapter=refine
    )
    session.explain()
    assert "SSDT Hooking" in refine.calls[0]


def test_explain_stores_refined_chunk_when_embed_and_store_set():
    chunks = [_chunk("SSDT Hooking")]
    retriever = _make_retriever(chunks)
    refine = MockAdapter(response="refined explanation")
    embed_fn = MagicMock(return_value=[0.1, 0.2, 0.3])
    store = _make_store()
    session = LearnSession(
        topic="SSDT", retriever=retriever,
        adapter=MockAdapter(response="draft"), refine_adapter=refine,
        embed_fn=embed_fn, store=store,
    )
    session.explain()
    store.add.assert_called_once()
    call_kwargs = store.add.call_args
    metadatas = call_kwargs[1]["metadatas"] if "metadatas" in call_kwargs[1] else call_kwargs[0][3]
    assert metadatas[0]["generated"] == "true"
    assert metadatas[0]["source_file"] == "generated"


def test_explain_skips_store_without_refine_adapter():
    chunks = [_chunk("SSDT Hooking")]
    retriever = _make_retriever(chunks)
    embed_fn = MagicMock(return_value=[0.1])
    store = _make_store()
    session = LearnSession(
        topic="SSDT", retriever=retriever,
        adapter=MockAdapter(response="draft"),
        embed_fn=embed_fn, store=store,
    )
    session.explain()
    store.add.assert_not_called()


def test_explain_falls_back_to_draft_when_no_refine_adapter():
    chunks = [_chunk("SSDT Hooking")]
    retriever = _make_retriever(chunks)
    local = MockAdapter(response="local draft")
    session = LearnSession(topic="SSDT", retriever=retriever, adapter=local)
    answer, _ = session.explain()
    assert answer == "local draft"


def test_follow_up_uses_refine_adapter():
    chunks = [_chunk("SSDT Hooking")]
    retriever = _make_retriever(chunks)
    local = MockAdapter(response="draft answer")
    refine = MockAdapter(response="refined answer")
    session = LearnSession(
        topic="SSDT", retriever=retriever, adapter=local, refine_adapter=refine
    )
    answer, _ = session.follow_up("How does hooking work?")
    assert answer == "refined answer"


def test_follow_up_stores_refined_chunk():
    chunks = [_chunk("SSDT Hooking")]
    retriever = _make_retriever(chunks)
    refine = MockAdapter(response="refined answer")
    embed_fn = MagicMock(return_value=[0.1, 0.2])
    store = _make_store()
    session = LearnSession(
        topic="SSDT", retriever=retriever,
        adapter=MockAdapter(response="draft"), refine_adapter=refine,
        embed_fn=embed_fn, store=store,
    )
    session.follow_up("How does hooking work?")
    store.add.assert_called_once()


def test_explain_skips_refinement_when_all_chunks_already_generated():
    already_refined = Chunk(
        heading="SSDT", text="already clean text", source_file="generated"
    )
    retriever = _make_retriever([already_refined])
    refine = MockAdapter(response="would refine again")
    session = LearnSession(
        topic="SSDT", retriever=retriever,
        adapter=MockAdapter(response="draft"), refine_adapter=refine,
    )
    session.explain()
    assert len(refine.calls) == 0


def test_follow_up_skips_refinement_when_all_chunks_already_generated():
    already_refined = Chunk(
        heading="SSDT: How does it work", text="already clean answer", source_file="generated"
    )
    retriever = _make_retriever([already_refined])
    refine = MockAdapter(response="would refine again")
    session = LearnSession(
        topic="SSDT", retriever=retriever,
        adapter=MockAdapter(response="draft"), refine_adapter=refine,
    )
    session.follow_up("How does it work?")
    assert len(refine.calls) == 0


def test_explain_refines_when_mix_of_generated_and_original_chunks():
    mixed = [
        Chunk(heading="SSDT", text="generated chunk", source_file="generated"),
        _chunk("SSDT Hooking", "original kb content"),
    ]
    retriever = _make_retriever(mixed)
    refine = MockAdapter(response="refined")
    session = LearnSession(
        topic="SSDT", retriever=retriever,
        adapter=MockAdapter(response="draft"), refine_adapter=refine,
    )
    session.explain()
    assert len(refine.calls) == 1
