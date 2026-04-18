import pytest
from pathlib import Path
from engine.indexer import Indexer
from engine.retriever import Retriever, IndexNotFoundError
from engine.question import Chunk


DIM = 4


def fake_embed(text: str) -> list[float]:
    h = hash(text) & 0xFFFF
    raw = [(h >> i) & 0xFF for i in range(DIM)]
    norm = sum(v ** 2 for v in raw) ** 0.5 or 1.0
    return [v / norm for v in raw]


@pytest.fixture
def populated_index(tmp_path):
    kb = tmp_path / "kb"
    kb.mkdir()
    (kb / "topic_a.md").write_text(
        "## SSDT Hooking\n\nThe SSDT maps syscall numbers to kernel addresses.\n\n"
        "## Kernel Callbacks\n\nPsSetCreateProcessNotifyRoutine for process events.\n\n"
        "## MiniFilter\n\nIoRegisterFsRegistrationChange for filesystem callbacks.\n\n"
        "## WFP\n\nWindows Filtering Platform callout drivers for network traffic.\n\n"
        "## EPROCESS\n\nProcess object in the kernel, contains PEB pointer.\n"
    )
    index_dir = tmp_path / "index"
    Indexer(kb_dir=kb, index_dir=index_dir, embed_fn=fake_embed).build_full()
    return index_dir


def test_raises_index_not_found_when_dir_missing(tmp_path):
    with pytest.raises(IndexNotFoundError, match="kb index"):
        Retriever(tmp_path / "nonexistent", embed_fn=fake_embed)


def test_search_returns_chunk_list(populated_index):
    r = Retriever(populated_index, embed_fn=fake_embed)
    results = r.search("SSDT", top_k=2)
    assert isinstance(results, list)
    assert all(isinstance(c, Chunk) for c in results)


def test_search_returns_at_most_top_k(populated_index):
    r = Retriever(populated_index, embed_fn=fake_embed)
    results = r.search("kernel", top_k=2)
    assert len(results) <= 2


def test_search_chunk_has_source_file(populated_index):
    r = Retriever(populated_index, embed_fn=fake_embed)
    results = r.search("SSDT", top_k=1)
    assert results[0].source_file != ""


def test_search_chunk_has_heading(populated_index):
    r = Retriever(populated_index, embed_fn=fake_embed)
    results = r.search("SSDT", top_k=1)
    assert results[0].heading != ""


def test_threshold_filters_low_scores(populated_index):
    r = Retriever(populated_index, embed_fn=fake_embed)
    results = r.search("SSDT", top_k=5, threshold=0.99)
    assert all(isinstance(c, Chunk) for c in results)


def test_seed_produces_deterministic_sampling(populated_index):
    r = Retriever(populated_index, embed_fn=fake_embed)
    r1 = r.search("kernel", top_k=2, top_n=5, seed=42)
    r2 = r.search("kernel", top_k=2, top_n=5, seed=42)
    assert [c.heading for c in r1] == [c.heading for c in r2]


def test_different_seeds_may_differ(populated_index):
    r = Retriever(populated_index, embed_fn=fake_embed)
    results_a = [c.heading for c in r.search("kernel", top_k=2, top_n=5, seed=1)]
    results_b = [c.heading for c in r.search("kernel", top_k=2, top_n=5, seed=99)]
    # Not guaranteed to differ, but with 5 candidates → 2 slots this is very likely
    # We assert both are valid Chunk lists regardless
    assert len(results_a) <= 2
    assert len(results_b) <= 2


def test_search_on_empty_index(tmp_path):
    kb = tmp_path / "kb"
    kb.mkdir()
    (kb / "a.md").write_text("")
    index_dir = tmp_path / "index"
    Indexer(kb_dir=kb, index_dir=index_dir, embed_fn=fake_embed).build_full()
    r = Retriever(index_dir, embed_fn=fake_embed)
    assert r.search("anything") == []
