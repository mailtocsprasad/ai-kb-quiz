# ai-kb-quiz — Architecture Design Spec

> **Method:** ADD (Attribute-Driven Design) + ATAM (Architecture Tradeoff Analysis Method)
> **Date:** 2026-04-11
> **Status:** Approved — ready for implementation planning

---

## 1. Purpose & Scope

`ai-kb-quiz` is a CLI quiz application that demonstrates hybrid multi-model AI engineering
patterns. It serves two purposes:

1. **Working tool** — quiz over a local vectorized knowledge base using local and/or premium models
2. **Portfolio showcase** — demonstrates PTC, Programmable Tool Calling, hybrid model routing,
   and vectorized semantic search as reusable, documented patterns

Phase 1: CLI. Phase 2: Web UI (interface layer only — engine unchanged).

---

## 2. Architectural Drivers

### 2.1 Primary Functional Requirements

| ID | Requirement |
|----|------------|
| FR1 | Generate quiz questions grounded in KB content via vector retrieval |
| FR2 | Evaluate user answers and provide scored feedback with correct answer shown |
| FR3 | Route subtasks to local or premium model based on complexity and config mode |
| FR4 | Apply PTC compression before every model call; raw KB text never reaches any model |
| FR5 | CLI interaction: question → answer → feedback → next → score summary |

### 2.2 Quality Attribute Scenarios

| ID | QA | Scenario | Response Measure |
|----|-----|---------|-----------------|
| QA1 | Modifiability | Dev swaps local model via `config.yaml` change only | No code change; system runs in any of 3 modes |
| QA2 | Performance | PTC reduces raw KB tokens before any model call | ≥40% token reduction per session |
| QA3 | Testability | Full pipeline runs in CI with zero live API calls | No Ollama, no Anthropic, no model download required |
| QA4 | Extensibility | Web UI added via new `interface/` layer | `engine/` untouched; no breaking changes |
| QA5 | Observability | Every session logs model, tokens, PTC ratios | JSON log per session; per-question flush |
| QA6 | Resource Efficiency | System operates in local-only, premium-only, or hybrid mode | Graceful degradation if either model is absent |
| QA7 | Security | Model-generated scripts cannot access OS, filesystem, or network | RestrictedPython AST + Job Object blocks all escape paths |

### 2.3 Constraints

- Python 3.x; no C++ compilation required
- Local model via Ollama HTTP API; GPU-accelerated where available, CPU fallback otherwise
- API key: `ANTHROPIC_API_KEY` env var first, then `api_key_file` path in config
- Only original-content KB files in public repo
- All components testable in isolation via dependency injection
- Code questions: user submits code, premium model evaluates — no user code execution

### 2.4 Driver Priority

| Driver | Business Value | Technical Risk | Priority |
|--------|---------------|----------------|----------|
| QA2 PTC-first | H | H | Highest |
| QA7 Sandbox security | H | H | Highest |
| FR3 Model router | H | H | Highest |
| QA3 Testability | H | L | High |
| QA1 Modifiability | H | M | High |
| QA6 Optional models | H | M | High |
| QA4 Extensibility | H | M | High |

---

## 3. ADD Iteration 1 — Overall Decomposition

**Goal:** Establish top-level elements, responsibilities, and interfaces.

### Element Responsibility Table

| Element | Responsibility |
|---------|---------------|
| `config/config.yaml` | Declares mode, local_model, premium_model, embedding_model, embedding_backend, api_key_file, quiz/retriever/ptc settings |
| `engine/embedder.py` | `make_embed_fn(model, backend, ollama_base_url) → EmbedFn`. Factory that returns an `EmbedFn` backed by either Ollama `/api/embeddings` or `sentence-transformers`. Injected into `Indexer` and `Retriever`. |
| `kb/` | Original-content markdown KB files. Versioned in repo. |
| `engine/retriever.py` | Semantic search over vector index. Returns top-K `Chunk` objects above similarity threshold. |
| `engine/ptc.py` | Runs developer-authored extraction scripts against KB chunks. Returns `PTCResult`. Never calls a model. |
| `engine/ptc_scripts/` | One script per task type. Each reads JSON chunks from stdin, writes compact output to stdout. |
| `engine/prog_tool_calling.py` | Asks premium model to generate an extraction script. Validates via RestrictedPython. Runs in sandbox. Returns `ProgToolResult`. |
| `engine/sandbox.py` | Two-layer isolation: RestrictedPython AST check + subprocess in Windows Job Object. |
| `engine/router.py` | Maps `(task_type, question_type, mode)` → `"local"` or `"premium"`. Pure stateless function. |
| `engine/quiz.py` | Session orchestrator. Retrieve → PTC → route → generate → answer → evaluate → score → log. |
| `engine/models/adapter.py` | `ModelAdapter` protocol: `generate(prompt: str) -> str`. |
| `engine/models/local_adapter.py` | Ollama HTTP API. Graceful degradation if unreachable. |
| `engine/models/premium_adapter.py` | Anthropic SDK. Resolves API key from env var then key file. |
| `cli/main.py` | Typer CLI: `quiz`, `kb index`, `kb add`, `kb remove`, `kb list`, `kb search` subcommands. |
| `docs/patterns/` | `ptc-pattern.md`, `programmable-tool-calling.md` — reusable pattern documentation. |

### Design Decisions (Iteration 1)

| Decision | Rationale | Discarded Alternatives |
|----------|-----------|----------------------|
| PTC generates+executes scripts dynamically | Keeps premium model input small regardless of KB size | Pre-summarize chunks (still a model call); truncate chunks (lossy) |
| Ollama HTTP API for local (not llama.cpp bindings) | Model-agnostic, swappable by config name, no compilation; GPU-accelerated automatically when available | llama.cpp Python bindings (model-specific build steps) |
| `ModelAdapter` interface `generate(prompt) -> str` | Both adapters mockable; router never touches SDK | Direct SDK calls in quiz.py (untestable, tightly coupled) |
| Mode inferred from config (not runtime flag) | Same code runs in all three modes; works in automated/scripted use | CLI flags only (breaks scripted use) |
| `embedding_backend` config field (`"ollama"` \| `"sentence-transformers"`) | Explicit over magic auto-detection; Ollama preferred when installed (no extra Python dep, higher-quality models) | Auto-detect by model name (ambiguous — `nomic-embed-text` has no distinguishing prefix) |
| `make_embed_fn` factory in `engine/embedder.py` | Swappable at construction time; CI uses `lambda s: [0.0]*N`; live uses real backend | Conditional import in indexer/retriever (logic scattered, untestable) |

---

## 4. ADD Iteration 2 — PTC, Programmable Tool Calling, Router, Sandbox

**Goal:** Address QA2, QA7, FR3, QA6 — the `(H,H)` drivers.

### Element Responsibility Table (refined)

| Element | Responsibility |
|---------|---------------|
| `engine/ptc.py` | Selects script by task_type from `ptc_scripts/`. Runs it in-process (trusted code). Returns `PTCResult(compressed_text, raw_tokens, compressed_tokens)`. |
| `engine/ptc_scripts/` | `summarize_chunk.py`, `extract_concepts.py`, `extract_code_context.py`. Pure functions on text — independently testable. |
| `engine/prog_tool_calling.py` | Receives `PTCResult`. Prompts premium model to generate extraction script. Validates via `sandbox.validate()`. Runs via `sandbox.execute()`. Falls back to PTCResult directly if script fails. |
| `engine/sandbox.py` | `SandboxRunner` protocol: `validate(script: str) -> ValidationResult` + `execute(script: str, input: str) -> ExecutionResult`. `JobObjectRunner` (Windows), `DirectRunner` (CI/non-Windows). |
| `engine/router.py` | Lookup table: `(task_type, question_type, mode) -> "local" \| "premium"`. Mode=local overrides all. Mode=premium overrides all. |

### Router Decision Table

| task_type | question_type | hybrid | local | premium |
|-----------|--------------|--------|-------|---------|
| `summarize_chunk` | — | local | local | premium |
| `generate_question` | `fill_in` | local | local | premium |
| `generate_question` | `conceptual` | premium | local | premium |
| `generate_question` | `code` | premium | local | premium |
| `evaluate_answer` | `fill_in` | local | local | premium |
| `evaluate_answer` | `conceptual` | premium | local | premium |
| `evaluate_answer` | `code` | premium | local | premium |
| `score_answer` | any | local | local | premium |

### Design Decisions (Iteration 2)

| Decision | Rationale | Discarded Alternatives |
|----------|-----------|----------------------|
| PTC scripts run in-process (not sandboxed) | Developer-authored, version-controlled — trusted code | Sandboxing PTC scripts (overkill, latency for trusted code) |
| Two-layer sandbox: RestrictedPython AST + Job Object | Defense in depth — RestrictedPython blocks semantic access; Job Object enforces OS-level resource limits | RestrictedPython only (known bypasses); Job Object only (no semantic restriction) |
| `SandboxRunner` protocol with `JobObjectRunner` + `DirectRunner` | CI runs on Linux/Windows without Win32; DirectRunner skips Job Object in tests | `if sys.platform == 'win32'` branches (untestable, platform-coupled) |
| Prog Tool Calling fallback to PTCResult (not raw KB) | Premium model never sees raw chunks even on script failure | Fallback to raw KB chunks (violates QA2) |
| Router is pure stateless function | Trivial to test exhaustively; no hidden state | Class with injected config (unnecessary indirection) |

---

## 5. ADD Iteration 3 — Quiz Orchestration, Retrieval, TDD Architecture

**Goal:** Address FR1–FR5, QA3 (testability), QA4 (extensibility), QA5 (observability).

### Element Responsibility Table (Iteration 3)

| Element | Responsibility |
|---------|---------------|
| `engine/question.py` | `Question(type, text, correct_answer, kb_excerpt, source_file)`. Validated on construction. |
| `engine/chunker.py` | Splits markdown into chunks at H2/H3 boundaries. Accepts string — no file I/O in core logic. |
| `engine/indexer.py` | Incremental index build: mtime comparison, embed only changed files, atomic swap (temp dir → rename). Accepts injected `EmbedFn`. |
| `engine/retriever.py` | Loads index from injected `index_dir: Path`. Returns `List[Chunk]` sorted by cosine similarity. Raises `IndexNotFoundError` with instructions if missing. |
| `engine/scorer.py` | `fill_in`: difflib fuzzy match. `conceptual`/`code`: delegates to model eval result. Returns `Score(value, feedback, correct_answer)`. |
| `engine/session_log.py` | Accumulates `SessionLog`. Flushes to `log_dir/<session_id>.json` after each question. Each entry includes `retrieval_scores` for observability of retrieval quality. |
| `engine/quiz.py` | Orchestrates full session. All deps injected. Stateless between questions except accumulated log. |
| `cli/main.py` | Typer CLI. Reads config, constructs engine with real adapters, delegates to quiz/kb commands. |

### Dependency Injection Contract

**All components accept dependencies as constructor arguments. No module-level singletons.**

```python
# Pattern applied throughout
class ProgToolCalling:
    def __init__(self, model: ModelAdapter, sandbox: SandboxRunner): ...

class Retriever:
    def __init__(self, index_dir: Path): ...

class Indexer:
    def __init__(self, kb_dir: Path, index_dir: Path, embed_fn: EmbedFn): ...

class Quiz:
    def __init__(self, retriever, ptc, prog_tool, router, local, premium, scorer, log): ...
```

### Test Structure

```
tests/
  unit/                        # Fast, pure, no I/O
    test_router.py             # Decision table exhaustive coverage
    test_chunker.py            # Heading boundary detection
    test_scorer.py             # fill_in fuzzy + partial scores
    test_question.py           # Validation: empty fields, invalid types
    test_session_log.py        # JSON flush, crash survival (tmp_path)
    test_ptc.py                # Script selection, compression ratio
  integration/                 # Real I/O, real RestrictedPython, mock models
    test_sandbox.py            # Safe pass; os/subprocess/file blocked
    test_prog_tool_calling.py  # MockAdapter + DirectRunner
    test_retriever.py          # Tiny real index in tmp_path
    test_indexer.py            # Incremental build, mtime, atomic swap
    test_adapters.py           # Mock HTTP (local) + mock SDK (premium)
    test_quiz.py               # Full pipeline, all mocks
  e2e/
    test_cli.py                # Typer CliRunner, mock engine
```

### TDD Build Order

| Order | Module | Rationale |
|-------|--------|-----------|
| 1 | `question.py` | Shared data types — no deps |
| 2 | `router.py` | Pure function — fastest TDD cycle |
| 3 | `chunker.py` | Pure string function |
| 4 | `scorer.py` | Needs question.py + MockAdapter |
| 5 | `session_log.py` | Filesystem only (tmp_path) |
| 6 | `ptc_scripts/` + `ptc.py` | Scripts are pure; ptc.py orchestrates |
| 7 | `sandbox.py` | RestrictedPython + Job Object |
| 8 | `models/adapter.py` + adapters | Interface then implementations |
| 9 | `prog_tool_calling.py` | Depends on adapter + sandbox |
| 10 | `retriever.py` | Real index in tmp_path |
| 11 | `indexer.py` | Needs chunker + embed_fn + retriever |
| 12 | `quiz.py` | Full pipeline — all deps available |
| 13 | `cli/main.py` | Typer CLI — wraps everything |

### Design Decisions (Iteration 3)

| Decision | Rationale | Discarded Alternatives |
|----------|-----------|----------------------|
| `EmbedFn = Callable[[str], list[float]]` injected into indexer | Swap real model for `lambda s: [0.0]*N` in CI — no model download, dimension-agnostic | Import sentence-transformers directly (slow CI, dimension-locked) |
| `httpx.Client` injected into local_adapter | `httpx.MockTransport` — no Ollama in tests | `requests` + `responses` (extra dep) |
| `anthropic.Anthropic` injected into premium_adapter | SDK supports httpx client injection | `unittest.mock.patch` at import (fragile) |
| Per-question log flush | Crash resilience — partial data better than none | Single flush at session end (all lost on crash) |
| `fill_in` scored locally via difflib | Zero premium cost for simple scoring | Local model scoring (slower, overkill) |
| Typer for CLI | Auto-generates `--help`, type-safe, clean subcommand tree | argparse (verbose boilerplate) |
| Atomic index: write to `kb_index.tmp/` then rename | Interrupted rebuild leaves old index intact | In-place write (partial write = corrupt index) |

---

## 6. ATAM Analysis

### Utility Tree

```
Utility
├── Modifiability
│   └── Model swappability
│       └── Dev swaps local model via config.yaml, no code change   (H, M)
│
├── Performance / Token Efficiency
│   └── PTC compression before all model calls
│       └── ≥40% token reduction vs raw KB chunks per session       (H, H)
│   └── Programmable Tool Calling compression
│       └── Model script further compresses PTC output              (H, H)
│
├── Testability
│   └── CI without live services
│       └── Full pipeline in CI: zero live API calls                (H, L)
│   └── Component isolation
│       └── Every module independently testable via DI              (H, L)
│
├── Extensibility
│   └── Web UI addition
│       └── Phase 2 via new interface/ — engine/ untouched          (H, M)
│
├── Observability
│   └── Token cost visibility
│       └── Per-session JSON log: ratios, tokens, model used        (H, L)
│   └── Crash resilience
│       └── Per-question flush — partial session recoverable        (M, L)
│
└── Security
    └── Sandbox integrity
        └── Model scripts blocked from OS/filesystem/network
            via RestrictedPython AST + Job Object                   (H, H)
```

### Risks

| ID | Risk | QA Threatened | Mitigation |
|----|------|--------------|------------|
| R1 | RestrictedPython has known escape vectors (subclass chains) | Security | Job Object as second layer — belt and suspenders |
| R2 | New task type added without PTC script → silent uncompressed fallback | Performance | Startup validation: assert PTC script exists for every task type |
| R3 | Ollama silent quality degradation (not a crash) | Performance, Observability | Log response token count + latency; surface anomalies in session summary |
| R4 | Windows atomic rename of directory may fail if handles held | Modifiability | Write to `kb_index.tmp/`; use `os.replace()`; document limitation |
| R5 | `embedding_model` or `embedding_backend` changed without index rebuild — dimension mismatch or stale vectors | Correctness, Modifiability | Store `embedding_model` and `embedding_backend` in `manifest.json` at index build time; detect mismatch on startup and raise `IndexStaleError` with rebuild instructions |

### Non-Risks

| ID | Decision | Confirmed Good |
|----|----------|---------------|
| NR1 | `ModelAdapter` single-method interface | Trivially mockable; no SDK in router |
| NR2 | Router as pure stateless function | Exhaustively testable; zero I/O |
| NR3 | Per-question log flush | Resilience cost: one file write per question — acceptable |
| NR4 | DI throughout | Eliminates test coupling at root |
| NR5 | PTC scripts as separate files | Each independently testable; ptc.py requires no changes to add task types |

### Sensitivity Points

| ID | Decision | Sensitive To |
|----|----------|-------------|
| S1 | `min_score` retriever threshold | Too low → noisy chunks → poor questions. Too high → too few chunks. |
| S2 | `sandbox_timeout_sec` | Too short → excessive fallback. Too long → session blocked. |
| S3 | PTC `max_output_tokens` | Too low → over-compressed, loses context. Too high → token savings diminish. |
| S4 | `top_n` / `top_k` ratio | With ~150 total chunks, a 20:5 ratio gives limited diversity. Too small a pool → same chunks every session. Ratio must scale with KB size. |
| S5 | Embedding model domain fit | General-purpose embedders may not differentiate Windows kernel terminology (e.g., SSDT vs EPROCESS). Poor inter-chunk cosine variance → retrieval returns same cluster for all queries. Validate with a retrieval quality eval before release. |

### Tradeoff Points

| ID | Decision | QA Improved | QA Degraded |
|----|----------|-------------|-------------|
| T1 | Two-layer sandbox | Security ↑ | Performance ↓, Complexity ↑ |
| T2 | Ollama graceful degradation | Resource Efficiency ↑ | Observability ↓ (silent quality drop) |
| T3 | Per-question log flush | Observability ↑ | Performance ↓ (one write/question) |
| T4 | Local model for fill_in scoring | Resource Efficiency ↑ | Quality ↓ (nuanced scoring less accurate) |

### Risk Themes

| Theme | Risks | Business Goal Threatened |
|-------|-------|--------------------------|
| Silent quality degradation | R2, R3 | Poor quiz questions with no user-visible signal — undermines showcase value |
| Windows-specific fragility | R4 | Atomic index swap and Job Object are Win32-specific; M1 Mac needs `DirectRunner` |
| Index staleness | R5 | Embedding model change silently corrupts retrieval — all downstream quality degrades |
| Retrieval feedback loop gap | S4, S5 | No signal path from poor question quality back to retrieval tuning; bad questions reinforce user disengagement with no corrective mechanism. Mitigation: log `retrieval_scores` in `QuestionLog`; add retrieval eval before release. |

---

## 7. API Key Resolution

Priority order (first match wins):
1. `ANTHROPIC_API_KEY` environment variable
2. `api_key_file` path from `config.yaml` (resolved relative to project root if relative)

`Claude-Key.txt` is copied locally to the project root and gitignored — never committed. Default config points to the local copy:
```yaml
api_key_file: Claude-Key.txt
```

---

## 8. Supported Local Models (via Ollama)

### GPU (8–16 GB VRAM)

| Model | VRAM | Best for |
|-------|------|---------|
| `qwen2.5:14b` (Q4) | ~8.7 GB | Technical reasoning — recommended |
| `phi4:14b` (Q4) | ~8.5 GB | Structured output, JSON, scoring |
| `llama3.1:8b` (Q4) | ~4.7 GB | Fastest local tier, general fallback |

### CPU-only (no discrete GPU)

| Model | RAM | Best for |
|-------|-----|---------|
| `phi4-mini` (3.8B Q4) | ~3.5 GB | Reasoning, code — recommended |
| `llama3.2:3b` (Q4) | ~3.0 GB | General fallback |
| `gemma3:4b` (Q4) | ~4.0 GB | Document understanding |
| `qwen2.5-coder:7b` (Q4) | ~5.5 GB | Code-heavy KB topics |

### Embedding Models (Ollama)

| Model | Dims | Best for |
|-------|------|---------|
| `nomic-embed-text` | 768 | Strong semantic quality — recommended |
| `all-minilm` | 384 | Fast, lightweight |
| `qwen3-embedding` | 1024 | Highest quality |

---

## 9. Question Types

| Type | Generation | Evaluation | Scoring |
|------|-----------|-----------|---------|
| `conceptual` | Premium via Prog Tool Calling | Premium | 0.0 / 0.5 / 1.0 |
| `code` | Premium via Prog Tool Calling | Premium | 0.0 / 0.5 / 1.0 |
| `fill_in` | Local | Local (difflib) | 0.0 / 0.5 / 1.0 |

Code answers are submitted as multi-line text — evaluated but never executed.

---

## 10. Phase 2 Extension Point

Web UI added by implementing `interface/web/` using FastAPI. `engine/` has zero web
dependencies. CLI and web share the same engine through the same DI contracts.

```
cli/        # Phase 1 (exists) — Typer CLI calling engine directly
web/        # Phase 2 — FastAPI routes calling engine directly
```
