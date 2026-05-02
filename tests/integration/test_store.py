import pytest
from engine.store import VectorStore


@pytest.fixture
def store(tmp_path):
    return VectorStore(persist_dir=tmp_path)


def test_empty_store_count_zero(store):
    assert store.count() == 0


def test_add_and_count(store):
    store.add(
        ids=["a", "b"],
        embeddings=[[1.0, 0.0], [0.0, 1.0]],
        documents=["doc a", "doc b"],
        metadatas=[{"src": "f.md"}, {"src": "f.md"}],
    )
    assert store.count() == 2


def test_get_ids(store):
    store.add(ids=["x"], embeddings=[[1.0, 0.0]], documents=["doc"], metadatas=[{}])
    assert "x" in store.get_ids()


def test_query_returns_closest(store):
    store.add(
        ids=["near", "far"],
        embeddings=[[1.0, 0.0], [0.0, 1.0]],
        documents=["near doc", "far doc"],
        metadatas=[{}, {}],
    )
    results = store.query(embedding=[1.0, 0.0], n_results=2)
    assert results[0]["id"] == "near"
    assert results[0]["score"] >= results[1]["score"]


def test_query_score_in_range(store):
    store.add(ids=["a"], embeddings=[[1.0, 0.0]], documents=["doc"], metadatas=[{}])
    results = store.query(embedding=[1.0, 0.0], n_results=1)
    assert 0.0 <= results[0]["score"] <= 1.0


def test_delete_removes_entry(store):
    store.add(ids=["to_delete"], embeddings=[[1.0, 0.0]], documents=["doc"], metadatas=[{}])
    store.delete(ids=["to_delete"])
    assert store.count() == 0


def test_delete_empty_list_is_noop(store):
    store.add(ids=["a"], embeddings=[[1.0, 0.0]], documents=["doc"], metadatas=[{}])
    store.delete(ids=[])
    assert store.count() == 1


def test_upsert_updates_existing(store):
    store.add(ids=["a"], embeddings=[[1.0, 0.0]], documents=["original"], metadatas=[{}])
    store.add(ids=["a"], embeddings=[[0.0, 1.0]], documents=["updated"], metadatas=[{}])
    assert store.count() == 1
    results = store.query(embedding=[0.0, 1.0], n_results=1)
    assert results[0]["document"] == "updated"


def test_query_on_empty_store_returns_empty(store):
    assert store.query(embedding=[1.0, 0.0], n_results=5) == []


def test_get_ids_on_empty_store_returns_empty(store):
    assert store.get_ids() == []


def test_delete_by_source_removes_matching_chunks(store):
    store.add(
        ids=["a1", "a2", "b1"],
        embeddings=[[1.0, 0.0], [0.9, 0.1], [0.0, 1.0]],
        documents=["doc a1", "doc a2", "doc b1"],
        metadatas=[
            {"source_file": "a.md"},
            {"source_file": "a.md"},
            {"source_file": "b.md"},
        ],
    )
    store.delete_by_source("a.md")
    assert store.count() == 1
    assert store.get_ids() == ["b1"]


def test_delete_by_source_unknown_file_is_noop(store):
    store.add(ids=["a"], embeddings=[[1.0, 0.0]], documents=["doc"], metadatas=[{"source_file": "a.md"}])
    store.delete_by_source("nonexistent.md")
    assert store.count() == 1


def test_delete_by_source_on_empty_store_is_noop(store):
    store.delete_by_source("any.md")
    assert store.count() == 0


def test_clear_removes_all_documents(store):
    store.add(
        ids=["a", "b", "c"],
        embeddings=[[1.0, 0.0], [0.0, 1.0], [0.5, 0.5]],
        documents=["doc a", "doc b", "doc c"],
        metadatas=[{}, {}, {}],
    )
    assert store.count() == 3
    store.clear()
    assert store.count() == 0


def test_clear_allows_new_adds_after_clear(store):
    store.add(ids=["a"], embeddings=[[1.0, 0.0]], documents=["doc"], metadatas=[{}])
    store.clear()
    store.add(ids=["b"], embeddings=[[0.0, 1.0]], documents=["new doc"], metadatas=[{}])
    assert store.count() == 1
    assert store.get_ids() == ["b"]


def test_clear_on_empty_store_is_noop(store):
    store.clear()
    assert store.count() == 0
