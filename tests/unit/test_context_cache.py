import pytest
from engine.context_cache import ContextCache


@pytest.fixture
def cache(tmp_path):
    return ContextCache(tmp_path / "cache.json")


def test_get_returns_none_on_miss(cache):
    assert cache.get("unknown text") is None


def test_set_then_get_returns_value(cache):
    cache.set("chunk text", "context summary")
    assert cache.get("chunk text") == "context summary"


def test_same_text_same_key(cache):
    cache.set("hello", "ctx1")
    assert cache.get("hello") == "ctx1"


def test_different_text_different_key(cache):
    cache.set("text A", "ctx A")
    assert cache.get("text B") is None


def test_save_and_reload_persists_data(tmp_path):
    path = tmp_path / "cache.json"
    c1 = ContextCache(path)
    c1.set("chunk", "my context")
    c1.save()
    c2 = ContextCache(path)
    assert c2.get("chunk") == "my context"


def test_save_creates_parent_dirs(tmp_path):
    path = tmp_path / "nested" / "dir" / "cache.json"
    c = ContextCache(path)
    c.set("x", "y")
    c.save()
    assert path.exists()


def test_overwrite_updates_value(cache):
    cache.set("text", "v1")
    cache.set("text", "v2")
    assert cache.get("text") == "v2"
