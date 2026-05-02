import pytest
from pathlib import Path
from engine.indexer import Indexer
from engine.store import VectorStore


DIM = 4


def fake_embed(text: str) -> list[float]:
    """Deterministic fake embedder — no model required."""
    h = hash(text) & 0xFFFF
    raw = [(h >> i) & 0xFF for i in range(DIM)]
    norm = sum(v ** 2 for v in raw) ** 0.5 or 1.0
    return [v / norm for v in raw]


@pytest.fixture
def kb(tmp_path):
    d = tmp_path / "kb"
    d.mkdir()
    (d / "topic_a.md").write_text(
        "## SSDT Hooking\n\nThe SSDT maps syscall numbers to kernel function addresses.\n\n"
        "## Kernel Callbacks\n\nPsSetCreateProcessNotifyRoutine registers a callback.\n"
    )
    (d / "topic_b.md").write_text(
        "## VBS\n\nVirtualization-Based Security isolates kernel from hypervisor.\n"
    )
    return d


@pytest.fixture
def index_dir(tmp_path):
    return tmp_path / "index"


def make_indexer(kb, index_dir, adapter=None):
    return Indexer(kb_dir=kb, index_dir=index_dir, embed_fn=fake_embed, context_adapter=adapter)


def test_build_full_indexes_all_chunks(kb, index_dir):
    make_indexer(kb, index_dir).build_full()
    store = VectorStore(index_dir / "chroma")
    assert store.count() == 3


def test_build_full_stores_document_text(kb, index_dir):
    make_indexer(kb, index_dir).build_full()
    store = VectorStore(index_dir / "chroma")
    results = store.query(fake_embed("SSDT"), n_results=3)
    docs = [r["document"] for r in results]
    assert any("SSDT" in d for d in docs)


def test_build_full_stores_source_file_metadata(kb, index_dir):
    make_indexer(kb, index_dir).build_full()
    store = VectorStore(index_dir / "chroma")
    results = store.query(fake_embed("x"), n_results=3)
    sources = {r["metadata"]["source_file"] for r in results if r["metadata"]}
    assert any("topic_a.md" in s for s in sources)
    assert any("topic_b.md" in s for s in sources)


def test_build_incremental_skips_unchanged_file(kb, index_dir):
    idx = make_indexer(kb, index_dir)
    idx.build_full()
    count_after_full = VectorStore(index_dir / "chroma").count()
    idx.build_incremental()
    assert VectorStore(index_dir / "chroma").count() == count_after_full


def test_build_incremental_reindexes_changed_file(kb, index_dir):
    make_indexer(kb, index_dir).build_full()
    import os, time
    f = kb / "topic_b.md"
    f.write_text("## New Section\n\nCompletely new content.\n")
    os.utime(f, (f.stat().st_atime, f.stat().st_mtime + 2))
    make_indexer(kb, index_dir).build_incremental()
    store = VectorStore(index_dir / "chroma")
    docs = [r["document"] for r in store.query(fake_embed("x"), n_results=5)]
    assert any("new content" in d.lower() for d in docs)
    assert not any("VBS" in d for d in docs)


def test_build_incremental_removes_deleted_file(kb, index_dir):
    make_indexer(kb, index_dir).build_full()
    (kb / "topic_b.md").unlink()
    make_indexer(kb, index_dir).build_incremental()
    store = VectorStore(index_dir / "chroma")
    results = store.query(fake_embed("x"), n_results=5)
    sources = {r["metadata"]["source_file"] for r in results if r["metadata"]}
    assert not any("topic_b.md" in s for s in sources)


def test_contextual_embedding_calls_adapter(kb, index_dir):
    class CountingAdapter:
        def __init__(self):
            self.calls = []
        def generate(self, prompt: str) -> str:
            self.calls.append(prompt)
            return "context: " + prompt[:30]

    adapter = CountingAdapter()
    make_indexer(kb, index_dir, adapter=adapter).build_full()
    assert len(adapter.calls) == 3


def test_contextual_embedding_caches_per_chunk_text(kb, index_dir):
    class CountingAdapter:
        def __init__(self):
            self.count = 0
        def generate(self, prompt: str) -> str:
            self.count += 1
            return "ctx"

    adapter = CountingAdapter()
    idx = make_indexer(kb, index_dir, adapter=adapter)
    idx.build_full()
    first_count = adapter.count
    idx.build_full()
    assert adapter.count == first_count


def test_empty_markdown_file_produces_no_chunks(kb, index_dir):
    (kb / "empty.md").write_text("")
    make_indexer(kb, index_dir).build_full()
    store = VectorStore(index_dir / "chroma")
    assert store.count() == 3


def test_build_full_indexes_subdir_file(kb, index_dir):
    subdir = kb / "subcat"
    subdir.mkdir()
    (subdir / "topic_c.md").write_text(
        "## Subdir Section\n\nContent from a subdirectory file.\n"
    )
    make_indexer(kb, index_dir).build_full()
    store = VectorStore(index_dir / "chroma")
    docs = [r["document"] for r in store.query(fake_embed("subdir"), n_results=5)]
    assert any("Subdir Section" in d or "subdirectory" in d for d in docs)


def test_build_full_clears_stale_chunks(kb, index_dir):
    make_indexer(kb, index_dir).build_full()
    count_after_first = VectorStore(index_dir / "chroma").count()
    make_indexer(kb, index_dir).build_full()
    assert VectorStore(index_dir / "chroma").count() == count_after_first
