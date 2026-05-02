"""E2E tests for KB CLI commands (Task 17).

Uses typer.testing.CliRunner — no live model or Ollama calls.
All tests that need an index stub out the retriever via monkeypatch
or use a minimal in-memory ChromaDB collection.
"""
import pytest
from typer.testing import CliRunner
from cli.main import app

runner = CliRunner()

_MINIMAL_CONFIG = (
    "mode: local\n"
    "local_model: phi4-mini\n"
    "premium_model: claude-sonnet-4-6\n"
    "api_key_file: Claude-Key.txt\n"
    "embedding_backend: sentence-transformers\n"
    "embedding_model: all-MiniLM-L6-v2\n"
    "quiz:\n"
    "  default_questions: 5\n"
    "  max_questions: 20\n"
    "  show_correct_answer: true\n"
    "  show_kb_excerpt: true\n"
    "retriever:\n"
    "  top_k: 5\n"
    "  min_score: 0.25\n"
    "ptc:\n"
    "  max_output_tokens: 1000\n"
    "logging:\n"
    "  enabled: true\n"
    "  log_dir: logs/\n"
    "  log_compression_ratio: true\n"
)


def _write_config(tmp_path):
    cfg = tmp_path / "config" / "config.yaml"
    cfg.parent.mkdir(parents=True)
    cfg.write_text(_MINIMAL_CONFIG)


# --- kb index ---

def test_kb_index_requires_config(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["kb", "index"])
    assert result.exit_code != 0
    assert "config" in result.output.lower()


def test_kb_index_incremental_no_kb_dir(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_config(tmp_path)
    result = runner.invoke(app, ["kb", "index"])
    assert "complete" in result.output.lower() or result.exit_code == 0


def test_kb_index_rebuild_flag(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_config(tmp_path)
    (tmp_path / "kb").mkdir()
    result = runner.invoke(app, ["kb", "index", "--rebuild"])
    assert "rebuild" in result.output.lower() or "complete" in result.output.lower()


# --- kb list ---

def test_kb_list_no_kb_dir(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_config(tmp_path)
    result = runner.invoke(app, ["kb", "list"])
    assert result.exit_code != 0
    assert "not found" in result.output.lower()


def test_kb_list_empty_kb(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_config(tmp_path)
    (tmp_path / "kb").mkdir()
    result = runner.invoke(app, ["kb", "list"])
    assert result.exit_code == 0


def test_kb_list_shows_files(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_config(tmp_path)
    kb = tmp_path / "kb"
    kb.mkdir()
    (kb / "ssdt.md").write_text("## SSDT\nContent here.\n")
    result = runner.invoke(app, ["kb", "list"])
    assert result.exit_code == 0
    assert "ssdt.md" in result.output


def test_kb_list_shows_subdir_files(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_config(tmp_path)
    kb = tmp_path / "kb"
    (kb / "windows-kernel").mkdir(parents=True)
    (kb / "windows-kernel" / "ssdt.md").write_text("## SSDT\nContent here.\n")
    result = runner.invoke(app, ["kb", "list"])
    assert result.exit_code == 0
    assert "ssdt.md" in result.output


# --- kb add ---

def test_kb_add_copies_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_config(tmp_path)
    (tmp_path / "kb").mkdir()
    src = tmp_path / "myfile.md"
    src.write_text("## Topic\nContent.\n")
    result = runner.invoke(app, ["kb", "add", str(src)])
    assert result.exit_code == 0
    assert (tmp_path / "kb" / "myfile.md").exists()


def test_kb_add_rejects_non_md(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_config(tmp_path)
    result = runner.invoke(app, ["kb", "add", "file.txt"])
    assert result.exit_code != 0
    assert ".md" in result.output


def test_kb_add_with_subdir(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_config(tmp_path)
    (tmp_path / "kb").mkdir()
    src = tmp_path / "myfile.md"
    src.write_text("## Topic\nContent.\n")
    result = runner.invoke(app, ["kb", "add", str(src), "--subdir", "windows-kernel"])
    assert result.exit_code == 0
    assert (tmp_path / "kb" / "windows-kernel" / "myfile.md").exists()


# --- kb remove ---

def test_kb_remove_missing_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_config(tmp_path)
    result = runner.invoke(app, ["kb", "remove", "nonexistent.md"])
    assert result.exit_code != 0
    assert "not found" in result.output.lower()


def test_kb_remove_deletes_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_config(tmp_path)
    kb = tmp_path / "kb"
    kb.mkdir()
    (kb / "ssdt.md").write_text("## SSDT\nContent.\n")
    result = runner.invoke(app, ["kb", "remove", "ssdt.md"], input="y\n")
    assert result.exit_code == 0
    assert not (kb / "ssdt.md").exists()


# --- kb search ---

def test_kb_search_no_index(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_config(tmp_path)
    result = runner.invoke(app, ["kb", "search", "SSDT"])
    assert result.exit_code != 0
    assert "index" in result.output.lower()


# --- kb learn ---

def test_kb_learn_no_index(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_config(tmp_path)
    result = runner.invoke(app, ["kb", "learn", "SSDT"])
    assert result.exit_code != 0
    assert "index" in result.output.lower()


def test_kb_learn_no_content(tmp_path, monkeypatch):
    """When retriever returns no chunks, prints friendly message."""
    monkeypatch.chdir(tmp_path)
    _write_config(tmp_path)
    (tmp_path / "kb_index").mkdir()

    from engine.question import Chunk
    from unittest.mock import MagicMock, patch

    mock_retriever = MagicMock()
    mock_retriever.search.return_value = []

    with patch("cli.main.Retriever", return_value=mock_retriever), \
         patch("cli.main.make_embed_fn", return_value=lambda t: [0.0]):
        result = runner.invoke(app, ["kb", "learn", "quantum computing"])

    assert "No KB content" in result.output or result.exit_code == 0
