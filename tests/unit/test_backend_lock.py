"""Unit tests for engine.backend_lock and cli._detect_embedding_backend / _resolve_backend."""
import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock


# ── backend_lock module ───────────────────────────────────────────────────────

def test_read_lock_returns_none_when_missing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from engine.backend_lock import read_lock
    assert read_lock() is None


def test_write_then_read_lock(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from engine.backend_lock import write_lock, read_lock
    write_lock("ollama", "nomic-embed-text", None)
    lock = read_lock()
    assert lock["backend"] == "ollama"
    assert lock["model"] == "nomic-embed-text"
    assert lock["dimensions"] is None


def test_clear_lock_removes_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from engine.backend_lock import write_lock, clear_lock, read_lock
    write_lock("gemini", "gemini-embedding-001", 768)
    clear_lock()
    assert read_lock() is None


def test_clear_lock_is_noop_when_missing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from engine.backend_lock import clear_lock
    clear_lock()  # should not raise


def test_write_lock_creates_parent_dirs(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from engine.backend_lock import write_lock
    write_lock("sentence-transformers", "all-MiniLM-L6-v2", None)
    lock_path = tmp_path / "kb_index" / "backend_lock.json"
    assert lock_path.exists()
    data = json.loads(lock_path.read_text())
    assert data["backend"] == "sentence-transformers"


# ── _detect_embedding_backend ────────────────────────────────────────────────

def _import_detect():
    # Import after patching to avoid module-level side effects
    import importlib, cli.main as m
    importlib.reload(m)
    return m._detect_embedding_backend


def test_detect_returns_gemini_when_env_key_set(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GEMINI_API_KEY", "AIza-test")
    from cli.main import _detect_embedding_backend
    backend, model, dims = _detect_embedding_backend({})
    assert backend == "gemini"
    assert model == "gemini-embedding-001"
    assert dims == 768


def test_detect_returns_gemini_when_key_file_present(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    (tmp_path / "Gemini-Key.txt").write_text("AIza-from-file")
    from cli.main import _detect_embedding_backend
    backend, model, dims = _detect_embedding_backend({"gemini_api_key_file": "Gemini-Key.txt"})
    assert backend == "gemini"


def test_detect_returns_ollama_when_reachable(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    import httpx
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    with patch("httpx.get", return_value=mock_resp):
        from cli.main import _detect_embedding_backend
        backend, model, dims = _detect_embedding_backend({})
    assert backend == "ollama"
    assert dims is None


def test_detect_falls_back_to_st_when_ollama_unreachable(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    import httpx
    with patch("httpx.get", side_effect=httpx.ConnectError("refused")):
        from cli.main import _detect_embedding_backend
        backend, model, dims = _detect_embedding_backend({})
    assert backend == "sentence-transformers"
    assert dims is None


# ── _resolve_backend ─────────────────────────────────────────────────────────

def test_resolve_returns_cfg_unchanged_when_not_auto(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from cli.main import _resolve_backend
    cfg = {"embedding_backend": "ollama", "embedding_model": "nomic-embed-text"}
    assert _resolve_backend(cfg) is cfg


def test_resolve_reads_lock_when_auto(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from engine.backend_lock import write_lock
    write_lock("ollama", "nomic-embed-text", None)
    from cli.main import _resolve_backend
    resolved = _resolve_backend({"embedding_backend": "auto"})
    assert resolved["embedding_backend"] == "ollama"
    assert resolved["embedding_model"] == "nomic-embed-text"


def test_resolve_detects_and_writes_lock_when_missing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GEMINI_API_KEY", "AIza-test")
    from engine.backend_lock import read_lock
    assert read_lock() is None  # no lock yet
    from cli.main import _resolve_backend
    resolved = _resolve_backend({"embedding_backend": "auto"})
    assert resolved["embedding_backend"] == "gemini"
    lock = read_lock()
    assert lock is not None
    assert lock["backend"] == "gemini"


def test_resolve_gemini_lock_sets_model_and_dimensions(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from engine.backend_lock import write_lock
    write_lock("gemini", "gemini-embedding-001", 768)
    from cli.main import _resolve_backend
    resolved = _resolve_backend({"embedding_backend": "auto"})
    assert resolved["gemini_embedding_model"] == "gemini-embedding-001"
    assert resolved["embedding_dimensions"] == 768
