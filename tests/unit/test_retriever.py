"""Unit tests for Retriever hybrid BM25 + semantic search with RRF."""
import pytest
from unittest.mock import MagicMock

from engine.retriever import Retriever, _tokenize


# ── helpers ──────────────────────────────────────────────────────────────────

def _make_retriever(store_docs: list[dict]) -> Retriever:
    """Build a Retriever with a mock store, bypassing __init__ filesystem checks."""
    r = object.__new__(Retriever)
    r._embed_fn = lambda text: [0.1, 0.2, 0.3]
    r._store = MagicMock()
    r._store.get_all.return_value = store_docs
    r._store.count.return_value = len(store_docs)
    r._bm25 = None
    r._bm25_corpus = []
    return r


def _semantic_result(id_: str, doc: str, score: float, meta: dict | None = None) -> dict:
    return {"id": id_, "document": doc, "score": score, "metadata": meta or {}}


# ── tokenizer ────────────────────────────────────────────────────────────────

def test_tokenize_lowercases():
    assert _tokenize("Prompt Caching") == ["prompt", "caching"]


def test_tokenize_strips_punctuation():
    assert _tokenize("hello, world!") == ["hello", "world"]


def test_tokenize_empty():
    assert _tokenize("") == []


# ── RRF merge ────────────────────────────────────────────────────────────────

def test_rrf_boosts_doc_appearing_in_both_lists():
    r = _make_retriever([])
    semantic = [
        _semantic_result("a", "doc a", 0.9),
        _semantic_result("b", "doc b", 0.5),
    ]
    bm25 = [
        {"id": "b", "document": "doc b", "metadata": {}, "bm25_score": 5.0},
        {"id": "c", "document": "doc c", "metadata": {}, "bm25_score": 3.0},
    ]
    merged = r._rrf_merge(semantic, bm25)
    by_id = {m["id"]: m["rrf_score"] for m in merged}

    # "b" appears in both lists so its RRF score must exceed "a" (semantic only)
    # and "c" (BM25 only)
    assert by_id["b"] > by_id["a"]
    assert by_id["b"] > by_id["c"]


def test_rrf_includes_bm25_only_docs():
    r = _make_retriever([])
    semantic = [_semantic_result("a", "doc a", 0.9)]
    bm25 = [{"id": "z", "document": "doc z", "metadata": {}, "bm25_score": 10.0}]
    merged = r._rrf_merge(semantic, bm25)
    assert {m["id"] for m in merged} == {"a", "z"}


def test_rrf_merge_preserves_document_text():
    r = _make_retriever([])
    semantic = [_semantic_result("x", "the actual content", 0.8)]
    merged = r._rrf_merge(semantic, [])
    assert merged[0]["document"] == "the actual content"


# ── BM25 keyword matching ─────────────────────────────────────────────────────

_BM25_CORPUS = [
    {"id": "llm", "document": "Prompt caching stores repeated LLM prefixes to reduce latency.", "metadata": {}},
    {"id": "fs",  "document": "File system stores recently accessed disk blocks on disk.", "metadata": {}},
    {"id": "net", "document": "Network packet inspection rules for firewall policies.", "metadata": {}},
    {"id": "db",  "document": "Database query optimizer uses index scans for filtering rows.", "metadata": {}},
]


def test_bm25_scores_keyword_match_above_zero():
    r = _make_retriever(_BM25_CORPUS)
    results = r._bm25_search("prompt caching", n=5)
    ids = [res["id"] for res in results]

    # "prompt" and "caching" only appear in the llm doc — it must rank first
    assert len(results) >= 1
    assert ids[0] == "llm"


def test_bm25_returns_empty_for_zero_scoring_query():
    docs = [{"id": "x", "document": "Windows kernel minifilter driver.", "metadata": {}}]
    r = _make_retriever(docs)
    results = r._bm25_search("zzzzunknownterm", n=5)
    assert results == []


def test_bm25_lazy_build_called_once():
    docs = [{"id": "a", "document": "some text about caching", "metadata": {}}]
    r = _make_retriever(docs)
    r._bm25_search("caching", n=3)
    r._bm25_search("caching", n=3)
    # get_all should be called only once — BM25 is cached after first build
    assert r._store.get_all.call_count == 1


# ── hybrid search end-to-end ─────────────────────────────────────────────────

def test_search_returns_chunks():
    docs = [
        {"id": "a", "document": "Prompt caching in LLMs.", "metadata": {"source_file": "llm.md", "heading": "Caching"}},
    ]
    r = _make_retriever(docs)
    r._store.query.return_value = [
        _semantic_result("a", "Prompt caching in LLMs.", 0.9, {"source_file": "llm.md", "heading": "Caching"})
    ]
    chunks = r.search("prompt caching", top_k=1)
    assert len(chunks) == 1
    assert chunks[0].heading == "Caching"
    assert chunks[0].source_file == "llm.md"


def test_search_keyword_beats_semantic_confusion():
    """Core fix: 'prompt caching' should not return Windows kernel docs.

    When semantic search is confused (Windows doc scores higher due to the word
    'cache'), BM25 promotes the LLM doc because the exact phrase 'prompt caching'
    only appears there. With top_k=2 both are in the candidate pool; RRF gives
    the LLM doc a higher combined score and it surfaces first.
    """
    # BM25Okapi IDF requires >2 docs for unique terms to score non-zero.
    # Padding docs ensure "prompt" and "caching" only appear in llm, giving
    # it a non-zero BM25 score while win scores 0 (no query term overlap).
    docs = [
        {"id": "llm", "document": "Prompt caching stores repeated LLM prefixes to reduce latency.", "metadata": {"source_file": "llm.md", "heading": "Prompt Caching"}},
        {"id": "win", "document": "Windows file system cache stores recently read disk blocks in RAM.", "metadata": {"source_file": "win.md", "heading": "File Cache"}},
        {"id": "net", "document": "Network packet inspection rules for firewall policies.", "metadata": {}},
        {"id": "db",  "document": "Database query optimizer uses index scans for filtering rows.", "metadata": {}},
    ]
    r = _make_retriever(docs)

    # Semantic is confused: Windows doc ranks first
    r._store.query.return_value = [
        _semantic_result("win", docs[1]["document"], 0.75, docs[1]["metadata"]),
        _semantic_result("llm", docs[0]["document"], 0.65, docs[0]["metadata"]),
    ]

    # top_k=2, top_n=None → fetch=2, both docs in semantic pool, no random sampling.
    # BM25 scores llm > 0 and win = 0 (no "prompt"/"caching" in win) → win filtered
    # from BM25 list → RRF gives llm a higher combined score than win.
    chunks = r.search("prompt caching", top_k=2, top_n=None)

    # BM25 promotes LLM doc — it should be first by RRF score
    assert chunks[0].source_file == "llm.md"


def test_cap_generated_limits_to_max():
    r = _make_retriever([])
    pool = [
        {"id": "g1", "document": "gen 1", "metadata": {"source_file": "generated"}, "rrf_score": 0.9},
        {"id": "g2", "document": "gen 2", "metadata": {"source_file": "generated"}, "rrf_score": 0.8},
        {"id": "kb", "document": "kb doc", "metadata": {"source_file": "kb/file.md"}, "rrf_score": 0.7},
    ]
    result = r._cap_generated(pool, max_generated=1)
    ids = [x["id"] for x in result]
    assert ids == ["g1", "kb"]


def test_cap_generated_zero_excludes_all_generated():
    r = _make_retriever([])
    pool = [
        {"id": "g1", "document": "gen", "metadata": {"source_file": "generated"}, "rrf_score": 0.9},
        {"id": "kb", "document": "kb", "metadata": {"source_file": "kb/file.md"}, "rrf_score": 0.5},
    ]
    result = r._cap_generated(pool, max_generated=0)
    assert [x["id"] for x in result] == ["kb"]


def test_cap_generated_preserves_order_and_kb_chunks():
    r = _make_retriever([])
    pool = [
        {"id": "g1", "document": "g", "metadata": {"source_file": "generated"}, "rrf_score": 1.0},
        {"id": "g2", "document": "g", "metadata": {"source_file": "generated"}, "rrf_score": 0.9},
        {"id": "g3", "document": "g", "metadata": {"source_file": "generated"}, "rrf_score": 0.8},
        {"id": "k1", "document": "k", "metadata": {"source_file": "kb/a.md"},   "rrf_score": 0.7},
        {"id": "k2", "document": "k", "metadata": {"source_file": "kb/b.md"},   "rrf_score": 0.6},
    ]
    result = r._cap_generated(pool, max_generated=1)
    ids = [x["id"] for x in result]
    assert ids == ["g1", "k1", "k2"]


def test_search_caps_generated_chunks_by_default():
    """Default max_generated=1 means at most one generated chunk in results."""
    docs = [
        {"id": "g1", "document": "generated explanation of injection", "metadata": {"source_file": "generated"}},
        {"id": "g2", "document": "generated follow-up on injection",   "metadata": {"source_file": "generated"}},
        {"id": "kb", "document": "T1055 process injection technique",  "metadata": {"source_file": "kb/t1055.md", "heading": "T1055"}},
    ]
    r = _make_retriever(docs)
    r._store.query.return_value = [
        _semantic_result("g1", docs[0]["document"], 0.95, docs[0]["metadata"]),
        _semantic_result("g2", docs[1]["document"], 0.90, docs[1]["metadata"]),
        _semantic_result("kb", docs[2]["document"], 0.80, docs[2]["metadata"]),
    ]
    chunks = r.search("process injection", top_k=3, top_n=None)
    generated_count = sum(1 for c in chunks if c.source_file == "generated")
    assert generated_count <= 1


def test_search_empty_index_returns_empty():
    r = _make_retriever([])
    r._store.query.return_value = []
    chunks = r.search("anything", top_k=5)
    assert chunks == []


def test_search_threshold_filters_low_semantic_scores():
    docs = [{"id": "a", "document": "some content", "metadata": {}}]
    r = _make_retriever(docs)
    # Return a result below threshold; no BM25 matches either
    r._store.query.return_value = [_semantic_result("a", "some content", 0.1)]
    chunks = r.search("query", top_k=5, threshold=0.5)
    assert chunks == []
