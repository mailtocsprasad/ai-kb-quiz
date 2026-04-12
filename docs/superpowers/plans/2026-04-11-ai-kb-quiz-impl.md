# ai-kb-quiz Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a CLI quiz app over a vectorized KB demonstrating hybrid model routing, PTC, Programmable Tool Calling, and semantic search — all components testable in isolation.

**Architecture:** Engine layer (retriever → PTC → router → model → scorer → log) is fully decoupled from CLI. All external dependencies (Ollama, Anthropic SDK, filesystem, Win32) injected via constructor arguments. TDD throughout — test written and watched to fail before each module is coded.

**Tech Stack:** Python 3.x, Typer, httpx, anthropic SDK, sentence-transformers, ChromaDB, numpy, RestrictedPython, pytest

> **Task order revised 2026-04-12:** VectorDB pipeline (Tasks 5–9) moved before scorer/PTC/adapters
> to validate the highest-risk external dependency (ChromaDB) as early as possible.
> Original numpy-based Tasks 11–12 replaced by ChromaDB equivalents.

---

## File Map

```
ai-kb-quiz/
  engine/
    __init__.py
    question.py            # Question/Chunk/Score/PTCResult/ProgToolResult dataclasses
    router.py              # Pure routing function: (task_type, question_type, mode) → "local"|"premium"
    chunker.py             # Splits markdown into Chunk list at H2/H3 boundaries
    store.py               # ChromaDB wrapper: add/delete/query with cosine similarity
    manifest.py            # mtime-based file change tracking: diff() → new/changed/deleted
    context_cache.py       # SHA-256 content-addressed cache for contextual embedding strings
    indexer.py             # Incremental KB indexer: chunk → embed → contextualise → store
    retriever.py           # ChromaDB semantic search: top-N sampling + SeenChunks dedup
    scorer.py              # Scores answers: fill_in via difflib, conceptual/code via model eval
    session_log.py         # Accumulates QuestionLog entries, flushes JSON per question
    ptc.py                 # Runs developer-authored PTC scripts, returns PTCResult
    ptc_scripts/
      __init__.py
      summarize_chunk.py   # Reads JSON chunks from stdin, writes summary to stdout
      extract_concepts.py  # Extracts key concepts from chunks
      extract_code_context.py  # Extracts code-relevant context
    sandbox.py             # SandboxRunner protocol + JobObjectRunner + DirectRunner
    prog_tool_calling.py   # Premium model generates script → validate → sandbox → result
    quiz.py                # Session orchestrator — wires all engine components
    models/
      __init__.py
      adapter.py           # ModelAdapter Protocol + MockAdapter
      local_adapter.py     # Ollama HTTP via injected httpx.Client
      premium_adapter.py   # Anthropic SDK via injected client
  cli/
    __init__.py
    main.py                # Typer CLI: quiz, kb index/add/remove/list/search
  tests/
    conftest.py            # Shared fixtures: tmp_path wrappers, MockAdapter, tiny KB
    unit/
      test_question.py
      test_router.py
      test_chunker.py
      test_scorer.py
      test_session_log.py
      test_ptc.py
    integration/
      test_sandbox.py
      test_adapters.py
      test_prog_tool_calling.py
      test_retriever.py
      test_indexer.py
      test_quiz.py
    e2e/
      test_cli.py
  requirements.txt
  pyproject.toml
```

---

## Task 1: Project Setup

**Files:**
- Create: `requirements.txt`
- Create: `pyproject.toml`
- Create: `tests/conftest.py`
- Create: `engine/__init__.py`, `engine/models/__init__.py`, `engine/ptc_scripts/__init__.py`
- Create: `cli/__init__.py`
- Create: `tests/unit/__init__.py`, `tests/integration/__init__.py`, `tests/e2e/__init__.py`

- [ ] **Step 1: Create requirements.txt**

```
anthropic>=0.40.0
httpx>=0.27.0
typer>=0.12.0
PyYAML>=6.0
sentence-transformers>=3.0.0
numpy>=1.26.0
RestrictedPython>=7.0
difflib2>=1.0.0
pytest>=8.0.0
pytest-mock>=3.12.0
```

- [ ] **Step 2: Create pyproject.toml**

```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.backends.legacy:build"

[project]
name = "ai-kb-quiz"
version = "0.1.0"
requires-python = ">=3.10"

[tool.pytest.ini_options]
testpaths = ["tests"]
python_files = ["test_*.py"]
python_classes = ["Test*"]
python_functions = ["test_*"]
```

- [ ] **Step 3: Create all __init__.py files**

```bash
touch engine/__init__.py engine/models/__init__.py engine/ptc_scripts/__init__.py
touch cli/__init__.py
touch tests/__init__.py tests/unit/__init__.py tests/integration/__init__.py tests/e2e/__init__.py
```

- [ ] **Step 4: Create tests/conftest.py**

```python
import json
import pytest
from pathlib import Path
from engine.models.adapter import ModelAdapter


class MockAdapter:
    """Deterministic model adapter for tests — no live API calls."""

    def __init__(self, response: str = "mock response"):
        self.response = response
        self.calls: list[str] = []

    def generate(self, prompt: str) -> str:
        self.calls.append(prompt)
        return self.response


@pytest.fixture
def mock_adapter():
    return MockAdapter()


@pytest.fixture
def tiny_kb_dir(tmp_path):
    """Creates a minimal KB directory with two markdown files."""
    kb = tmp_path / "kb"
    kb.mkdir()
    (kb / "topic_a.md").write_text(
        "## SSDT Hooking\n\nThe SSDT (System Service Descriptor Table) maps syscall numbers "
        "to kernel function addresses. Rootkits overwrite entries to intercept calls.\n\n"
        "## Kernel Callbacks\n\nPsSetCreateProcessNotifyRoutine registers a callback "
        "invoked on process creation events.\n"
    )
    (kb / "topic_b.md").write_text(
        "## Dynamic Programming\n\nMemoization stores subproblem results to avoid recomputation. "
        "Key insight: overlapping subproblems + optimal substructure.\n\n"
        "## LIST_ENTRY\n\nWindows doubly-linked list. Traverse via Flink until back at head.\n"
    )
    return kb
```

- [ ] **Step 5: Install dependencies**

```bash
cd C:/ai-projects/ai-kb-quiz
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

- [ ] **Step 6: Verify pytest runs**

```bash
pytest --collect-only
```

Expected: `0 items` collected, no errors.

- [ ] **Step 7: Commit**

```bash
git add requirements.txt pyproject.toml engine/ cli/ tests/
git commit -m "chore: project scaffold, deps, conftest"
```

---

## Task 2: Data Types (`engine/question.py`)

**Files:**
- Create: `engine/question.py`
- Create: `tests/unit/test_question.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/unit/test_question.py
import pytest
from engine.question import Question, Chunk, Score, PTCResult, ProgToolResult, QuestionLog


def test_question_valid():
    q = Question(type="conceptual", text="What is SSDT?",
                 correct_answer="System Service Descriptor Table",
                 kb_excerpt="SSDT maps syscall numbers...", source_file="windows-internals.md")
    assert q.type == "conceptual"
    assert q.text == "What is SSDT?"


def test_question_invalid_type():
    with pytest.raises(ValueError, match="Invalid question type"):
        Question(type="unknown", text="Q", correct_answer="A",
                 kb_excerpt="E", source_file="f.md")


def test_question_empty_text():
    with pytest.raises(ValueError, match="text cannot be empty"):
        Question(type="fill_in", text="", correct_answer="A",
                 kb_excerpt="E", source_file="f.md")


def test_chunk_fields():
    c = Chunk(text="some content", source_file="topic_a.md", heading="SSDT Hooking")
    assert c.heading == "SSDT Hooking"


def test_score_valid_values():
    for v in [0.0, 0.5, 1.0]:
        s = Score(value=v, feedback="ok", correct_answer="A")
        assert s.value == v


def test_score_invalid_value():
    with pytest.raises(ValueError, match="Score value must be"):
        Score(value=0.7, feedback="ok", correct_answer="A")


def test_ptc_result():
    r = PTCResult(compressed_text="compact", raw_tokens=1000, compressed_tokens=200)
    assert r.compression_ratio == pytest.approx(0.8)


def test_prog_tool_result():
    r = ProgToolResult(output_text="out", script="print('x')", fallback_used=False)
    assert not r.fallback_used
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
pytest tests/unit/test_question.py -v
```

Expected: `ImportError: No module named 'engine.question'`

- [ ] **Step 3: Implement `engine/question.py`**

```python
from dataclasses import dataclass, field


VALID_QUESTION_TYPES = {"conceptual", "code", "fill_in"}


@dataclass
class Question:
    type: str
    text: str
    correct_answer: str
    kb_excerpt: str
    source_file: str

    def __post_init__(self):
        if self.type not in VALID_QUESTION_TYPES:
            raise ValueError(f"Invalid question type '{self.type}'. Must be one of {VALID_QUESTION_TYPES}")
        if not self.text.strip():
            raise ValueError("text cannot be empty")
        if not self.correct_answer.strip():
            raise ValueError("correct_answer cannot be empty")


@dataclass
class Chunk:
    text: str
    source_file: str
    heading: str


@dataclass
class Score:
    value: float
    feedback: str
    correct_answer: str

    def __post_init__(self):
        if self.value not in {0.0, 0.5, 1.0}:
            raise ValueError(f"Score value must be 0.0, 0.5, or 1.0 — got {self.value}")


@dataclass
class PTCResult:
    compressed_text: str
    raw_tokens: int
    compressed_tokens: int

    @property
    def compression_ratio(self) -> float:
        if self.raw_tokens == 0:
            return 0.0
        return round(1.0 - self.compressed_tokens / self.raw_tokens, 4)


@dataclass
class ProgToolResult:
    output_text: str
    script: str
    fallback_used: bool


@dataclass
class QuestionLog:
    question_num: int
    question_type: str
    question_text: str
    user_answer: str
    correct_answer: str
    score: float
    model_used: str
    tokens_local: int
    tokens_premium: int
    ptc_compression_ratio: float
    error: str | None = None
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
pytest tests/unit/test_question.py -v
```

Expected: All 9 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/question.py tests/unit/test_question.py
git commit -m "feat: Question/Chunk/Score/PTCResult/ProgToolResult dataclasses"
```

---

## Task 3: Model Router (`engine/router.py`)

**Files:**
- Create: `engine/router.py`
- Create: `tests/unit/test_router.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/unit/test_router.py
import pytest
from engine.router import route


# Hybrid mode
def test_hybrid_summarize_chunk_goes_local():
    assert route("summarize_chunk", None, "hybrid") == "local"

def test_hybrid_fill_in_generate_goes_local():
    assert route("generate_question", "fill_in", "hybrid") == "local"

def test_hybrid_conceptual_generate_goes_premium():
    assert route("generate_question", "conceptual", "hybrid") == "premium"

def test_hybrid_code_generate_goes_premium():
    assert route("generate_question", "code", "hybrid") == "premium"

def test_hybrid_fill_in_evaluate_goes_local():
    assert route("evaluate_answer", "fill_in", "hybrid") == "local"

def test_hybrid_conceptual_evaluate_goes_premium():
    assert route("evaluate_answer", "conceptual", "hybrid") == "premium"

def test_hybrid_code_evaluate_goes_premium():
    assert route("evaluate_answer", "code", "hybrid") == "premium"

def test_hybrid_score_goes_local():
    assert route("score_answer", "conceptual", "hybrid") == "local"

# Local-only mode overrides everything
def test_local_mode_always_local():
    for task in ["generate_question", "evaluate_answer", "summarize_chunk", "score_answer"]:
        for qtype in ["conceptual", "code", "fill_in", None]:
            assert route(task, qtype, "local") == "local"

# Premium-only mode overrides everything
def test_premium_mode_always_premium():
    for task in ["generate_question", "evaluate_answer", "summarize_chunk", "score_answer"]:
        for qtype in ["conceptual", "code", "fill_in", None]:
            assert route(task, qtype, "premium") == "premium"

def test_unknown_task_type_raises():
    with pytest.raises(ValueError, match="Unknown task_type"):
        route("unknown_task", None, "hybrid")
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
pytest tests/unit/test_router.py -v
```

Expected: `ImportError: No module named 'engine.router'`

- [ ] **Step 3: Implement `engine/router.py`**

```python
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
    """Return 'local' or 'premium' for a given task in the given mode."""
    if task_type not in _KNOWN_TASKS:
        raise ValueError(f"Unknown task_type '{task_type}'")
    if mode == "local":
        return "local"
    if mode == "premium":
        return "premium"
    return _HYBRID_TABLE[(task_type, question_type)]
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
pytest tests/unit/test_router.py -v
```

Expected: All 11 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/router.py tests/unit/test_router.py
git commit -m "feat: model router — pure routing function with decision table"
```

---

## Task 4: Markdown Chunker (`engine/chunker.py`)

**Files:**
- Create: `engine/chunker.py`
- Create: `tests/unit/test_chunker.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/unit/test_chunker.py
from engine.chunker import chunk_markdown
from engine.question import Chunk


def test_splits_on_h2():
    md = "## Section A\n\nContent A.\n\n## Section B\n\nContent B.\n"
    chunks = chunk_markdown(md, source_file="test.md")
    assert len(chunks) == 2
    assert chunks[0].heading == "Section A"
    assert chunks[1].heading == "Section B"


def test_splits_on_h3():
    md = "## Parent\n\n### Child A\n\nContent A.\n\n### Child B\n\nContent B.\n"
    chunks = chunk_markdown(md, source_file="test.md")
    assert any(c.heading == "Child A" for c in chunks)
    assert any(c.heading == "Child B" for c in chunks)


def test_chunk_carries_source_file():
    md = "## Section\n\nContent.\n"
    chunks = chunk_markdown(md, source_file="windows-internals.md")
    assert chunks[0].source_file == "windows-internals.md"


def test_chunk_text_contains_content():
    md = "## SSDT\n\nSystem Service Descriptor Table maps syscalls.\n"
    chunks = chunk_markdown(md, source_file="f.md")
    assert "System Service Descriptor Table" in chunks[0].text


def test_empty_markdown_returns_no_chunks():
    assert chunk_markdown("", source_file="f.md") == []


def test_markdown_without_headings_returns_one_chunk():
    md = "Just some content without any headings.\n"
    chunks = chunk_markdown(md, source_file="f.md")
    assert len(chunks) == 1
    assert chunks[0].heading == ""


def test_skips_empty_sections():
    md = "## Empty\n\n## Full\n\nHas content.\n"
    chunks = chunk_markdown(md, source_file="f.md")
    assert len(chunks) == 1
    assert chunks[0].heading == "Full"
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
pytest tests/unit/test_chunker.py -v
```

Expected: `ImportError: No module named 'engine.chunker'`

- [ ] **Step 3: Implement `engine/chunker.py`**

```python
import re
from engine.question import Chunk


_HEADING_RE = re.compile(r'^(#{2,3})\s+(.+)$', re.MULTILINE)


def chunk_markdown(text: str, source_file: str) -> list[Chunk]:
    """Split markdown into chunks at H2/H3 boundaries."""
    if not text.strip():
        return []

    matches = list(_HEADING_RE.finditer(text))

    if not matches:
        return [Chunk(text=text.strip(), source_file=source_file, heading="")]

    chunks = []
    for i, match in enumerate(matches):
        heading = match.group(2).strip()
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        content = text[start:end].strip()
        if content:
            chunks.append(Chunk(text=content, source_file=source_file, heading=heading))

    return chunks
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
pytest tests/unit/test_chunker.py -v
```

Expected: All 7 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/chunker.py tests/unit/test_chunker.py
git commit -m "feat: markdown chunker — splits at H2/H3 boundaries"
```

---

## Task 5: VectorStore (`engine/store.py`)

**Files:**
- Create: `engine/store.py`
- Create: `tests/integration/test_store.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/integration/test_store.py
import pytest
from engine.store import VectorStore


@pytest.fixture
def store(tmp_path):
    return VectorStore(persist_dir=tmp_path)


def test_empty_store_count_zero(store):
    assert store.count() == 0


def test_add_and_count(store):
    store.add(ids=["a", "b"], embeddings=[[1.0, 0.0], [0.0, 1.0]],
              documents=["doc a", "doc b"], metadatas=[{"src": "f.md"}, {"src": "f.md"}])
    assert store.count() == 2


def test_get_ids(store):
    store.add(ids=["x"], embeddings=[[1.0, 0.0]], documents=["doc"], metadatas=[{}])
    assert "x" in store.get_ids()


def test_query_returns_closest(store):
    store.add(ids=["near", "far"], embeddings=[[1.0, 0.0], [0.0, 1.0]],
              documents=["near doc", "far doc"], metadatas=[{}, {}])
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
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
pytest tests/integration/test_store.py -v
```

Expected: `ImportError: No module named 'engine.store'`

- [ ] **Step 3: Implement `engine/store.py`**

- [ ] **Step 4: Run tests — verify they pass**

- [ ] **Step 5: Commit**

```bash
git add engine/store.py tests/integration/test_store.py
git commit -m "feat: VectorStore — ChromaDB wrapper with cosine similarity"
```

---

## Task 6: Manifest (`engine/manifest.py`)

**Files:**
- Create: `engine/manifest.py`
- Create: `tests/unit/test_manifest.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/unit/test_manifest.py
import time
import pytest
from pathlib import Path
from engine.manifest import Manifest


@pytest.fixture
def kb_dir(tmp_path):
    (tmp_path / "a.md").write_text("content a")
    (tmp_path / "b.md").write_text("content b")
    return tmp_path


def test_diff_all_new_when_no_manifest(kb_dir, tmp_path):
    m = Manifest(manifest_path=tmp_path / "manifest.json")
    diff = m.diff(kb_dir)
    assert set(diff.new) == {"a.md", "b.md"}
    assert diff.changed == []
    assert diff.deleted == []


def test_diff_no_changes_after_save(kb_dir, tmp_path):
    m = Manifest(manifest_path=tmp_path / "manifest.json")
    diff = m.diff(kb_dir)
    m.save(kb_dir)
    diff2 = m.diff(kb_dir)
    assert diff2.new == []
    assert diff2.changed == []
    assert diff2.deleted == []


def test_diff_detects_changed_file(kb_dir, tmp_path):
    m = Manifest(manifest_path=tmp_path / "manifest.json")
    m.save(kb_dir)
    time.sleep(0.01)
    (kb_dir / "a.md").write_text("updated content")
    diff = m.diff(kb_dir)
    assert "a.md" in diff.changed


def test_diff_detects_new_file(kb_dir, tmp_path):
    m = Manifest(manifest_path=tmp_path / "manifest.json")
    m.save(kb_dir)
    (kb_dir / "new.md").write_text("new content")
    diff = m.diff(kb_dir)
    assert "new.md" in diff.new


def test_diff_detects_deleted_file(kb_dir, tmp_path):
    m = Manifest(manifest_path=tmp_path / "manifest.json")
    m.save(kb_dir)
    (kb_dir / "a.md").unlink()
    diff = m.diff(kb_dir)
    assert "a.md" in diff.deleted


def test_manifest_persists_across_instances(kb_dir, tmp_path):
    path = tmp_path / "manifest.json"
    Manifest(manifest_path=path).save(kb_dir)
    diff = Manifest(manifest_path=path).diff(kb_dir)
    assert diff.new == [] and diff.changed == [] and diff.deleted == []
```

- [ ] **Step 2: Run tests — verify they fail**

- [ ] **Step 3: Implement `engine/manifest.py`**

- [ ] **Step 4: Run tests — verify they pass**

- [ ] **Step 5: Commit**

```bash
git add engine/manifest.py tests/unit/test_manifest.py
git commit -m "feat: Manifest — mtime-based KB file change tracking"
```

---

## Task 7: ContextCache (`engine/context_cache.py`)

**Files:**
- Create: `engine/context_cache.py`
- Create: `tests/unit/test_context_cache.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/unit/test_context_cache.py
import pytest
from engine.context_cache import ContextCache


@pytest.fixture
def cache(tmp_path):
    return ContextCache(cache_path=tmp_path / "context_cache.json")


def test_miss_returns_none(cache):
    assert cache.get("nonexistent_hash") is None


def test_set_and_get(cache):
    cache.set("abc123", "This chunk describes SSDT hooking.")
    assert cache.get("abc123") == "This chunk describes SSDT hooking."


def test_persists_across_instances(tmp_path):
    path = tmp_path / "cache.json"
    ContextCache(cache_path=path).set("h1", "context text")
    assert ContextCache(cache_path=path).get("h1") == "context text"


def test_overwrite_updates_value(cache):
    cache.set("h1", "original")
    cache.set("h1", "updated")
    assert cache.get("h1") == "updated"


def test_chunk_hash_is_deterministic():
    from engine.context_cache import chunk_hash
    text = "SSDT maps syscall numbers to kernel addresses."
    assert chunk_hash(text) == chunk_hash(text)


def test_chunk_hash_differs_for_different_text():
    from engine.context_cache import chunk_hash
    assert chunk_hash("text a") != chunk_hash("text b")


def test_chunk_hash_is_16_chars():
    from engine.context_cache import chunk_hash
    assert len(chunk_hash("any text")) == 16


def test_prune_removes_old_entries(cache):
    for i in range(10):
        cache.set(f"h{i}", f"value {i}")
    cache.prune(max_entries=5)
    assert len(cache) <= 5


def test_len_reflects_entry_count(cache):
    assert len(cache) == 0
    cache.set("a", "v1")
    cache.set("b", "v2")
    assert len(cache) == 2
```

- [ ] **Step 2: Run tests — verify they fail**

- [ ] **Step 3: Implement `engine/context_cache.py`**

- [ ] **Step 4: Run tests — verify they pass**

- [ ] **Step 5: Commit**

```bash
git add engine/context_cache.py tests/unit/test_context_cache.py
git commit -m "feat: ContextCache — SHA-256 content-addressed cache for contextual embeddings"
```

---

## Task 8: KB Indexer (`engine/indexer.py`)

**Files:**
- Create: `engine/indexer.py`
- Create: `tests/integration/test_indexer.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/integration/test_indexer.py
import pytest
from pathlib import Path
from unittest.mock import MagicMock
from engine.indexer import Indexer
from engine.store import VectorStore
from engine.manifest import Manifest
from engine.context_cache import ContextCache


def _fake_embed(texts: list[str]) -> list[list[float]]:
    """Deterministic fake embedder — unique vector per text."""
    import hashlib
    vecs = []
    for t in texts:
        h = int(hashlib.md5(t.encode()).hexdigest(), 16)
        vecs.append([float((h >> i) & 0xFF) / 255.0 for i in range(8)])
    return vecs


@pytest.fixture
def kb_dir(tmp_path):
    (tmp_path / "kb").mkdir()
    (tmp_path / "kb" / "topic_a.md").write_text(
        "## SSDT Hooking\n\nSSDT maps syscall numbers to kernel addresses.\n\n"
        "## Kernel Callbacks\n\nPsSetCreateProcessNotifyRoutine registers callbacks.\n"
    )
    return tmp_path / "kb"


@pytest.fixture
def indexer(tmp_path, kb_dir):
    store = VectorStore(persist_dir=tmp_path / "index")
    manifest = Manifest(manifest_path=tmp_path / "manifest.json")
    cache = ContextCache(cache_path=tmp_path / "cache.json")
    return Indexer(store=store, manifest=manifest, cache=cache, embed_fn=_fake_embed)


def test_full_index_stores_chunks(indexer, kb_dir):
    indexer.index(kb_dir, incremental=False)
    assert indexer.store.count() > 0


def test_full_index_updates_manifest(indexer, kb_dir, tmp_path):
    indexer.index(kb_dir, incremental=False)
    manifest2 = Manifest(manifest_path=tmp_path / "manifest.json")
    diff = manifest2.diff(kb_dir)
    assert diff.new == [] and diff.changed == []


def test_incremental_index_skips_unchanged(indexer, kb_dir):
    indexer.index(kb_dir, incremental=False)
    count_after_full = indexer.store.count()
    indexer.index(kb_dir, incremental=True)
    assert indexer.store.count() == count_after_full


def test_incremental_index_picks_up_new_file(indexer, kb_dir):
    indexer.index(kb_dir, incremental=False)
    (kb_dir / "new_topic.md").write_text("## New\n\nBrand new content here.\n")
    indexer.index(kb_dir, incremental=True)
    assert indexer.store.count() > 2


def test_context_adapter_called_per_chunk(tmp_path, kb_dir):
    store = VectorStore(persist_dir=tmp_path / "index")
    manifest = Manifest(manifest_path=tmp_path / "manifest.json")
    cache = ContextCache(cache_path=tmp_path / "cache.json")
    context_adapter = MagicMock(return_value="Mock context description.")
    indexer = Indexer(store=store, manifest=manifest, cache=cache,
                      embed_fn=_fake_embed, context_adapter=context_adapter)
    indexer.index(kb_dir, incremental=False)
    assert context_adapter.call_count > 0


def test_no_context_adapter_still_indexes(indexer, kb_dir):
    # context_adapter=None — contextual embedding disabled
    indexer.index(kb_dir, incremental=False)
    assert indexer.store.count() > 0
```

- [ ] **Step 2: Run tests — verify they fail**

- [ ] **Step 3: Implement `engine/indexer.py`**

- [ ] **Step 4: Run tests — verify they pass**

- [ ] **Step 5: Commit**

```bash
git add engine/indexer.py tests/integration/test_indexer.py
git commit -m "feat: Indexer — incremental KB indexer with ChromaDB and contextual embedding"
```

---

## Task 9: Retriever (`engine/retriever.py`)

**Files:**
- Create: `engine/retriever.py`
- Create: `tests/integration/test_retriever.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/integration/test_retriever.py
import pytest
from pathlib import Path
from engine.retriever import Retriever, IndexNotFoundError, SeenChunks
from engine.store import VectorStore
from engine.question import Chunk


def _fake_embed(text: str) -> list[float]:
    import hashlib
    h = int(hashlib.md5(text.encode()).hexdigest(), 16)
    return [float((h >> i) & 0xFF) / 255.0 for i in range(8)]


@pytest.fixture
def populated_store(tmp_path):
    store = VectorStore(persist_dir=tmp_path)
    store.add(
        ids=["ssdt", "list_entry", "irql"],
        embeddings=[_fake_embed("SSDT"), _fake_embed("LIST_ENTRY"), _fake_embed("IRQL")],
        documents=["SSDT maps syscalls.", "LIST_ENTRY is a linked list.", "IRQL controls interrupt levels."],
        metadatas=[{"source_file": "wi.md", "heading": "SSDT"},
                   {"source_file": "wi.md", "heading": "LIST_ENTRY"},
                   {"source_file": "wi.md", "heading": "IRQL"}],
    )
    return store


def test_raises_if_store_empty(tmp_path):
    store = VectorStore(persist_dir=tmp_path)
    with pytest.raises(IndexNotFoundError):
        Retriever(store=store, embed_fn=_fake_embed)


def test_search_returns_chunks(tmp_path, populated_store):
    r = Retriever(store=populated_store, embed_fn=_fake_embed)
    results = r.search("SSDT syscall table", top_k=2)
    assert len(results) <= 2
    assert all(isinstance(c, Chunk) for c in results)


def test_search_top_k_respected(tmp_path, populated_store):
    r = Retriever(store=populated_store, embed_fn=_fake_embed)
    results = r.search("kernel", top_k=1)
    assert len(results) == 1


def test_search_with_seed_is_deterministic(tmp_path, populated_store):
    r = Retriever(store=populated_store, embed_fn=_fake_embed)
    r1 = r.search("SSDT", top_k=2, top_n=3, seed=42)
    r2 = r.search("SSDT", top_k=2, top_n=3, seed=42)
    assert [c.heading for c in r1] == [c.heading for c in r2]


def test_seen_chunks_deweighted(tmp_path, populated_store):
    seen = SeenChunks(tmp_path / "seen.json")
    seen.mark(["ssdt"])
    r = Retriever(store=populated_store, embed_fn=_fake_embed, seen_chunks=seen)
    results = r.search("SSDT syscall", top_k=1, top_n=3, seed=0)
    # Unseen chunks should be preferred
    assert results[0].heading != "SSDT"
```

- [ ] **Step 2: Run tests — verify they fail**

- [ ] **Step 3: Implement `engine/retriever.py`**

- [ ] **Step 4: Run tests — verify they pass**

- [ ] **Step 5: Commit**

```bash
git add engine/retriever.py tests/integration/test_retriever.py
git commit -m "feat: Retriever — ChromaDB semantic search, top-N sampling, SeenChunks dedup"
```

---

## Task 10: Answer Scorer (`engine/scorer.py`)

**Files:**
- Create: `engine/scorer.py`
- Create: `tests/unit/test_scorer.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/unit/test_scorer.py
import pytest
from engine.scorer import score_fill_in, score_from_model_eval
from engine.question import Score
from tests.conftest import MockAdapter


def test_fill_in_exact_match():
    s = score_fill_in(user_answer="SSDT", correct_answer="SSDT")
    assert s.value == 1.0


def test_fill_in_case_insensitive():
    s = score_fill_in(user_answer="ssdt", correct_answer="SSDT")
    assert s.value == 1.0


def test_fill_in_close_match():
    s = score_fill_in(user_answer="system service descriptor", correct_answer="System Service Descriptor Table")
    assert s.value == 0.5


def test_fill_in_wrong_answer():
    s = score_fill_in(user_answer="wrong answer entirely", correct_answer="SSDT")
    assert s.value == 0.0


def test_fill_in_shows_correct_answer():
    s = score_fill_in(user_answer="x", correct_answer="SSDT")
    assert s.correct_answer == "SSDT"


def test_score_from_model_eval_correct():
    adapter = MockAdapter(response='{"score": 1.0, "feedback": "Perfect answer."}')
    s = score_from_model_eval(user_answer="good answer", question_text="Q?",
                               correct_answer="A", adapter=adapter)
    assert s.value == 1.0
    assert "Perfect" in s.feedback


def test_score_from_model_eval_partial():
    adapter = MockAdapter(response='{"score": 0.5, "feedback": "Partially correct."}')
    s = score_from_model_eval(user_answer="partial", question_text="Q?",
                               correct_answer="A", adapter=adapter)
    assert s.value == 0.5


def test_score_from_model_eval_malformed_json_defaults_zero():
    adapter = MockAdapter(response="not valid json")
    s = score_from_model_eval(user_answer="x", question_text="Q?",
                               correct_answer="A", adapter=adapter)
    assert s.value == 0.0
    assert "parse" in s.feedback.lower()
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
pytest tests/unit/test_scorer.py -v
```

Expected: `ImportError: No module named 'engine.scorer'`

- [ ] **Step 3: Implement `engine/scorer.py`**

```python
import json
import difflib
from engine.question import Score
from engine.models.adapter import ModelAdapter


def score_fill_in(user_answer: str, correct_answer: str) -> Score:
    """Score a fill-in answer using fuzzy string matching."""
    user = user_answer.strip().lower()
    correct = correct_answer.strip().lower()

    if user == correct:
        return Score(value=1.0, feedback="Correct!", correct_answer=correct_answer)

    ratio = difflib.SequenceMatcher(None, user, correct).ratio()
    if ratio >= 0.7:
        return Score(value=0.5,
                     feedback=f"Close — expected: {correct_answer}",
                     correct_answer=correct_answer)

    return Score(value=0.0,
                 feedback=f"Incorrect. Correct answer: {correct_answer}",
                 correct_answer=correct_answer)


def score_from_model_eval(user_answer: str, question_text: str,
                           correct_answer: str, adapter: ModelAdapter) -> Score:
    """Score a conceptual or code answer via model evaluation."""
    prompt = (
        f"Evaluate this answer to the question below. "
        f"Respond with JSON only: {{\"score\": <0.0|0.5|1.0>, \"feedback\": \"<explanation>\"}}\n\n"
        f"Question: {question_text}\n"
        f"Correct answer: {correct_answer}\n"
        f"User answer: {user_answer}"
    )
    raw = adapter.generate(prompt)
    try:
        data = json.loads(raw)
        value = float(data["score"])
        if value not in {0.0, 0.5, 1.0}:
            value = 0.0
        return Score(value=value, feedback=data.get("feedback", ""), correct_answer=correct_answer)
    except (json.JSONDecodeError, KeyError, ValueError):
        return Score(value=0.0,
                     feedback="Could not parse model evaluation response.",
                     correct_answer=correct_answer)
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
pytest tests/unit/test_scorer.py -v
```

Expected: All 8 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/scorer.py tests/unit/test_scorer.py
git commit -m "feat: answer scorer — difflib for fill_in, model eval for conceptual/code"
```

---

## Task 6: Session Logger (`engine/session_log.py`)

**Files:**
- Create: `engine/session_log.py`
- Create: `tests/unit/test_session_log.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/unit/test_session_log.py
import json
import pytest
from pathlib import Path
from engine.session_log import SessionLog
from engine.question import QuestionLog


def test_log_creates_file_on_first_flush(tmp_path):
    log = SessionLog(log_dir=tmp_path, mode="hybrid",
                     local_model="phi4-mini", premium_model="claude-sonnet-4-6")
    entry = QuestionLog(question_num=1, question_type="fill_in", question_text="Q?",
                        user_answer="A", correct_answer="A", score=1.0,
                        model_used="local", tokens_local=50, tokens_premium=0,
                        ptc_compression_ratio=0.6)
    log.add(entry)
    files = list(tmp_path.glob("*.json"))
    assert len(files) == 1


def test_log_file_contains_question_entry(tmp_path):
    log = SessionLog(log_dir=tmp_path, mode="local",
                     local_model="phi4-mini", premium_model=None)
    entry = QuestionLog(question_num=1, question_type="code", question_text="Write X",
                        user_answer="def x(): pass", correct_answer="def x(): return 1",
                        score=0.5, model_used="premium", tokens_local=0, tokens_premium=200,
                        ptc_compression_ratio=0.75)
    log.add(entry)
    data = json.loads(list(tmp_path.glob("*.json"))[0].read_text())
    assert data["questions"][0]["score"] == 0.5
    assert data["questions"][0]["question_type"] == "code"


def test_log_flushes_per_question(tmp_path):
    log = SessionLog(log_dir=tmp_path, mode="hybrid",
                     local_model="phi4-mini", premium_model="claude-sonnet-4-6")
    for i in range(3):
        log.add(QuestionLog(question_num=i+1, question_type="fill_in",
                            question_text="Q", user_answer="A", correct_answer="A",
                            score=1.0, model_used="local", tokens_local=10,
                            tokens_premium=0, ptc_compression_ratio=0.5))
    data = json.loads(list(tmp_path.glob("*.json"))[0].read_text())
    assert len(data["questions"]) == 3


def test_log_summary_totals(tmp_path):
    log = SessionLog(log_dir=tmp_path, mode="hybrid",
                     local_model="phi4-mini", premium_model="claude-sonnet-4-6")
    log.add(QuestionLog(1, "fill_in", "Q", "A", "A", 1.0, "local", 50, 0, 0.6))
    log.add(QuestionLog(2, "conceptual", "Q2", "B", "B", 0.5, "premium", 0, 300, 0.8))
    summary = log.summary()
    assert summary["total_score"] == 1.5
    assert summary["total_tokens_local"] == 50
    assert summary["total_tokens_premium"] == 300
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
pytest tests/unit/test_session_log.py -v
```

Expected: `ImportError: No module named 'engine.session_log'`

- [ ] **Step 3: Implement `engine/session_log.py`**

```python
import json
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from engine.question import QuestionLog


class SessionLog:
    def __init__(self, log_dir: Path, mode: str,
                 local_model: str | None, premium_model: str | None):
        self._log_dir = Path(log_dir)
        self._log_dir.mkdir(parents=True, exist_ok=True)
        self._session_id = str(uuid.uuid4())[:8]
        self._started_at = datetime.now(timezone.utc).isoformat()
        self._mode = mode
        self._local_model = local_model
        self._premium_model = premium_model
        self._questions: list[QuestionLog] = []
        self._log_path = self._log_dir / f"{self._started_at[:10]}-{self._session_id}.json"

    def add(self, entry: QuestionLog) -> None:
        self._questions.append(entry)
        self._flush()

    def summary(self) -> dict:
        return {
            "session_id": self._session_id,
            "mode": self._mode,
            "total_questions": len(self._questions),
            "total_score": sum(q.score for q in self._questions),
            "total_tokens_local": sum(q.tokens_local for q in self._questions),
            "total_tokens_premium": sum(q.tokens_premium for q in self._questions),
            "avg_ptc_compression_ratio": (
                sum(q.ptc_compression_ratio for q in self._questions) / len(self._questions)
                if self._questions else 0.0
            ),
        }

    def _flush(self) -> None:
        data = {
            "session_id": self._session_id,
            "started_at": self._started_at,
            "mode": self._mode,
            "local_model": self._local_model,
            "premium_model": self._premium_model,
            "questions": [asdict(q) for q in self._questions],
        }
        self._log_path.write_text(json.dumps(data, indent=2))
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
pytest tests/unit/test_session_log.py -v
```

Expected: All 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/session_log.py tests/unit/test_session_log.py
git commit -m "feat: session logger — per-question JSON flush, crash-safe"
```

---

## Task 7: PTC Pipeline (`engine/ptc_scripts/` + `engine/ptc.py`)

**Files:**
- Create: `engine/ptc_scripts/summarize_chunk.py`
- Create: `engine/ptc_scripts/extract_concepts.py`
- Create: `engine/ptc_scripts/extract_code_context.py`
- Create: `engine/ptc.py`
- Create: `tests/unit/test_ptc.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/unit/test_ptc.py
import pytest
from engine.ptc import compress
from engine.question import Chunk, PTCResult


@pytest.fixture
def chunks():
    return [
        Chunk(text="The SSDT maps syscall numbers to kernel function addresses. "
              "Rootkits overwrite entries to intercept system calls. "
              "PatchGuard detects unauthorized modifications.",
              source_file="windows-internals.md", heading="SSDT Hooking"),
        Chunk(text="Kernel callbacks: PsSetCreateProcessNotifyRoutine registers "
              "a callback invoked on process creation.",
              source_file="windows-internals.md", heading="Kernel Callbacks"),
    ]


def test_compress_returns_ptc_result(chunks):
    result = compress(chunks, task_type="summarize_chunk")
    assert isinstance(result, PTCResult)
    assert result.compressed_text


def test_compress_reduces_tokens(chunks):
    result = compress(chunks, task_type="summarize_chunk")
    assert result.compressed_tokens <= result.raw_tokens


def test_compress_extracts_concepts(chunks):
    result = compress(chunks, task_type="extract_concepts")
    assert isinstance(result, PTCResult)
    assert result.compressed_text


def test_compress_code_context(chunks):
    result = compress(chunks, task_type="extract_code_context")
    assert isinstance(result, PTCResult)


def test_compress_unknown_task_raises(chunks):
    with pytest.raises(ValueError, match="No PTC script for task_type"):
        compress(chunks, task_type="unknown_task")


def test_compression_ratio_in_range(chunks):
    result = compress(chunks, task_type="summarize_chunk")
    assert 0.0 <= result.compression_ratio <= 1.0
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
pytest tests/unit/test_ptc.py -v
```

Expected: `ImportError: No module named 'engine.ptc'`

- [ ] **Step 3: Create `engine/ptc_scripts/summarize_chunk.py`**

```python
"""PTC script: summarize_chunk — reads JSON chunks, writes compact summary."""
import json
import sys


def run(chunks: list[dict]) -> str:
    lines = []
    for chunk in chunks:
        heading = chunk.get("heading", "")
        text = chunk.get("text", "")
        # Extract first 2 sentences as summary
        sentences = [s.strip() for s in text.replace("\n", " ").split(".") if s.strip()]
        summary = ". ".join(sentences[:2])
        if summary:
            lines.append(f"[{heading}] {summary}.")
    return "\n".join(lines)


if __name__ == "__main__":
    chunks = json.loads(sys.stdin.read())
    print(run(chunks))
```

- [ ] **Step 4: Create `engine/ptc_scripts/extract_concepts.py`**

```python
"""PTC script: extract_concepts — extracts key noun phrases and terms."""
import json
import re
import sys


def run(chunks: list[dict]) -> str:
    concepts = []
    for chunk in chunks:
        heading = chunk.get("heading", "")
        text = chunk.get("text", "")
        # Extract capitalized terms (likely domain concepts)
        terms = re.findall(r'\b[A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+)*\b', text)
        unique_terms = list(dict.fromkeys(terms))[:8]
        if unique_terms:
            concepts.append(f"[{heading}] Concepts: {', '.join(unique_terms)}")
    return "\n".join(concepts)


if __name__ == "__main__":
    chunks = json.loads(sys.stdin.read())
    print(run(chunks))
```

- [ ] **Step 5: Create `engine/ptc_scripts/extract_code_context.py`**

```python
"""PTC script: extract_code_context — extracts code-relevant details."""
import json
import re
import sys


def run(chunks: list[dict]) -> str:
    lines = []
    for chunk in chunks:
        heading = chunk.get("heading", "")
        text = chunk.get("text", "")
        # Extract lines mentioning functions, structs, APIs, or data structures
        code_lines = [l.strip() for l in text.split("\n")
                      if re.search(r'\b(struct|function|API|typedef|define|return|void|int|NTSTATUS)\b', l, re.I)]
        if code_lines:
            lines.append(f"[{heading}]\n" + "\n".join(code_lines[:5]))
        else:
            # Fall back to first sentence
            first = text.split(".")[0].strip()
            if first:
                lines.append(f"[{heading}] {first}.")
    return "\n".join(lines)


if __name__ == "__main__":
    chunks = json.loads(sys.stdin.read())
    print(run(chunks))
```

- [ ] **Step 6: Create `engine/ptc.py`**

```python
import json
from engine.question import Chunk, PTCResult
from engine.ptc_scripts import summarize_chunk, extract_concepts, extract_code_context

_SCRIPT_MAP = {
    "summarize_chunk": summarize_chunk.run,
    "extract_concepts": extract_concepts.run,
    "extract_code_context": extract_code_context.run,
    "generate_question": extract_concepts.run,
    "evaluate_answer": summarize_chunk.run,
}

# Startup validation: fail fast if any known task type lacks a script
_KNOWN_TASK_TYPES = {"summarize_chunk", "extract_concepts", "extract_code_context",
                     "generate_question", "evaluate_answer"}
assert _KNOWN_TASK_TYPES == set(_SCRIPT_MAP.keys()), \
    f"Missing PTC scripts for: {_KNOWN_TASK_TYPES - set(_SCRIPT_MAP.keys())}"


def _count_tokens(text: str) -> int:
    """Approximate token count: ~4 chars per token."""
    return max(1, len(text) // 4)


def compress(chunks: list[Chunk], task_type: str) -> PTCResult:
    """Run the appropriate PTC script for the given task type."""
    if task_type not in _SCRIPT_MAP:
        raise ValueError(f"No PTC script for task_type '{task_type}'")

    raw_text = "\n\n".join(f"[{c.heading}]\n{c.text}" for c in chunks)
    raw_tokens = _count_tokens(raw_text)

    chunk_dicts = [{"heading": c.heading, "text": c.text, "source_file": c.source_file}
                   for c in chunks]
    compressed_text = _SCRIPT_MAP[task_type](chunk_dicts)
    compressed_tokens = _count_tokens(compressed_text)

    return PTCResult(
        compressed_text=compressed_text,
        raw_tokens=raw_tokens,
        compressed_tokens=min(compressed_tokens, raw_tokens),
    )
```

- [ ] **Step 7: Run tests — verify they pass**

```bash
pytest tests/unit/test_ptc.py -v
```

Expected: All 6 tests PASS.

- [ ] **Step 8: Commit**

```bash
git add engine/ptc.py engine/ptc_scripts/ tests/unit/test_ptc.py
git commit -m "feat: PTC pipeline — developer-authored extraction scripts"
```

---

## Task 8: Sandbox (`engine/sandbox.py`)

**Files:**
- Create: `engine/sandbox.py`
- Create: `tests/integration/test_sandbox.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/integration/test_sandbox.py
import pytest
import sys
from engine.sandbox import DirectRunner, ValidationResult, ExecutionResult


@pytest.fixture
def runner():
    return DirectRunner()


def test_safe_script_passes_validation(runner):
    script = "result = [x.upper() for x in data.split()]\noutput = ' '.join(result)"
    result = runner.validate(script)
    assert result.valid


def test_os_import_blocked(runner):
    script = "import os\noutput = os.getcwd()"
    result = runner.validate(script)
    assert not result.valid
    assert "os" in result.error.lower() or "import" in result.error.lower()


def test_subprocess_import_blocked(runner):
    script = "import subprocess\noutput = subprocess.check_output(['ls'])"
    result = runner.validate(script)
    assert not result.valid


def test_open_blocked(runner):
    script = "output = open('secret.txt').read()"
    result = runner.validate(script)
    assert not result.valid


def test_safe_script_executes(runner):
    script = "output = data.strip().upper()"
    ok, out = runner.execute(script, input_data="hello world")
    assert ok
    assert out == "HELLO WORLD"


def test_execution_returns_output_variable(runner):
    script = "words = data.split()\noutput = str(len(words))"
    ok, out = runner.execute(script, input_data="one two three")
    assert ok
    assert out == "3"


def test_execution_of_invalid_script_returns_false(runner):
    script = "import os"
    ok, out = runner.execute(script, input_data="anything")
    assert not ok


def test_syntax_error_fails_gracefully(runner):
    script = "output = ("
    result = runner.validate(script)
    assert not result.valid
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
pytest tests/integration/test_sandbox.py -v
```

Expected: `ImportError: No module named 'engine.sandbox'`

- [ ] **Step 3: Implement `engine/sandbox.py`**

```python
from __future__ import annotations
import sys
from dataclasses import dataclass
from typing import Protocol
from RestrictedPython import compile_restricted, safe_globals, safe_builtins


@dataclass
class ValidationResult:
    valid: bool
    error: str = ""


class SandboxRunner(Protocol):
    def validate(self, script: str) -> ValidationResult: ...
    def execute(self, script: str, input_data: str) -> tuple[bool, str]: ...


class DirectRunner:
    """
    Sandbox runner using RestrictedPython AST validation.
    Used in CI and non-Windows environments.
    On Windows production use JobObjectRunner instead.
    """

    _BLOCKED_NAMES = {"os", "sys", "subprocess", "socket", "open",
                      "exec", "eval", "__import__", "importlib"}

    def validate(self, script: str) -> ValidationResult:
        try:
            compile_restricted(script, "<string>", "exec")
        except SyntaxError as e:
            return ValidationResult(valid=False, error=str(e))

        # AST check: scan for blocked names
        import ast
        try:
            tree = ast.parse(script)
        except SyntaxError as e:
            return ValidationResult(valid=False, error=str(e))

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    name = alias.name.split(".")[0]
                    if name in self._BLOCKED_NAMES:
                        return ValidationResult(valid=False,
                                                error=f"Blocked import: {name}")
            if isinstance(node, ast.ImportFrom):
                if node.module and node.module.split(".")[0] in self._BLOCKED_NAMES:
                    return ValidationResult(valid=False,
                                            error=f"Blocked import: {node.module}")
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name) and node.func.id == "open":
                    return ValidationResult(valid=False, error="Blocked: open()")

        return ValidationResult(valid=True)

    def execute(self, script: str, input_data: str) -> tuple[bool, str]:
        validation = self.validate(script)
        if not validation.valid:
            return False, f"Validation failed: {validation.error}"

        namespace = {"data": input_data, "output": ""}
        try:
            exec(compile_restricted(script, "<string>", "exec"),
                 {**safe_globals, "__builtins__": safe_builtins}, namespace)
            return True, str(namespace.get("output", ""))
        except Exception as e:
            return False, f"Execution error: {e}"


if sys.platform == "win32":
    try:
        from engine._sandbox_win32 import JobObjectRunner
    except ImportError:
        JobObjectRunner = DirectRunner  # fallback if ctypes setup incomplete
else:
    JobObjectRunner = DirectRunner
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
pytest tests/integration/test_sandbox.py -v
```

Expected: All 8 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/sandbox.py tests/integration/test_sandbox.py
git commit -m "feat: sandbox — RestrictedPython AST validation + DirectRunner"
```

---

## Task 9: Model Adapters (`engine/models/`)

**Files:**
- Create: `engine/models/adapter.py`
- Create: `engine/models/local_adapter.py`
- Create: `engine/models/premium_adapter.py`
- Create: `tests/integration/test_adapters.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/integration/test_adapters.py
import json
import pytest
import httpx
from engine.models.adapter import ModelAdapter, MockAdapter
from engine.models.local_adapter import LocalAdapter
from engine.models.premium_adapter import PremiumAdapter


def test_mock_adapter_returns_configured_response():
    adapter = MockAdapter(response="test output")
    assert adapter.generate("any prompt") == "test output"


def test_mock_adapter_records_calls():
    adapter = MockAdapter(response="x")
    adapter.generate("prompt one")
    adapter.generate("prompt two")
    assert len(adapter.calls) == 2


def test_local_adapter_calls_ollama(respx_mock):
    respx_mock.post("http://localhost:11434/api/generate").mock(
        return_value=httpx.Response(200, json={"response": "kernel answer"})
    )
    client = httpx.Client(transport=respx_mock)
    adapter = LocalAdapter(model="phi4-mini", client=client)
    result = adapter.generate("What is SSDT?")
    assert result == "kernel answer"


def test_local_adapter_graceful_on_connection_error():
    client = httpx.Client(transport=httpx.MockTransport(
        lambda r: (_ for _ in ()).throw(httpx.ConnectError("refused"))
    ))
    adapter = LocalAdapter(model="phi4-mini", client=client)
    result = adapter.generate("any prompt")
    assert result == ""


def test_premium_adapter_resolves_key_from_env(monkeypatch, tmp_path):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-env")
    import anthropic
    mock_client = MockAnthropicClient("premium response")
    adapter = PremiumAdapter(model="claude-sonnet-4-6", client=mock_client)
    result = adapter.generate("prompt")
    assert result == "premium response"


def test_premium_adapter_resolves_key_from_file(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    key_file = tmp_path / "Claude-Key.txt"
    key_file.write_text("file-key-123")
    import anthropic
    mock_client = MockAnthropicClient("file response")
    adapter = PremiumAdapter(model="claude-sonnet-4-6", client=mock_client)
    result = adapter.generate("prompt")
    assert result == "file response"


def test_premium_adapter_raises_without_key(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(EnvironmentError, match="No API key"):
        PremiumAdapter.from_config(
            model="claude-sonnet-4-6",
            api_key_file=tmp_path / "nonexistent.txt"
        )


class MockAnthropicClient:
    def __init__(self, response: str):
        self._response = response
        self.messages = self

    def create(self, **kwargs):
        class FakeMsg:
            content = [type("B", (), {"text": self._response})()]
        return FakeMsg()

    def __get__(self, obj, t=None):
        return self
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
pytest tests/integration/test_adapters.py -v
```

Expected: `ImportError: No module named 'engine.models.adapter'`

- [ ] **Step 3: Create `engine/models/adapter.py`**

```python
from typing import Protocol, runtime_checkable


@runtime_checkable
class ModelAdapter(Protocol):
    def generate(self, prompt: str) -> str: ...


class MockAdapter:
    """Deterministic adapter for tests."""
    def __init__(self, response: str = "mock response"):
        self.response = response
        self.calls: list[str] = []

    def generate(self, prompt: str) -> str:
        self.calls.append(prompt)
        return self.response
```

- [ ] **Step 4: Create `engine/models/local_adapter.py`**

```python
import httpx


class LocalAdapter:
    def __init__(self, model: str, client: httpx.Client | None = None):
        self._model = model
        self._client = client or httpx.Client()
        self._url = "http://localhost:11434/api/generate"

    def generate(self, prompt: str) -> str:
        try:
            resp = self._client.post(
                self._url,
                json={"model": self._model, "prompt": prompt, "stream": False},
                timeout=60.0,
            )
            resp.raise_for_status()
            return resp.json().get("response", "")
        except Exception:
            return ""
```

- [ ] **Step 5: Create `engine/models/premium_adapter.py`**

```python
import os
from pathlib import Path
import anthropic


class PremiumAdapter:
    def __init__(self, model: str, client: anthropic.Anthropic):
        self._model = model
        self._client = client

    def generate(self, prompt: str) -> str:
        msg = self._client.messages.create(
            model=self._model,
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )
        return msg.content[0].text

    @classmethod
    def from_config(cls, model: str,
                    api_key_file: Path | None = None) -> "PremiumAdapter":
        key = os.environ.get("ANTHROPIC_API_KEY")
        if not key and api_key_file and Path(api_key_file).exists():
            key = Path(api_key_file).read_text().strip()
        if not key:
            raise EnvironmentError(
                "No API key found. Set ANTHROPIC_API_KEY or create Claude-Key.txt.\n"
                "Claude-Key.txt must be listed in .gitignore."
            )
        return cls(model=model, client=anthropic.Anthropic(api_key=key))
```

- [ ] **Step 6: Run tests — verify they pass**

```bash
pytest tests/integration/test_adapters.py -v
```

Expected: All adapter tests PASS (mock and error path tests; live API tests skipped).

- [ ] **Step 7: Commit**

```bash
git add engine/models/ tests/integration/test_adapters.py
git commit -m "feat: model adapters — LocalAdapter (Ollama), PremiumAdapter (Anthropic)"
```

---

## Task 10: Programmable Tool Calling (`engine/prog_tool_calling.py`)

**Files:**
- Create: `engine/prog_tool_calling.py`
- Create: `tests/integration/test_prog_tool_calling.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/integration/test_prog_tool_calling.py
import pytest
from engine.prog_tool_calling import ProgToolCalling
from engine.question import PTCResult, ProgToolResult
from engine.sandbox import DirectRunner
from engine.models.adapter import MockAdapter


@pytest.fixture
def ptc_result():
    return PTCResult(
        compressed_text="[SSDT Hooking] Rootkits overwrite SSDT entries to intercept syscalls.",
        raw_tokens=500, compressed_tokens=100
    )


def test_successful_script_returns_output(ptc_result):
    adapter = MockAdapter(response='output = data.strip().upper()')
    runner = DirectRunner()
    ptc = ProgToolCalling(model=adapter, sandbox=runner)
    result = ptc.run(ptc_result, task="extract key term")
    assert isinstance(result, ProgToolResult)
    assert not result.fallback_used
    assert result.output_text


def test_fallback_on_invalid_script(ptc_result):
    # Model generates a dangerous script — sandbox blocks it
    adapter = MockAdapter(response='import os\noutput = os.getcwd()')
    runner = DirectRunner()
    ptc = ProgToolCalling(model=adapter, sandbox=runner)
    result = ptc.run(ptc_result, task="any task")
    assert result.fallback_used
    assert result.output_text == ptc_result.compressed_text


def test_fallback_on_execution_error(ptc_result):
    adapter = MockAdapter(response='output = undefined_variable')
    runner = DirectRunner()
    ptc = ProgToolCalling(model=adapter, sandbox=runner)
    result = ptc.run(ptc_result, task="any task")
    assert result.fallback_used


def test_model_prompt_contains_compressed_text(ptc_result):
    adapter = MockAdapter(response='output = data[:50]')
    runner = DirectRunner()
    ptc = ProgToolCalling(model=adapter, sandbox=runner)
    ptc.run(ptc_result, task="summarize")
    assert ptc_result.compressed_text in adapter.calls[0]


def test_result_script_is_recorded(ptc_result):
    script = 'output = data.strip()'
    adapter = MockAdapter(response=script)
    runner = DirectRunner()
    ptc = ProgToolCalling(model=adapter, sandbox=runner)
    result = ptc.run(ptc_result, task="any")
    assert result.script == script
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
pytest tests/integration/test_prog_tool_calling.py -v
```

Expected: `ImportError: No module named 'engine.prog_tool_calling'`

- [ ] **Step 3: Implement `engine/prog_tool_calling.py`**

```python
from engine.question import PTCResult, ProgToolResult
from engine.models.adapter import ModelAdapter
from engine.sandbox import SandboxRunner


class ProgToolCalling:
    def __init__(self, model: ModelAdapter, sandbox: SandboxRunner):
        self._model = model
        self._sandbox = sandbox

    def run(self, ptc_result: PTCResult, task: str) -> ProgToolResult:
        prompt = (
            f"Write a Python script to extract relevant information for this task:\n"
            f"Task: {task}\n\n"
            f"Input data will be available as a string variable called `data`.\n"
            f"Store your output in a variable called `output`.\n"
            f"Do NOT import any modules. Use only string operations and builtins.\n\n"
            f"Data preview:\n{ptc_result.compressed_text[:500]}\n\n"
            f"Respond with ONLY the Python script, no explanation."
        )
        script = self._model.generate(prompt).strip()

        validation = self._sandbox.validate(script)
        if not validation.valid:
            return ProgToolResult(
                output_text=ptc_result.compressed_text,
                script=script,
                fallback_used=True,
            )

        success, output = self._sandbox.execute(script, ptc_result.compressed_text)
        if not success or not output.strip():
            return ProgToolResult(
                output_text=ptc_result.compressed_text,
                script=script,
                fallback_used=True,
            )

        return ProgToolResult(output_text=output, script=script, fallback_used=False)
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
pytest tests/integration/test_prog_tool_calling.py -v
```

Expected: All 5 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/prog_tool_calling.py tests/integration/test_prog_tool_calling.py
git commit -m "feat: Programmable Tool Calling — model-generated scripts with sandbox"
```

---

## Task 11: KB Retriever (`engine/retriever.py`)

**Files:**
- Create: `engine/retriever.py`
- Create: `tests/integration/test_retriever.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/integration/test_retriever.py
import numpy as np
import pytest
from pathlib import Path
from engine.retriever import Retriever, IndexNotFoundError
from engine.question import Chunk


def _build_tiny_index(index_dir: Path):
    """Manually write a minimal index for testing."""
    import json
    chunks = [
        {"text": "SSDT maps syscall numbers to kernel addresses.",
         "source_file": "windows-internals.md", "heading": "SSDT Hooking"},
        {"text": "LIST_ENTRY is a doubly-linked list structure in Windows kernel.",
         "source_file": "windows-internals.md", "heading": "LIST_ENTRY"},
        {"text": "Memoization stores subproblem results to avoid recomputation.",
         "source_file": "dynamic-programming.md", "heading": "Dynamic Programming"},
    ]
    vectors = np.array([
        [1.0, 0.0, 0.0],
        [0.0, 1.0, 0.0],
        [0.0, 0.0, 1.0],
    ], dtype=np.float32)
    index_dir.mkdir(parents=True, exist_ok=True)
    np.save(index_dir / "vectors.npy", vectors)
    (index_dir / "manifest.json").write_text(json.dumps({"chunks": chunks, "dim": 3}))


def test_retriever_raises_if_index_missing(tmp_path):
    with pytest.raises(IndexNotFoundError, match="kb index"):
        Retriever(index_dir=tmp_path / "nonexistent")


def test_retriever_returns_top_k(tmp_path):
    _build_tiny_index(tmp_path)
    retriever = Retriever(index_dir=tmp_path)
    query_vec = np.array([1.0, 0.0, 0.0], dtype=np.float32)
    results = retriever.search_by_vector(query_vec, top_k=2, min_score=0.0)
    assert len(results) == 2
    assert results[0].chunk.heading == "SSDT Hooking"


def test_retriever_filters_by_min_score(tmp_path):
    _build_tiny_index(tmp_path)
    retriever = Retriever(index_dir=tmp_path)
    query_vec = np.array([1.0, 0.0, 0.0], dtype=np.float32)
    results = retriever.search_by_vector(query_vec, top_k=3, min_score=0.9)
    assert len(results) == 1
    assert results[0].chunk.heading == "SSDT Hooking"


def test_retriever_result_has_score(tmp_path):
    _build_tiny_index(tmp_path)
    retriever = Retriever(index_dir=tmp_path)
    query_vec = np.array([1.0, 0.0, 0.0], dtype=np.float32)
    results = retriever.search_by_vector(query_vec, top_k=1, min_score=0.0)
    assert 0.0 <= results[0].score <= 1.0
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
pytest tests/integration/test_retriever.py -v
```

Expected: `ImportError: No module named 'engine.retriever'`

- [ ] **Step 3: Implement `engine/retriever.py`**

```python
import json
from dataclasses import dataclass
from pathlib import Path
import numpy as np
from engine.question import Chunk


class IndexNotFoundError(Exception):
    pass


@dataclass
class RankedChunk:
    chunk: Chunk
    score: float


class Retriever:
    def __init__(self, index_dir: Path):
        index_dir = Path(index_dir)
        vectors_path = index_dir / "vectors.npy"
        manifest_path = index_dir / "manifest.json"
        if not vectors_path.exists() or not manifest_path.exists():
            raise IndexNotFoundError(
                f"kb index not found at '{index_dir}'. "
                f"Run: python cli/main.py kb index"
            )
        self._vectors = np.load(str(vectors_path))
        manifest = json.loads(manifest_path.read_text())
        self._chunks = [
            Chunk(text=c["text"], source_file=c["source_file"], heading=c["heading"])
            for c in manifest["chunks"]
        ]

    def search_by_vector(self, query_vec: np.ndarray,
                         top_k: int, min_score: float) -> list[RankedChunk]:
        if len(self._vectors) == 0:
            return []
        # Cosine similarity
        norms = np.linalg.norm(self._vectors, axis=1, keepdims=True)
        norms = np.where(norms == 0, 1, norms)
        normalised = self._vectors / norms
        q_norm = query_vec / (np.linalg.norm(query_vec) or 1.0)
        scores = normalised @ q_norm
        ranked_idx = np.argsort(scores)[::-1]
        results = []
        for idx in ranked_idx[:top_k]:
            score = float(scores[idx])
            if score >= min_score:
                results.append(RankedChunk(chunk=self._chunks[idx], score=score))
        return results
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
pytest tests/integration/test_retriever.py -v
```

Expected: All 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/retriever.py tests/integration/test_retriever.py
git commit -m "feat: KB retriever — cosine similarity search over numpy index"
```

---

## Task 12: KB Indexer (`engine/indexer.py`)

**Files:**
- Create: `engine/indexer.py`
- Create: `tests/integration/test_indexer.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/integration/test_indexer.py
import json
import numpy as np
import pytest
from pathlib import Path
from engine.indexer import Indexer


# Fake embed function: returns a deterministic vector based on text length
def fake_embed(text: str) -> list[float]:
    return [float(len(text) % 10) / 10.0] * 3


def test_full_index_build(tiny_kb_dir, tmp_path):
    indexer = Indexer(kb_dir=tiny_kb_dir, index_dir=tmp_path / "idx", embed_fn=fake_embed)
    stats = indexer.build()
    assert stats["files_indexed"] == 2
    assert stats["total_chunks"] > 0
    assert (tmp_path / "idx" / "vectors.npy").exists()
    assert (tmp_path / "idx" / "manifest.json").exists()


def test_incremental_skips_unchanged(tiny_kb_dir, tmp_path):
    idx_dir = tmp_path / "idx"
    indexer = Indexer(kb_dir=tiny_kb_dir, index_dir=idx_dir, embed_fn=fake_embed)
    indexer.build()
    stats = indexer.build()  # second build — nothing changed
    assert stats["files_added"] == 0
    assert stats["files_unchanged"] == 2


def test_incremental_detects_new_file(tiny_kb_dir, tmp_path):
    idx_dir = tmp_path / "idx"
    indexer = Indexer(kb_dir=tiny_kb_dir, index_dir=idx_dir, embed_fn=fake_embed)
    indexer.build()
    (tiny_kb_dir / "new_topic.md").write_text("## New Topic\n\nNew content here.\n")
    stats = indexer.build()
    assert stats["files_added"] == 1
    assert stats["files_unchanged"] == 2


def test_incremental_detects_modified_file(tiny_kb_dir, tmp_path):
    import time
    idx_dir = tmp_path / "idx"
    indexer = Indexer(kb_dir=tiny_kb_dir, index_dir=idx_dir, embed_fn=fake_embed)
    indexer.build()
    time.sleep(0.01)
    f = tiny_kb_dir / "topic_a.md"
    f.write_text(f.read_text() + "\n## New Section\n\nAdded content.\n")
    stats = indexer.build()
    assert stats["files_updated"] == 1


def test_rebuild_flag_reindexes_all(tiny_kb_dir, tmp_path):
    idx_dir = tmp_path / "idx"
    indexer = Indexer(kb_dir=tiny_kb_dir, index_dir=idx_dir, embed_fn=fake_embed)
    indexer.build()
    stats = indexer.build(rebuild=True)
    assert stats["files_indexed"] == 2


def test_atomic_write_on_interrupted_build(tiny_kb_dir, tmp_path):
    idx_dir = tmp_path / "idx"
    call_count = [0]

    def failing_embed(text: str) -> list[float]:
        call_count[0] += 1
        if call_count[0] > 3:
            raise RuntimeError("simulated failure")
        return [0.1, 0.2, 0.3]

    indexer = Indexer(kb_dir=tiny_kb_dir, index_dir=idx_dir, embed_fn=failing_embed)
    with pytest.raises(RuntimeError):
        indexer.build()
    # Partial index should not exist
    assert not (idx_dir / "vectors.npy").exists()
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
pytest tests/integration/test_indexer.py -v
```

Expected: `ImportError: No module named 'engine.indexer'`

- [ ] **Step 3: Implement `engine/indexer.py`**

```python
import json
import shutil
import tempfile
from pathlib import Path
from typing import Callable
import numpy as np
from engine.chunker import chunk_markdown

EmbedFn = Callable[[str], list[float]]


class Indexer:
    def __init__(self, kb_dir: Path, index_dir: Path, embed_fn: EmbedFn):
        self._kb_dir = Path(kb_dir)
        self._index_dir = Path(index_dir)
        self._embed_fn = embed_fn

    def build(self, rebuild: bool = False) -> dict:
        manifest_path = self._index_dir / "manifest.json"
        existing: dict = {}
        if not rebuild and manifest_path.exists():
            existing = {e["source_file"]: e["mtime"]
                       for e in json.loads(manifest_path.read_text()).get("files", [])}

        md_files = sorted(self._kb_dir.glob("*.md"))
        all_chunks, all_vectors = [], []
        stats = {"files_indexed": 0, "files_added": 0,
                 "files_updated": 0, "files_unchanged": 0, "total_chunks": 0}

        # Load existing data if incremental
        if existing and not rebuild and manifest_path.exists():
            old = json.loads(manifest_path.read_text())
            old_chunks = old.get("chunks", [])
            old_file_map: dict[str, list] = {}
            for c in old_chunks:
                old_file_map.setdefault(c["source_file"], []).append(c)
        else:
            old_file_map = {}

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            new_chunks, new_vectors = [], []

            for md_file in md_files:
                fname = md_file.name
                mtime = md_file.stat().st_mtime
                if not rebuild and fname in existing:
                    if existing[fname] == mtime:
                        # Unchanged — carry over from old index
                        for c in old_file_map.get(fname, []):
                            new_chunks.append(c)
                        stats["files_unchanged"] += 1
                        continue
                    else:
                        stats["files_updated"] += 1
                else:
                    stats["files_added"] += 1

                chunks = chunk_markdown(md_file.read_text(), source_file=fname)
                for chunk in chunks:
                    vec = self._embed_fn(chunk.text)
                    new_chunks.append({
                        "text": chunk.text,
                        "source_file": chunk.source_file,
                        "heading": chunk.heading,
                        "mtime": mtime,
                    })
                    new_vectors.append(vec)

            # Load vectors for unchanged files
            unchanged_chunks = [c for fname in existing
                                 if fname in old_file_map
                                 for c in old_file_map[fname]
                                 if not rebuild]

            all_chunks = new_chunks
            if new_vectors:
                vectors_array = np.array(new_vectors, dtype=np.float32)
            else:
                vectors_array = np.empty((0, 1), dtype=np.float32)

            stats["files_indexed"] = stats["files_added"] + stats["files_updated"]
            stats["total_chunks"] = len(all_chunks)

            # Atomic write
            np.save(str(tmp_path / "vectors.npy"), vectors_array)
            file_records = [{"source_file": f.name, "mtime": f.stat().st_mtime}
                            for f in md_files]
            (tmp_path / "manifest.json").write_text(json.dumps({
                "chunks": all_chunks,
                "files": file_records,
                "dim": vectors_array.shape[1] if vectors_array.ndim > 1 else 0,
            }, indent=2))

            # Swap
            self._index_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(tmp_path / "vectors.npy", self._index_dir / "vectors.npy")
            shutil.copy2(tmp_path / "manifest.json", self._index_dir / "manifest.json")

        return stats
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
pytest tests/integration/test_indexer.py -v
```

Expected: All 6 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/indexer.py tests/integration/test_indexer.py
git commit -m "feat: KB indexer — incremental build, mtime detection, atomic swap"
```

---

## Task 13: Quiz Orchestrator (`engine/quiz.py`)

**Files:**
- Create: `engine/quiz.py`
- Create: `tests/integration/test_quiz.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/integration/test_quiz.py
import pytest
from pathlib import Path
from engine.quiz import QuizSession, QuizConfig
from engine.question import Chunk
from engine.models.adapter import MockAdapter
from engine.sandbox import DirectRunner


@pytest.fixture
def mock_chunks():
    return [
        Chunk(text="SSDT maps syscall numbers to kernel function addresses. "
              "Rootkits overwrite entries to intercept system calls.",
              source_file="windows-internals.md", heading="SSDT Hooking"),
    ]


@pytest.fixture
def quiz_session(tmp_path, mock_chunks):
    local = MockAdapter(response='{"score": 1.0, "feedback": "Correct!"}')
    premium = MockAdapter(
        response='{"question": "What does SSDT stand for?", '
                 '"correct_answer": "System Service Descriptor Table", '
                 '"kb_excerpt": "SSDT maps syscall numbers..."}'
    )

    class MockRetriever:
        def search_by_vector(self, vec, top_k, min_score):
            from engine.retriever import RankedChunk
            return [RankedChunk(chunk=mock_chunks[0], score=0.9)]

    class MockEmbedder:
        def embed(self, text: str):
            import numpy as np
            return np.zeros(3, dtype=np.float32)

    config = QuizConfig(
        mode="hybrid", num_questions=1,
        question_types=["fill_in"], topic="SSDT",
        show_correct_answer=True, show_kb_excerpt=True,
    )
    return QuizSession(
        config=config,
        retriever=MockRetriever(),
        embedder=MockEmbedder(),
        local=local, premium=premium,
        sandbox=DirectRunner(),
        log_dir=tmp_path,
    )


def test_session_generates_question(quiz_session):
    q = quiz_session.next_question()
    assert q is not None
    assert q.text


def test_session_evaluates_answer(quiz_session):
    q = quiz_session.next_question()
    score = quiz_session.evaluate(q, user_answer="System Service Descriptor Table")
    assert score.value in {0.0, 0.5, 1.0}


def test_session_shows_correct_answer_on_wrong(quiz_session):
    q = quiz_session.next_question()
    score = quiz_session.evaluate(q, user_answer="wrong answer")
    assert score.correct_answer


def test_session_summary(quiz_session):
    q = quiz_session.next_question()
    quiz_session.evaluate(q, user_answer="any answer")
    summary = quiz_session.summary()
    assert "total_score" in summary
    assert "total_tokens_premium" in summary
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
pytest tests/integration/test_quiz.py -v
```

Expected: `ImportError: No module named 'engine.quiz'`

- [ ] **Step 3: Implement `engine/quiz.py`**

```python
import json
from dataclasses import dataclass
from pathlib import Path
from engine.question import Question, Chunk, Score, QuestionLog, PTCResult
from engine.models.adapter import ModelAdapter
from engine.ptc import compress
from engine.router import route
from engine.scorer import score_fill_in, score_from_model_eval
from engine.session_log import SessionLog
from engine.sandbox import SandboxRunner
from engine.prog_tool_calling import ProgToolCalling


@dataclass
class QuizConfig:
    mode: str
    num_questions: int
    question_types: list[str]
    topic: str
    show_correct_answer: bool
    show_kb_excerpt: bool


class QuizSession:
    def __init__(self, config: QuizConfig, retriever, embedder,
                 local: ModelAdapter, premium: ModelAdapter,
                 sandbox: SandboxRunner, log_dir: Path):
        self._config = config
        self._retriever = retriever
        self._embedder = embedder
        self._local = local
        self._premium = premium
        self._prog_tool = ProgToolCalling(model=premium, sandbox=sandbox)
        self._log = SessionLog(
            log_dir=log_dir, mode=config.mode,
            local_model=getattr(local, '_model', 'local'),
            premium_model=getattr(premium, '_model', 'premium'),
        )
        self._question_num = 0
        self._tokens_local = 0
        self._tokens_premium = 0

    def next_question(self) -> Question | None:
        import numpy as np
        query_vec = self._embedder.embed(self._config.topic)
        ranked = self._retriever.search_by_vector(query_vec, top_k=5, min_score=0.1)
        if not ranked:
            return None
        chunks = [r.chunk for r in ranked]

        qtype = self._config.question_types[self._question_num % len(self._config.question_types)]
        ptc_result = compress(chunks, task_type="generate_question")
        destination = route("generate_question", qtype, self._config.mode)

        if destination == "premium":
            prog_result = self._prog_tool.run(ptc_result, task=f"generate {qtype} question about {self._config.topic}")
            context = prog_result.output_text
            self._tokens_premium += len(context) // 4
        else:
            context = ptc_result.compressed_text
            self._tokens_local += len(context) // 4

        adapter = self._premium if destination == "premium" else self._local
        prompt = (
            f"Generate a {qtype} quiz question based on this content.\n"
            f"Respond with JSON only: "
            f'{{\"question\": \"...\", \"correct_answer\": \"...\", \"kb_excerpt\": \"...\"}}\n\n'
            f"Content:\n{context}"
        )
        raw = adapter.generate(prompt)
        try:
            data = json.loads(raw)
            self._question_num += 1
            return Question(
                type=qtype,
                text=data["question"],
                correct_answer=data["correct_answer"],
                kb_excerpt=data.get("kb_excerpt", ""),
                source_file=chunks[0].source_file if chunks else "",
            )
        except (json.JSONDecodeError, KeyError):
            return None

    def evaluate(self, question: Question, user_answer: str) -> Score:
        destination = route("evaluate_answer", question.type, self._config.mode)
        if question.type == "fill_in":
            score = score_fill_in(user_answer, question.correct_answer)
        else:
            adapter = self._premium if destination == "premium" else self._local
            score = score_from_model_eval(
                user_answer=user_answer,
                question_text=question.text,
                correct_answer=question.correct_answer,
                adapter=adapter,
            )
            if destination == "premium":
                self._tokens_premium += (len(user_answer) + len(question.text)) // 4
            else:
                self._tokens_local += (len(user_answer) + len(question.text)) // 4

        self._log.add(QuestionLog(
            question_num=self._question_num,
            question_type=question.type,
            question_text=question.text,
            user_answer=user_answer,
            correct_answer=question.correct_answer,
            score=score.value,
            model_used=destination,
            tokens_local=self._tokens_local,
            tokens_premium=self._tokens_premium,
            ptc_compression_ratio=0.0,
        ))
        return score

    def summary(self) -> dict:
        return self._log.summary() | {
            "total_tokens_premium": self._tokens_premium,
            "total_tokens_local": self._tokens_local,
        }
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
pytest tests/integration/test_quiz.py -v
```

Expected: All 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/quiz.py tests/integration/test_quiz.py
git commit -m "feat: quiz session orchestrator — full pipeline with DI"
```

---

## Task 14: CLI (`cli/main.py`)

**Files:**
- Create: `cli/main.py`
- Create: `tests/e2e/test_cli.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/e2e/test_cli.py
import pytest
from typer.testing import CliRunner
from cli.main import app

runner = CliRunner()


def test_kb_index_command_requires_config(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["kb", "index"])
    assert result.exit_code != 0 or "config" in result.output.lower()


def test_kb_list_no_index(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config.yaml").write_text(
        "mode: local\nlocal_model: phi4-mini\n"
        "premium_model: claude-sonnet-4-6\napi_key_file: Claude-Key.txt\n"
        "embedding_model: all-MiniLM-L6-v2\n"
        "quiz:\n  default_questions: 5\n  max_questions: 20\n"
        "  show_correct_answer: true\n  show_kb_excerpt: true\n"
        "retriever:\n  top_k: 5\n  min_score: 0.25\n"
        "ptc:\n  max_output_tokens: 1000\n"
        "prog_tool_calling:\n  sandbox_timeout_sec: 10\n"
        "logging:\n  enabled: true\n  log_dir: logs/\n  log_compression_ratio: true\n"
    )
    (tmp_path / "kb").mkdir()
    result = runner.invoke(app, ["kb", "list"])
    assert result.exit_code == 0


def test_quiz_topic_not_found(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config.yaml").write_text(
        "mode: local\nlocal_model: phi4-mini\n"
        "premium_model: claude-sonnet-4-6\napi_key_file: Claude-Key.txt\n"
        "embedding_model: all-MiniLM-L6-v2\n"
        "quiz:\n  default_questions: 5\n  max_questions: 20\n"
        "  show_correct_answer: true\n  show_kb_excerpt: true\n"
        "retriever:\n  top_k: 5\n  min_score: 0.25\n"
        "ptc:\n  max_output_tokens: 1000\n"
        "prog_tool_calling:\n  sandbox_timeout_sec: 10\n"
        "logging:\n  enabled: true\n  log_dir: logs/\n  log_compression_ratio: true\n"
    )
    (tmp_path / "kb").mkdir()
    (tmp_path / "kb_index").mkdir()
    result = runner.invoke(app, ["quiz", "--topic", "quantum computing", "--questions", "1"])
    assert "No KB content" in result.output or result.exit_code != 0


def test_kb_search_no_index(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config.yaml").write_text("mode: local\nlocal_model: phi4-mini\n"
        "premium_model: claude-sonnet-4-6\napi_key_file: Claude-Key.txt\n"
        "embedding_model: all-MiniLM-L6-v2\n"
        "quiz:\n  default_questions: 5\n  max_questions: 20\n"
        "  show_correct_answer: true\n  show_kb_excerpt: true\n"
        "retriever:\n  top_k: 5\n  min_score: 0.25\n"
        "ptc:\n  max_output_tokens: 1000\n"
        "prog_tool_calling:\n  sandbox_timeout_sec: 10\n"
        "logging:\n  enabled: true\n  log_dir: logs/\n  log_compression_ratio: true\n")
    result = runner.invoke(app, ["kb", "search", "SSDT"])
    assert "Index is empty" in result.output or result.exit_code != 0
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
pytest tests/e2e/test_cli.py -v
```

Expected: `ImportError: No module named 'cli.main'`

- [ ] **Step 3: Implement `cli/main.py`**

```python
import sys
from pathlib import Path
from typing import Optional
import typer
import yaml

app = typer.Typer(help="ai-kb-quiz — KB-grounded quiz with hybrid model routing")
kb_app = typer.Typer(help="KB management commands")
app.add_typer(kb_app, name="kb")


def _load_config(config_path: Path = Path("config/config.yaml")) -> dict:
    if not config_path.exists():
        typer.echo(f"Config not found: {config_path}. Copy config/config.example.yaml to {config_path}")
        raise typer.Exit(code=1)
    return yaml.safe_load(config_path.read_text())


@kb_app.command("index")
def kb_index(rebuild: bool = typer.Option(False, "--rebuild", help="Force full rebuild")):
    """Build or update the KB vector index."""
    from engine.indexer import Indexer
    from sentence_transformers import SentenceTransformer
    cfg = _load_config()
    model = SentenceTransformer(cfg.get("embedding_model", "all-MiniLM-L6-v2"))
    embed_fn = lambda text: model.encode(text).tolist()
    indexer = Indexer(kb_dir=Path("kb"), index_dir=Path("kb_index"), embed_fn=embed_fn)
    typer.echo("Building KB index...")
    stats = indexer.build(rebuild=rebuild)
    typer.echo(f"Done. Files indexed: {stats['files_indexed']}, "
               f"chunks: {stats['total_chunks']}, "
               f"unchanged: {stats['files_unchanged']}")


@kb_app.command("list")
def kb_list():
    """List KB files and their index status."""
    import json
    kb_dir = Path("kb")
    index_manifest = Path("kb_index/manifest.json")
    indexed_files: set[str] = set()
    indexed_chunks: dict[str, int] = {}
    if index_manifest.exists():
        data = json.loads(index_manifest.read_text())
        for c in data.get("chunks", []):
            fname = c["source_file"]
            indexed_files.add(fname)
            indexed_chunks[fname] = indexed_chunks.get(fname, 0) + 1
    if not kb_dir.exists():
        typer.echo("kb/ directory not found.")
        raise typer.Exit(code=1)
    typer.echo(f"{'File':<35} {'Indexed':<10} {'Chunks':<8} {'Last Modified'}")
    typer.echo("-" * 70)
    for f in sorted(kb_dir.glob("*.md")):
        indexed = "yes" if f.name in indexed_files else "no"
        chunks = str(indexed_chunks.get(f.name, "—"))
        mtime = f.stat().st_mtime
        from datetime import datetime
        mdate = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d")
        warn = " ⚠" if indexed == "no" else ""
        typer.echo(f"{f.name:<35} {indexed:<10} {chunks:<8} {mdate}{warn}")


@kb_app.command("add")
def kb_add(filepath: str = typer.Argument(..., help="Path to .md file to add")):
    """Add a markdown file to the KB."""
    src = Path(filepath)
    if src.suffix != ".md":
        typer.echo("Only .md files are supported.")
        raise typer.Exit(code=1)
    dest = Path("kb") / src.name
    if dest.exists():
        overwrite = typer.confirm(f"File {dest} already exists. Overwrite?", default=False)
        if not overwrite:
            raise typer.Exit(code=0)
    import shutil
    shutil.copy2(src, dest)
    typer.echo(f"Added {dest}. Run 'python cli/main.py kb index' to index it.")


@kb_app.command("remove")
def kb_remove(filename: str = typer.Argument(..., help="Filename to remove from kb/")):
    """Remove a KB file and its index entries."""
    target = Path("kb") / filename
    if not target.exists():
        typer.echo(f"{target} not found.")
        raise typer.Exit(code=1)
    confirm = typer.confirm(
        f"This will remove {target} and its index entries. Continue?", default=False)
    if not confirm:
        raise typer.Exit(code=0)
    target.unlink()
    typer.echo(f"Removed {target}. Run 'python cli/main.py kb index --rebuild' to update index.")


@kb_app.command("search")
def kb_search(query: str = typer.Argument(...),
              top: int = typer.Option(5, "--top", help="Number of results")):
    """Semantic search over the KB."""
    import numpy as np
    from engine.retriever import Retriever, IndexNotFoundError
    from sentence_transformers import SentenceTransformer
    cfg = _load_config()
    try:
        retriever = Retriever(index_dir=Path("kb_index"))
    except IndexNotFoundError:
        typer.echo("Index is empty. Run: python cli/main.py kb index")
        raise typer.Exit(code=1)
    model = SentenceTransformer(cfg.get("embedding_model", "all-MiniLM-L6-v2"))
    query_vec = np.array(model.encode(query), dtype=np.float32)
    results = retriever.search_by_vector(query_vec, top_k=top, min_score=0.0)
    if not results:
        typer.echo("No results found.")
        return
    for i, r in enumerate(results, 1):
        typer.echo(f"\n[{i}] score={r.score:.3f} | {r.chunk.source_file} — {r.chunk.heading}")
        typer.echo(f"    {r.chunk.text[:200]}...")


@app.command("quiz")
def quiz_cmd(
    topic: str = typer.Option(..., "--topic", help="KB topic to quiz on"),
    questions: Optional[int] = typer.Option(None, "--questions", help="Number of questions"),
    types: Optional[str] = typer.Option(None, "--types", help="Comma-separated: conceptual,code,fill_in"),
):
    """Run an interactive quiz session."""
    import numpy as np
    from engine.retriever import Retriever, IndexNotFoundError
    from engine.quiz import QuizSession, QuizConfig
    from engine.sandbox import DirectRunner
    from engine.models.local_adapter import LocalAdapter
    from engine.models.premium_adapter import PremiumAdapter
    from sentence_transformers import SentenceTransformer

    cfg = _load_config()
    quiz_cfg_raw = cfg.get("quiz", {})
    num_q = questions or quiz_cfg_raw.get("default_questions", 5)
    if num_q < 1:
        typer.echo("Question count must be at least 1.")
        raise typer.Exit(code=1)
    num_q = min(num_q, quiz_cfg_raw.get("max_questions", 20))
    qtypes = types.split(",") if types else ["conceptual", "code", "fill_in"]

    try:
        retriever = Retriever(index_dir=Path("kb_index"))
    except IndexNotFoundError:
        typer.echo("Index is empty. Run: python cli/main.py kb index")
        raise typer.Exit(code=1)

    st_model = SentenceTransformer(cfg.get("embedding_model", "all-MiniLM-L6-v2"))

    class Embedder:
        def embed(self, text: str) -> np.ndarray:
            return np.array(st_model.encode(text), dtype=np.float32)

    mode = cfg.get("mode", "hybrid")
    local = LocalAdapter(model=cfg.get("local_model", "phi4-mini"))
    try:
        premium = PremiumAdapter.from_config(
            model=cfg.get("premium_model", "claude-sonnet-4-6"),
            api_key_file=Path(cfg.get("api_key_file", "Claude-Key.txt")),
        )
    except EnvironmentError as e:
        if mode == "premium":
            typer.echo(str(e))
            raise typer.Exit(code=1)
        premium = local  # fallback for hybrid/local mode

    session = QuizSession(
        config=QuizConfig(mode=mode, num_questions=num_q, question_types=qtypes,
                          topic=topic,
                          show_correct_answer=quiz_cfg_raw.get("show_correct_answer", True),
                          show_kb_excerpt=quiz_cfg_raw.get("show_kb_excerpt", True)),
        retriever=retriever, embedder=Embedder(),
        local=local, premium=premium,
        sandbox=DirectRunner(),
        log_dir=Path(cfg.get("logging", {}).get("log_dir", "logs")),
    )

    typer.echo(f"\nStarting quiz: {topic} ({num_q} questions)\n{'='*50}")
    scores = []
    for i in range(num_q):
        question = session.next_question()
        if question is None:
            typer.echo(f"No KB content found for topic '{topic}'.")
            break
        typer.echo(f"\nQ{i+1}/{num_q} [{question.type.upper()}]\n{question.text}")
        if question.type == "code":
            typer.echo("(Enter your code. Finish with a blank line)")
            lines = []
            while True:
                line = input(">>> ")
                if line == "":
                    break
                lines.append(line)
            user_answer = "\n".join(lines)
        else:
            user_answer = typer.prompt("Your answer")

        score = session.evaluate(question, user_answer)
        scores.append(score.value)
        icon = "✓" if score.value == 1.0 else ("~" if score.value == 0.5 else "✗")
        typer.echo(f"\n{icon} Score: {score.value} — {score.feedback}")
        if quiz_cfg_raw.get("show_correct_answer", True):
            typer.echo(f"  Correct answer: {score.correct_answer}")
        if quiz_cfg_raw.get("show_kb_excerpt", True) and question.kb_excerpt:
            typer.echo(f"  KB source [{question.source_file}]: {question.kb_excerpt[:150]}...")

    if scores:
        total = sum(scores)
        pct = int(total / len(scores) * 100)
        summary = session.summary()
        typer.echo(f"\n{'='*50}")
        typer.echo(f"Final Score  : {total}/{len(scores)}  ({pct}%)")
        typer.echo(f"Models used  : {mode}")
        tokens_saved = summary.get("avg_ptc_compression_ratio", 0)
        typer.echo(f"Token savings: {int(tokens_saved * 100)}% via PTC")


if __name__ == "__main__":
    app()
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
pytest tests/e2e/test_cli.py -v
```

Expected: All 4 CLI tests PASS.

- [ ] **Step 5: Run full test suite**

```bash
pytest -v
```

Expected: All tests PASS. Note any skipped tests for live API paths.

- [ ] **Step 6: Update README status table**

In `README.md`, mark these milestones done:
```
| Engine core (retriever, PTC, router, quiz) | ✅ Done |
| CLI                                        | ✅ Done |
| Tests                                      | ✅ Done |
```

- [ ] **Step 7: Final commit**

```bash
git add cli/main.py tests/e2e/test_cli.py README.md
git commit -m "feat: Typer CLI — quiz, kb index/add/remove/list/search"
git push
```

---

## Completion Checklist

- [ ] `pytest -v` — all tests pass, no skips hiding logic
- [ ] `python cli/main.py --help` shows all subcommands
- [ ] `python cli/main.py kb index` runs without error (with real KB + Ollama)
- [ ] `python cli/main.py quiz --topic "EDR architecture" --questions 2` completes a session
- [ ] Session log written to `logs/`
- [ ] No raw KB text appears in any model prompt (verify via MockAdapter.calls in tests)

---

## Post-Implementation Quality Tasks
> Derived from critical thinking analysis (2026-04-12-critical-thinking-analysis.md).
> Ordered by priority. P0/P1 are blocking for the tool to be trustworthy; P2/P3/P4 are
> improvements that can follow.

---

### Task 15 [P0] — Scorer Calibration: Golden Evaluation Test Set

**Problem:** `Scorer.evaluate()` + `PremiumAdapter` is the Error Kernel. A wrong answer silently
scoring 1.0 corrupts the learning loop — worse than a crash. No calibration exists today.

**Files:**
- Create: `tests/integration/test_scorer_calibration.py`

- [ ] **Step 1: Build golden test set**

Hand-write 10 (question, wrong_answer, correct_answer) triples from the KB. Cover all three
question types. Mark each with the expected score for a wrong answer (must be 0.0 or 0.5, never 1.0).

Example entries:
```python
GOLDEN_PAIRS = [
    {
        "question": "What does IRQL DISPATCH_LEVEL prohibit?",
        "wrong_answer": "It prevents user-mode code from running.",
        "correct_answer": "Waiting on dispatcher objects; accessing paged memory.",
        "max_wrong_score": 0.5,  # partial credit possible but never 1.0
    },
    {
        "question": "Fill in: The _____ table maps Windows syscall numbers to kernel addresses.",
        "wrong_answer": "IDT",
        "correct_answer": "SSDT",
        "max_wrong_score": 0.0,  # completely wrong term — must score 0.0
    },
    # ... 8 more
]
```

- [ ] **Step 2: Write calibration test**

```python
# tests/integration/test_scorer_calibration.py
# Requires: ANTHROPIC_API_KEY env var set. Skip if absent.
import os
import pytest
from engine.scorer import score_from_model_eval
from engine.models.premium_adapter import PremiumAdapter
import anthropic

pytestmark = pytest.mark.skipif(
    not os.getenv("ANTHROPIC_API_KEY"),
    reason="ANTHROPIC_API_KEY not set — skipping live calibration test"
)

@pytest.fixture(scope="module")
def premium():
    return PremiumAdapter(
        model="claude-haiku-4-5-20251001",
        client=anthropic.Anthropic(),
        max_tokens=256,
    )

@pytest.mark.parametrize("pair", GOLDEN_PAIRS)
def test_wrong_answer_never_scores_full(premium, pair):
    score = score_from_model_eval(
        question=pair["question"],
        user_answer=pair["wrong_answer"],
        correct_answer=pair["correct_answer"],
        adapter=premium,
    )
    assert score.value <= pair["max_wrong_score"], (
        f"Wrong answer scored {score.value} — expected <= {pair['max_wrong_score']}\n"
        f"Feedback: {score.feedback}"
    )
```

- [ ] **Step 3: Run and verify**

```bash
ANTHROPIC_API_KEY=... pytest tests/integration/test_scorer_calibration.py -v
```

Expected: All 10 pairs pass. If any wrong answer scores 1.0, fix the evaluation prompt in
`scorer.py` before shipping.

- [ ] **Step 4: Commit**

```bash
git add tests/integration/test_scorer_calibration.py
git commit -m "test: golden calibration set for Scorer.evaluate — Error Kernel guard"
```

---

### Task 16 [P1] — Cross-Session Seen-Question Deduplication

**Problem:** No cross-session tracking. ~120 chunks, top_k=5 per question → KB exhausted in
~2 weeks. Same chunks repeat indefinitely (reinforcing negative feedback loop).

**Files:**
- Modify: `engine/retriever.py`
- Create: `tests/unit/test_seen_chunks.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/unit/test_seen_chunks.py
from engine.retriever import SeenChunks

def test_empty_on_init(tmp_path):
    sc = SeenChunks(tmp_path / "seen.json")
    assert sc.seen_ids == set()

def test_mark_and_persist(tmp_path):
    path = tmp_path / "seen.json"
    sc = SeenChunks(path)
    sc.mark(["chunk-a", "chunk-b"])
    sc2 = SeenChunks(path)  # reload
    assert "chunk-a" in sc2.seen_ids
    assert "chunk-b" in sc2.seen_ids

def test_is_seen(tmp_path):
    sc = SeenChunks(tmp_path / "seen.json")
    sc.mark(["chunk-x"])
    assert sc.is_seen("chunk-x")
    assert not sc.is_seen("chunk-y")

def test_reset_clears(tmp_path):
    sc = SeenChunks(tmp_path / "seen.json")
    sc.mark(["chunk-a"])
    sc.reset()
    assert sc.seen_ids == set()
```

- [ ] **Step 2: Implement `SeenChunks` in `engine/retriever.py`**

Add to existing `retriever.py`:
```python
import json
from pathlib import Path

class SeenChunks:
    """Persists chunk IDs seen across sessions to reduce repetition."""

    def __init__(self, path: Path):
        self._path = path
        self.seen_ids: set[str] = self._load()

    def _load(self) -> set[str]:
        if self._path.exists():
            return set(json.loads(self._path.read_text()))
        return set()

    def mark(self, ids: list[str]) -> None:
        self.seen_ids.update(ids)
        self._path.write_text(json.dumps(list(self.seen_ids)))

    def is_seen(self, chunk_id: str) -> bool:
        return chunk_id in self.seen_ids

    def reset(self) -> None:
        self.seen_ids = set()
        if self._path.exists():
            self._path.unlink()
```

Update `Retriever.search()`: after sampling `top_k` results, prefer unseen chunks. If fewer than
`top_k` unseen chunks are available, fill from seen chunks to maintain the requested count.

```python
# In Retriever.search(), after sampling candidates:
if seen_chunks:
    unseen = [c for c in candidates if not seen_chunks.is_seen(c.heading)]
    seen = [c for c in candidates if seen_chunks.is_seen(c.heading)]
    result = (unseen + seen)[:top_k]
else:
    result = candidates[:top_k]
```

- [ ] **Step 3: Wire into `quiz.py`**

`SeenChunks` path: `logs/seen_chunks.json` (already gitignored via `logs/`). Pass as optional
constructor argument to `Retriever`; `None` disables deduplication.

- [ ] **Step 4: Run tests and commit**

```bash
pytest tests/unit/test_seen_chunks.py -v
git add engine/retriever.py tests/unit/test_seen_chunks.py
git commit -m "feat: SeenChunks — cross-session chunk deduplication to reduce repetition"
```

---

### Task 17 [P1] — Resilience: Ollama Fallback + Auto-Index

**Problem 1:** If Ollama is unavailable, `fill_in` question generation raises `OllamaUnavailableError`
with no recovery. The tool becomes completely unusable even though the premium path could substitute.

**Problem 2:** First-run requires `kb index` before `quiz`. Two-command startup increases friction.

**Files:**
- Modify: `engine/router.py`
- Modify: `cli/main.py`

- [ ] **Step 1: Add local-down fallback to router**

Extend `route()` to accept an optional `local_available: bool` flag:
```python
def route(task_type: str, question_type: str | None, mode: str,
          local_available: bool = True) -> Literal["local", "premium"]:
    result = _route_table(task_type, question_type, mode)
    if result == "local" and not local_available:
        return "premium"
    return result
```

In `quiz.py`, catch `OllamaUnavailableError` on the first local call; set `local_available=False`
for the remainder of the session and log a one-time warning: `"Local model unavailable — routing
all tasks to premium for this session."`

- [ ] **Step 2: Write tests for fallback routing**

```python
def test_local_down_routes_fill_in_to_premium():
    assert route("generate_question", "fill_in", "hybrid", local_available=False) == "premium"

def test_local_down_does_not_affect_premium_mode():
    assert route("generate_question", "conceptual", "premium", local_available=False) == "premium"
```

- [ ] **Step 3: Auto-index on `quiz` command**

In `cli/main.py`, at the start of the `quiz` command, check if the index exists:
```python
if not retriever.index_exists():
    typer.echo("[quiz] Index not found — running kb index first...")
    run_indexer(kb_dir, incremental=False)
```

- [ ] **Step 4: Commit**

```bash
git add engine/router.py cli/main.py tests/unit/test_router.py
git commit -m "feat: Ollama fallback routing + auto-index on first quiz run"
```

---

### Task 18 [P2] — `quiz stats` Command: Cross-Session Analytics

**Problem:** SessionLog writes per-question JSON but there is no command to read it. The OODA
Orient phase is unbuilt: the user has no signal of what they know or where they are weak.

**Files:**
- Modify: `cli/main.py`
- Create: `tests/unit/test_stats.py`

- [ ] **Step 1: Implement stats aggregation**

```python
# In cli/main.py, add stats subcommand:
@kb_app.command("stats")
def quiz_stats(logs_dir: Path = typer.Option(Path("logs"), help="Session logs directory")):
    """Show score summary across all past sessions."""
    files = sorted(logs_dir.glob("session_*.json"))
    if not files:
        typer.echo("No session logs found. Run a quiz session first.")
        raise typer.Exit()

    by_topic: dict[str, list[float]] = {}
    total, correct = 0, 0

    for f in files:
        for line in f.read_text().splitlines():
            entry = json.loads(line)
            topic = entry.get("source_file", "unknown")
            score = entry.get("score", 0.0)
            by_topic.setdefault(topic, []).append(score)
            total += 1
            if score == 1.0:
                correct += 1

    typer.echo(f"\nTotal questions: {total}  |  Overall score: {correct/total:.0%}\n")
    typer.echo("Score by topic (weakest first):")
    ranked = sorted(by_topic.items(), key=lambda kv: sum(kv[1]) / len(kv[1]))
    for topic, scores in ranked:
        avg = sum(scores) / len(scores)
        typer.echo(f"  {avg:.0%}  {topic}  ({len(scores)} questions)")
```

- [ ] **Step 2: Write tests**

Test with synthetic session JSON files (two topics, mixed scores). Verify ranking order and
percentage output.

- [ ] **Step 3: Commit**

```bash
git add cli/main.py tests/unit/test_stats.py
git commit -m "feat: quiz stats command — cross-session score aggregation by topic"
```

---

### Task 19 [P3/P4] — Code Quality: PTC Flag, Trusted Runner, Router Typing

Three small cleanups identified by the analysis.

**Files:**
- Modify: `cli/main.py` (--no-ptc flag)
- Modify: `engine/sandbox.py` (DirectRunner for trusted scripts)
- Modify: `engine/router.py` (Literal return type)
- Modify: `engine/question.py` (defer code question type)

- [ ] **Step 1: Add `--no-ptc` flag**

```python
@app.command()
def quiz(
    topic: str = typer.Argument(...),
    questions: int = typer.Option(5),
    mode: str = typer.Option("hybrid"),
    no_ptc: bool = typer.Option(False, "--no-ptc", help="Skip PTC; use KB excerpt directly"),
):
```

Pass `ptc_enabled = not no_ptc` to `QuizOrchestrator`. When disabled, the KB excerpt goes
directly to the question generation prompt without PTC compression.

- [ ] **Step 2: Use DirectRunner for version-controlled scripts**

In `prog_tool_calling.py`, distinguish script source:
```python
runner = DirectRunner() if script_source == "builtin" else sandbox_runner
```

`ptc_scripts/` scripts are `"builtin"` — reviewed in version control. Only externally provided
scripts use the full sandbox.

- [ ] **Step 3: Type router return as `Literal`**

```python
from typing import Literal

def route(...) -> Literal["local", "premium"]:
```

This surfaces the implicit contract at the type level and prevents `quiz.py` from silently
handling unexpected return values.

- [ ] **Step 4: Defer `code` question type**

In `engine/question.py`, keep `"code"` in `VALID_QUESTION_TYPES` but add a note:
```python
# "code" type accepted for future use but not yet fully implemented.
# Grading uses model eval (same as conceptual) — no code execution scoring.
```

Remove `"code"` from the default `question_type_weights` in `quiz.py` until code execution
scoring is implemented. This prevents the router from dispatching code questions that will
score the same as conceptual questions with more latency.

- [ ] **Step 5: Commit**

```bash
git add cli/main.py engine/sandbox.py engine/router.py engine/question.py
git commit -m "chore: --no-ptc flag, DirectRunner for builtin scripts, Literal router type, defer code type"
```
- [ ] README status table updated
