# ai-kb-quiz — Quiz Pipeline Implementation Plan
> Saved: 2026-04-25
> Baseline: 166 passed, 3 skipped
> Target: ~270 tests when complete (~104 new)

---

## Primary Design Requirements

1. **Mode flexibility** — works local-only, premium-only, or hybrid. Graceful degradation.
2. **Topic-based role profiles** — topic is embedded at quiz start; cosine similarity selects the best expert profile automatically. No CLI flag needed.
3. **Adaptive question selection** — epsilon-greedy policy uses past session scores to prioritize weak areas. Replaced by round-robin when no history exists.
4. **PTC security invariant** — raw KB text never reaches any model in any code path.

---

## Step 0 — Cross-Cutting Adapter Changes (Do First)

These modify existing files. All new modules depend on the updated interfaces.

### A. Add `system_prompt` to the adapter protocol

**`engine/models/adapter.py`**
- Add `system_prompt: str | None = None` to `ModelAdapter.generate()` Protocol
- Add `system_prompt: str | None = None` to `MockAdapter.generate()`
- Add `self.system_prompts: list[str | None] = []` to MockAdapter — parallel to `self.calls`, one entry per call. Existing tests reading `self.calls` are unbroken.

**`engine/models/local_adapter.py`**
- Add `system_prompt: str | None = None` to `generate()`
- When not None, include `"system": system_prompt` in the Ollama `/api/generate` JSON payload (natively supported)

**`engine/models/premium_adapter.py`**
- Add `system_prompt: str | None = None` to `generate()`
- When not None, pass as top-level `system=system_prompt` to `client.messages.create()`

### B. Add retry to `LocalAdapter`

**`engine/models/local_adapter.py`**
- Constructor: add `max_retries: int = 3`, `retry_delay_sec: float = 0.5`, `_sleep_fn = time.sleep`
- In `generate()`: retry up to `max_retries` on any exception with exponential backoff (`delay * 2**attempt`)
- After exhausting retries, return `""`
- Tests inject `_sleep_fn = lambda _: None` to avoid real sleeps

### C. Add retry to `PremiumAdapter`

**`engine/models/premium_adapter.py`**
- Constructor: add `max_retries: int = 3`, `retry_delay_sec: float = 1.0`, `_sleep_fn = time.sleep`
- Retry on: `anthropic.RateLimitError`, `anthropic.APITimeoutError`, `anthropic.InternalServerError`
- Do NOT retry on: `anthropic.AuthenticationError` (401), `anthropic.BadRequestError` (400) — raise immediately
- Re-raise last exception after exhausting retries

### New tests — extend `tests/integration/test_adapters.py`
- `test_mock_adapter_records_system_prompt`
- `test_mock_adapter_system_prompt_defaults_to_none`
- `test_mock_adapter_protocol_still_satisfied`
- `test_local_adapter_retries_on_connection_error` — mock raises twice then succeeds; 3 calls made
- `test_local_adapter_returns_empty_after_max_retries`
- `test_local_adapter_no_sleep_on_first_success`
- `test_local_adapter_exponential_backoff_delays` — sleep args: 0.5s, 1.0s
- `test_premium_adapter_retries_on_rate_limit`
- `test_premium_adapter_no_retry_on_auth_error` — raised immediately, no sleep
- `test_premium_adapter_reraises_after_max_retries`

---

## Task 1 — `engine/profiles.py`
**New module** | Depends on: `engine/embedder.py` (already built)

### Purpose
Automatically select an expert role profile based on topic similarity. The selected profile provides system prompts for question generation, answer evaluation, and PTC script context — no user input required.

### `RoleProfile` dataclass

```python
@dataclass
class RoleProfile:
    name: str
    description: str          # embedded for similarity matching
    question_prompts: dict[str, str]   # q_type → generation system prompt
    eval_prompt: str          # system prompt for answer evaluation
```

### Built-in profiles

| Profile | Description (used for embedding) | Triggers on topics like |
|---|---|---|
| `kernel_architect` | Windows kernel architecture, IRQL, memory manager, object manager, pool allocator, EPROCESS, KTHREAD | IRQL, memory, object manager, pool |
| `reverse_engineer` | Windows reverse engineering, EDR bypass, SSDT hooking, syscall, rootkit, kernel-mode malware | EDR, bypass, hooking, rootkit |
| `driver_engineer` | Windows driver development, minifilter, IRP, WDM, KMDF, device stack, filter callbacks | minifilter, IRP, driver, WDM |
| `debugger` | Windows kernel debugging, WinDbg, kd, crash dump analysis, breakpoints, symbols | WinDbg, debugging, !analyze, dump |
| `systems_programmer` | Windows system programming, eBPF, ETW, perf counters, tracing, kernel APIs | eBPF, ETW, tracing, perf |

Each profile's `question_prompts` keys: `"conceptual"`, `"code"`, `"fill_in"`.
Each has a distinct `eval_prompt` calibrated to the domain.

Example — `reverse_engineer`:
```python
question_prompts = {
    "conceptual": (
        "You are a Windows reverse engineer specializing in EDR bypass and "
        "kernel-mode exploitation. Create conceptual questions that test understanding "
        "of evasion mechanics, hooking techniques, and detection countermeasures."
    ),
    "code": (
        "You are a Windows reverse engineer. Create code questions involving "
        "syscall stubs, hook trampolines, or SSDT manipulation patterns."
    ),
    "fill_in": (
        "You are a Windows security researcher. Create fill-in-the-blank questions "
        "about specific API names, structure fields, and technique names."
    ),
}
eval_prompt = (
    "You are a senior Windows security researcher evaluating quiz answers. "
    "Judge technical accuracy of evasion techniques and kernel internals rigorously."
)
```

### `select_profile()` function

```python
def select_profile(topic: str, embed_fn) -> RoleProfile:
```

Algorithm:
1. Embed `topic` using `embed_fn(topic)`
2. For each profile in `PROFILES`, retrieve or compute `embed_fn(profile.description)` — **cached on first call** using a module-level dict keyed by profile name (computed once per process)
3. Compute cosine similarity between topic embedding and each profile embedding
4. Return the `RoleProfile` with highest similarity
5. Tie-break: return `"kernel_architect"` (the most general profile)

Cache structure:
```python
_PROFILE_EMBEDDINGS: dict[str, list[float]] = {}  # populated lazily, once per profile
```

### Module structure

```
engine/profiles.py
  """Topic-based role profile selection.
  Embeds the quiz topic and selects the closest expert role via cosine similarity.
  User story: cross-cutting — role profiles for question generation and evaluation.
  """
  @dataclass RoleProfile
  PROFILES: dict[str, RoleProfile]
  _PROFILE_EMBEDDINGS: dict[str, list[float]]
  def _cosine(a, b) -> float
  def select_profile(topic, embed_fn) -> RoleProfile
```

### Test file: `tests/unit/test_profiles.py` (write BEFORE implementing)

- `test_all_profiles_have_three_question_prompts` — each profile has conceptual/code/fill_in keys
- `test_all_profiles_have_eval_prompt`
- `test_select_profile_returns_role_profile` — mock embed_fn returning fixed vectors; assert returns RoleProfile
- `test_select_profile_picks_highest_similarity` — two profiles, mock embeddings where profile B is closer; assert B selected
- `test_select_profile_caches_profile_embeddings` — embed_fn called once per profile per process, not once per topic call
- `test_select_profile_tiebreak_returns_kernel_architect`
- `test_select_profile_kernel_topic` — topic="IRQL scheduling" with real embed_fn (skip if no Ollama); assert kernel_architect
- `test_select_profile_edr_topic` — topic="EDR bypass SSDT"; assert reverse_engineer

---

## Task 2 — `engine/scorer.py`
**Story 6.1** | Depends on: `question.py`, `ModelAdapter`

### Functions

```python
score_fill_in(user_answer: str, correct_answer: str) -> Score
```
- `difflib.SequenceMatcher(None, user.lower().strip(), correct.lower().strip()).ratio()`
- ratio >= 0.9 → `Score(1.0, "Correct", correct_answer)`
- ratio >= 0.6 → `Score(0.5, "Partially correct", correct_answer)`
- else → `Score(0.0, "Incorrect", correct_answer)`

```python
score_from_model_eval(question: Question, user_answer: str,
                      adapter: ModelAdapter,
                      system_prompt: str | None = None) -> Score
```
- Builds eval prompt containing `question.text`, `question.correct_answer`, `user_answer`
- Calls `adapter.generate(prompt, system_prompt=system_prompt)`
- Parses response as JSON: `{"score": float, "feedback": str}`
- Parse failure or invalid score → `Score(0.0, "Evaluation failed — could not parse model response", question.correct_answer)`

```python
score(question: Question, user_answer: str,
      adapter: ModelAdapter,
      system_prompt: str | None = None) -> Score
```
- Dispatcher: `question.type == "fill_in"` → `score_fill_in`; else → `score_from_model_eval`

### Test file: `tests/unit/test_scorer.py` (write BEFORE implementing)

fill_in (6 tests):
- exact match → 1.0, case-insensitive → 1.0, close match → 0.5, wrong → 0.0, empty → 0.0, whitespace stripped → 1.0

model eval (8 tests):
- parses 1.0 / 0.5 / 0.0, bad JSON → failure score, prompt contains question/correct/user text, system_prompt passed to adapter

dispatcher (3 tests):
- fill_in → difflib (no adapter call), conceptual → model eval, code → model eval

---

## Task 3 — `engine/session_log.py`
**Stories 6.1, 6.3, 4.1** | Depends on: `question.py`, stdlib only

### Class

```python
class SessionLog:
    def __init__(self, session_id: str, log_dir: Path, mode: str)
    # session_id="" → auto-generate "session_YYYYMMDD_HHMMSS"
    # creates log_dir if absent

    def record(self, entry: QuestionLog) -> None
    # appends to internal list + flushes full list to disk immediately

    @property
    def entries(self) -> list[QuestionLog]  # returns a copy

    def summary(self) -> dict
    # keys: total_questions, total_score, max_score, percentage,
    #        avg_compression_ratio, total_tokens_local, total_tokens_premium,
    #        mode, session_id
```

### JSON file format

```json
{
  "session_id": "session_20260425_143000",
  "mode": "hybrid",
  "entries": [ { ...QuestionLog fields via dataclasses.asdict()... } ]
}
```
File path: `{log_dir}/{session_id}.json`

### Module-level functions

```python
def load_seen_questions(log_dir: Path) -> set[str]
```
Reads all `*.json` session files; returns deduplicated set of all `question_text` values.
Returns empty set if dir absent or no files. Skips/logs corrupt JSON.

```python
def load_score_history(log_dir: Path) -> dict[tuple[str, str], list[float]]
```
Reads all `*.json` session files; returns `{(source_file, question_type): [scores...]}`.
Used by `WeakAreaPolicy` to determine which topic+type combinations need more practice.
Returns empty dict if dir absent or no files.

### Test file: `tests/unit/test_session_log.py` (write BEFORE implementing)

- `test_creates_log_dir`
- `test_record_flushes_json_immediately`
- `test_record_accumulates_entries`
- `test_file_named_by_session_id`
- `test_summary_score_calculation` — scores 1.0/0.5/0.0 → total 1.5, percentage 50.0
- `test_summary_compression_ratio_average`
- `test_summary_token_totals`
- `test_entries_returns_copy`
- `test_auto_session_id_starts_with_session_`
- `test_load_seen_empty_dir` → empty set
- `test_load_seen_nonexistent_dir` → empty set
- `test_load_seen_reads_question_texts`
- `test_load_seen_deduplicates`
- `test_load_seen_survives_corrupt_file`
- `test_load_score_history_empty_dir` → empty dict
- `test_load_score_history_groups_by_source_and_type`
- `test_load_score_history_accumulates_across_sessions`
- `test_load_score_history_survives_corrupt_file`

---

## Task 4 — `engine/sandbox.py`
**Stories 4.2, 4.3** | Depends on: stdlib, RestrictedPython, win32 on Windows

### Types

```python
@dataclass ValidationResult:
    ok: bool
    reason: str

@dataclass ExecutionResult:
    ok: bool
    output: str
    error: str

class SandboxRunner(Protocol):
    def validate(self, script: str) -> ValidationResult: ...
    def run(self, script: str, stdin_data: str, timeout_sec: int) -> ExecutionResult: ...
```

### Forbidden patterns (AST walk before RestrictedPython)

- Imports: `os`, `subprocess`, `sys`, `socket`, `urllib`, `http`, `pathlib`, `shutil`, `ctypes`, `winreg`
- Calls: `open()`
- Attribute access: `__subclasses__`, `__bases__`, `__class__`

### `DirectRunner` (CI / non-Windows)

- `validate()`: AST walk with above rules
- `run()`: `subprocess.run(["python", "-c", script], input=stdin_data, capture_output=True, text=True, timeout=timeout_sec)`
  - Success → `ExecutionResult(ok=True, output=stdout, error="")`
  - `TimeoutExpired` → `ExecutionResult(ok=False, output="", error="Timeout")`
  - Other exception → `ExecutionResult(ok=False, output="", error=str(e))`

### `JobObjectRunner` (Windows production)

- Same AST validation as DirectRunner
- `run()`: defers `import win32api` inside method; falls back to DirectRunner on import failure
- Constructor params: `memory_limit_bytes: int = 256 * 1024 * 1024`, `cpu_time_limit_sec: int = 30`
- Win32 Job Object: create → associate subprocess → set quotas → wait → close handle (auto-kills children)
- Construction never fails on non-Windows (import deferred)

### Factory
```python
def make_sandbox() -> SandboxRunner:
    return JobObjectRunner() if sys.platform == "win32" else DirectRunner()
```

### Test file: `tests/integration/test_sandbox.py` (write BEFORE implementing)

Validation (8 tests): safe script passes; `import os/subprocess/sys/socket`, `open()`, `from os import`, `__subclasses__` each blocked

Execution (4 tests): executes safe script, timeout → failure, runtime error → failure, stdin passed through

Factory (1 test): `isinstance(make_sandbox(), SandboxRunner)`

---

## Task 5 — `engine/prog_tool_calling.py`
**Story 4.1** | Depends on: `question.py`, `ModelAdapter`, `sandbox.py`

### Class

```python
class ProgToolCalling:
    def __init__(self,
                 premium_adapter: ModelAdapter | None,
                 sandbox: SandboxRunner,
                 sandbox_timeout_sec: int = 10)

    def extract(self, ptc_result: PTCResult, task_type: str) -> ProgToolResult
```

### `extract()` decision tree

```
1. premium_adapter is None → return PTC fallback immediately (fallback_used=True)

2. script = premium_adapter.generate(
       _build_script_prompt(ptc_result, task_type),
       system_prompt=_SCRIPT_GEN_SYSTEM_PROMPT
   )

3. validation = sandbox.validate(script)
   → not ok: log reason, return PTC fallback

4. execution = sandbox.run(script, stdin_data=ptc_result.compressed_text, timeout_sec=...)
   → not ok: log error, return PTC fallback

5. return ProgToolResult(output_text=execution.output, script=script, fallback_used=False)
```

PTC invariant: `output_text` is always either `ptc_result.compressed_text` (fallback) or script stdout derived from it. Raw KB never appears.

### Test file: `tests/integration/test_prog_tool_calling.py` (write BEFORE implementing)

- `test_none_adapter_returns_fallback`
- `test_prompt_contains_compressed_text`
- `test_system_prompt_equals_constant`
- `test_valid_script_runs_sandbox` → `fallback_used=False`
- `test_invalid_script_triggers_fallback` → `"import os"` blocked
- `test_execution_failure_triggers_fallback`
- `test_output_is_script_stdout_on_success`
- `test_ptc_invariant_on_all_fallback_paths`

---

## Task 6 — `engine/quiz.py`
**Stories 6.1, 6.2** | Depends on: all previous modules

### Exceptions
```python
class EmptyKBError(Exception): ...
class QuestionGenerationError(Exception): ...
```

### Selection policies

```python
class SelectionPolicy(Protocol):
    def select(self,
               chunks: list[Chunk],
               q_types: list[str],
               history: dict[tuple[str, str], list[float]]) -> tuple[Chunk, str]
```

**`RoundRobinPolicy`**
- Cycles through `q_types` in order (deterministic)
- Cycles through `chunks` in retrieval order
- No history used
- Default when no session logs exist

**`WeakAreaPolicy`**
- Constructor: `epsilon: float = 0.2`
- For each `(chunk, q_type)` pair, compute `mean_score` from history (default 0.5 if unseen — neutral)
- Weights: `weight = 1.0 - mean_score` (score 0.0 → weight 1.0, score 1.0 → weight 0.0)
- With probability `epsilon`: pick uniformly at random (explore)
- Otherwise: weighted random selection (exploit weak areas)
- Effect: topics+types the user consistently gets wrong get selected more often

**Policy selection logic at `QuizSession.__init__()`:**
```python
# if history is non-empty → WeakAreaPolicy, else → RoundRobinPolicy
history = load_score_history(session_log.log_dir)
self._policy = WeakAreaPolicy() if history else RoundRobinPolicy()
```

### Profile selection at `QuizSession.__init__()`

```python
self._profile = select_profile(topic, embed_fn)
# logs: "Selected profile: reverse_engineer (similarity: 0.81)"
```

The `embed_fn` is injected as a constructor parameter (same pattern as `LearnSession`).

### Class

```python
class QuizSession:
    def __init__(self,
                 topic: str,
                 retriever,
                 embed_fn,                          # for profile selection
                 local_adapter: ModelAdapter | None,
                 premium_adapter: ModelAdapter | None,
                 mode: str,
                 prog_tool_calling: ProgToolCalling,
                 session_log: SessionLog,
                 question_types: list[str] | None = None,
                 top_k: int = 5,
                 _input_fn=input,
                 _output_fn=print)
```

**Construction validation:**
- Both adapters None → `ValueError("At least one adapter must be provided")`
- Invalid question type → `ValueError`
- `question_types=None` → default `["conceptual", "code", "fill_in"]`
- Profile selected via `select_profile(topic, embed_fn)` — stored as `self._profile`
- Policy selected based on `load_score_history(session_log.log_dir)`

### Adapter resolution

```python
def _resolve_adapter(self, routed: str) -> ModelAdapter:
```

| routed | local_adapter | premium_adapter | Returns | Note |
|---|---|---|---|---|
| "local" | available | any | local | Normal |
| "local" | None | available | premium | Degraded (warn once) |
| "premium" | any | available | premium | Normal |
| "premium" | available | None | local | Degraded (warn once) |

### `run()` flow

```python
def run(self, n_questions: int) -> list[QuestionLog]:
```

1. `chunks = retriever.search(topic, top_k=self.top_k)`
2. No chunks → raise `EmptyKBError`
3. Cap `n_questions = min(n_questions, len(chunks))` — log if capped
4. Load `history = load_score_history(session_log.log_dir)` — used by policy
5. Loop `n_questions` times: `(chunk, q_type) = self._policy.select(chunks, q_types, history)`
6. Call `_run_question(chunk, q_type, q_num)` → append to session_log → collect
7. Return list of QuestionLog entries

### `_run_question()` — the star DAG

```python
def _run_question(self, chunk: Chunk, q_type: str, q_num: int) -> QuestionLog:
```

1. `ptc = compress([chunk], "generate_question")`
2. `prog = self.prog_tool_calling.extract(ptc, "generate_question")`
3. `routed = route("generate_question", q_type, self.mode)`
4. `adapter = self._resolve_adapter(routed)`
5. `system_prompt = self._profile.question_prompts[q_type]`
6. `question = self._generate_question(adapter, prog.output_text, q_type, system_prompt)`
   - `QuestionGenerationError` → retry once; skip if still fails
7. `user_answer = self._prompt_user_answer(q_type, question)`
8. `score_routed = route("evaluate_answer", q_type, self.mode)`
9. `score_adapter = self._resolve_adapter(score_routed)`
10. `sc = score(question, user_answer, score_adapter, system_prompt=self._profile.eval_prompt)`
11. Display feedback via `_output_fn`
12. Return `QuestionLog(..., ptc_compression_ratio=ptc.compression_ratio)`

### Question generation JSON contract

Model must return:
```json
{"question": "...", "correct_answer": "...", "kb_excerpt": "..."}
```
Parse failure → `QuestionGenerationError`

Code questions: multi-line input loop via `_input_fn` until blank line.

### Test file: `tests/integration/test_quiz.py` (write BEFORE implementing)

**Construction:**
- `test_raises_when_both_adapters_none`
- `test_local_only_constructs`
- `test_premium_only_constructs`
- `test_profile_selected_at_construction` — mock embed_fn; assert `_profile` is a RoleProfile
- `test_round_robin_policy_when_no_history` — empty log_dir; assert `_policy` is RoundRobinPolicy
- `test_weak_area_policy_when_history_exists` — seed log_dir with session JSON; assert WeakAreaPolicy

**Adapter resolution (4 tests):** all four fallback scenarios

**Empty KB:** `test_run_raises_empty_kb_error`

**Question count:** capped at chunk count; exact count within limit

**Profile system prompts:**
- `test_profile_question_prompt_passed_to_adapter` — assert adapter.system_prompts[0] matches profile.question_prompts[q_type]
- `test_profile_eval_prompt_passed_to_scorer` — assert eval_prompt passed for conceptual/code questions

**Mode routing (6 tests):** local-only, premium-only, hybrid-both, hybrid-local-down, hybrid-premium-down, both-None

**WeakAreaPolicy behaviour:**
- `test_weak_area_policy_prefers_low_score_pairs` — history with (file_a, "conceptual") score=0.0; assert selected more often than (file_a, "fill_in") score=1.0 over 100 draws
- `test_weak_area_policy_explores_with_epsilon` — epsilon=1.0 (always explore); distribution is uniform

**PTC invariant:** raw chunk text not in any adapter.calls

**Logging:** run() returns QuestionLog list; score and compression_ratio populated

---

## Task 7 — `cli/main.py` additions
**Stories 6.1, 6.2, 6.3**

### Command signature

```python
@app.command("quiz")
def quiz_command(
    topic: str = typer.Argument(..., help="KB topic to quiz on"),
    questions: Optional[int] = typer.Option(None, "--questions",
                                            help="Number of questions (default: from config)"),
    types: str = typer.Option("", "--types",
                              help="Comma-separated: conceptual,code,fill_in"),
    debug: bool = typer.Option(False, "--debug"),
)
```

### Startup adapter detection

```python
# Attempt local adapter
local_adapter = None
try:
    local_adapter = LocalAdapter(model=cfg["local_model"])
except Exception:
    pass

# Attempt premium adapter
premium_adapter = None
try:
    premium_adapter = PremiumAdapter.from_config(
        model=cfg["premium_model"],
        api_key_file=Path(cfg.get("api_key_file", "Claude-Key.txt")),
    )
except EnvironmentError:
    pass

# Enforce mode constraints
mode = cfg["mode"]
if mode == "local" and local_adapter is None:
    typer.echo("Error: mode=local but Ollama is not reachable.")
    raise typer.Exit(1)
if mode == "premium" and premium_adapter is None:
    typer.echo("Error: mode=premium but no API key found. Set ANTHROPIC_API_KEY.")
    raise typer.Exit(1)
if local_adapter is None and premium_adapter is None:
    typer.echo("Error: No model available. Start Ollama or set ANTHROPIC_API_KEY.")
    raise typer.Exit(1)

# Hybrid degradation (warn, don't fail)
if mode == "hybrid":
    if local_adapter is None:
        typer.echo("Warning: local model unavailable — running in premium-only mode.")
        mode = "premium"
    elif premium_adapter is None:
        typer.echo("Warning: premium model unavailable — running in local-only mode.")
        mode = "local"
```

### Validation
- `questions` specified as < 1 → error "Question count must be at least 1" + Exit(1)
- `questions` > `cfg["quiz"]["max_questions"]` → cap silently, log
- `types` with invalid values → error listing valid types + Exit(1)
- Empty index → error "KB not indexed. Run: kb index" + Exit(1)

### Profile display at quiz start
```
Topic     : EDR bypass techniques
Profile   : reverse_engineer (Windows RE specialist — SSDT, syscall, rootkit)
Mode      : hybrid (local: phi4:14b | premium: claude-sonnet-4-6)
Questions : 5  [conceptual, code, fill_in]
Policy    : WeakAreaPolicy (ε=0.2) — prioritising weak areas from 3 prior sessions
──────────────────────────────────────────────────────
```

### Score summary display (story 6.3 exact format)
```
 #  | type        | topic excerpt        | correct | score
────|─────────────|──────────────────────|─────────|──────
 1  | conceptual  | SSDT hooking         | yes     | 1.0
 2  | code        | LIST_ENTRY walk      | partial | 0.5
 3  | fill_in     | ETW flags            | no      | 0.0

Final Score  : 1.5 / 3  (50%)
Token savings: 83% via PTC + Programmable Tool Calling
Profile used : reverse_engineer
Models used  : hybrid (local: phi4:14b | premium: claude-sonnet-4-6)
```
- correct column: 1.0 → "yes", 0.5 → "partial", 0.0 → "no"
- topic excerpt: first 20 chars of `question.text`

### New E2E tests — extend `tests/e2e/test_cli.py`
- `test_quiz_invalid_question_count`
- `test_quiz_no_index`
- `test_quiz_empty_topic_exits_cleanly`
- `test_quiz_premium_mode_no_key_fails`
- `test_quiz_type_filter_respected`
- `test_quiz_profile_shown_in_header`
- `test_quiz_policy_shown_in_header`
- `test_quiz_summary_table_shown`
- `test_quiz_final_score_in_output`
- `test_quiz_token_savings_in_output`
- `test_quiz_models_used_in_output`
- `test_quiz_profile_used_in_summary`

---

## Task 8 — `engine/mcp_server.py` + CLI `serve` command
**Depends on: all previous tasks (engine fully built)**

### Purpose
Expose the quiz engine as an MCP server. Any MCP client — Claude Code, Cursor, VS Code, a LangGraph orchestrator, or an A2A peer — can call KB retrieval, question generation, and scoring as standard tools. Works fully with local-only mode (Ollama): KB content never leaves the machine.

### MCP tools to expose

| Tool | Input | Output | Engine call |
|---|---|---|---|
| `kb_retrieve` | `topic: str, top_k: int = 5` | `[{text, heading, source_file}]` | `retriever.search()` |
| `kb_generate_question` | `topic: str, q_type: str, mode: str = "hybrid"` | `{question, correct_answer, kb_excerpt, profile_used}` | retrieve → PTC → profile → prog_tool_calling → model |
| `kb_score_answer` | `question_json: str, user_answer: str, mode: str = "hybrid"` | `{score, feedback, correct_answer}` | `score()` |
| `kb_run_question` | `topic: str, q_type: str, user_answer: str, mode: str = "hybrid"` | `{question, score, feedback, profile_used, token_savings}` | full single-question pipeline |
| `kb_list_topics` | `{}` | `[{source_file, chunk_count}]` | `manifest.load()` |
| `kb_session_summary` | `session_id: str` | `{total_score, percentage, entries: [...]}` | `session_log.summary()` |

### MCP resources

| URI | Content | Notes |
|---|---|---|
| `kb://topics` | List of indexed source files | Same data as `kb_list_topics` but as a browseable resource |
| `kb://profile/{topic}` | Which profile `select_profile(topic)` would choose | Lets a client preview role selection before starting a quiz |

### MCP prompts

| Name | Template | Use |
|---|---|---|
| `quiz_me` | `"Quiz me on {topic} with {n} {q_type} questions in {mode} mode."` | Shortcut for Claude Code users to start a session |

### Transport

- **stdio** — default. For Claude Code, VS Code, Cursor, JetBrains MCP plugins. Server is a child process; line-delimited JSON over stdin/stdout.
- **Streamable HTTP** — optional. Single endpoint accepting POST and GET (GET upgradeable to SSE for streaming). For remote access or A2A integration. Port configurable via `--port`.

### `engine/mcp_server.py` structure

```python
"""MCP server — exposes quiz engine tools, resources, and prompts.
User story: cross-cutting — MCP integration for Claude Code and A2A peers.
Thin wrapper only: no business logic here, all calls delegate to engine modules.
"""
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.server.streamable_http import streamable_http_server
from mcp.types import Tool, Resource, Prompt, TextContent

def make_server(
    retriever,
    embed_fn,
    local_adapter: ModelAdapter | None,
    premium_adapter: ModelAdapter | None,
    prog_tool_calling: ProgToolCalling,
    log_dir: Path,
) -> Server:
    server = Server("ai-kb-quiz")
    # register tools, resources, prompts via decorators
    return server

async def run_stdio(server: Server) -> None: ...
async def run_http(server: Server, port: int) -> None: ...
```

Key implementation notes:
- All tool handlers are `async def` (MCP SDK is async-first)
- Engine components are injected at `make_server()` time — no global state, no config file reads inside the server
- Each tool call creates its own `SessionLog` with a UUID session_id for stateless operation
- `kb_run_question` is the only stateful tool (creates a question, accepts an answer, scores it in one call — avoids round-trip state management)
- `mode` parameter on each tool call overrides config-level mode — lets the MCP client request local or premium per call

### CLI `serve` command

```python
@app.command("serve")
def serve_command(
    transport: str = typer.Option("stdio", "--transport",
                                  help="Transport: stdio or http"),
    port: int = typer.Option(8080, "--port",
                             help="Port for HTTP transport"),
    debug: bool = typer.Option(False, "--debug"),
)
```

Startup:
1. Load config, build adapters (same detection logic as `quiz_command`)
2. Build engine components (retriever, embed_fn, prog_tool_calling)
3. `server = make_server(...)`
4. `asyncio.run(run_stdio(server))` or `asyncio.run(run_http(server, port))`

### Claude Code integration (`.claude/settings.json`)

After `engine/mcp_server.py` is built, add to project settings so Claude Code can call the quiz engine as tools:

```json
{
  "mcpServers": {
    "ai-kb-quiz": {
      "command": "python",
      "args": ["-m", "cli.main", "serve", "--transport", "stdio"],
      "cwd": "C:/Code/ai-projects/ai-kb-quiz"
    }
  }
}
```

Claude Code then has access to `kb_retrieve`, `kb_generate_question`, `kb_score_answer`, etc. as native tools. With `mode=local`, phi4:14b runs all inference locally — no data leaves the machine.

### Local model note
MCP is model-agnostic. The server's tool handlers call `LocalAdapter` (Ollama) or `PremiumAdapter` (Claude) depending on the `mode` parameter. With `mode=local`:
- All `generate()` calls go to `http://localhost:11434/api/generate` (phi4:14b)
- Profile selection uses the local Ollama embedding model (nomic-embed-text)
- No cloud API keys required
- KB content stays on-device throughout

### Test file: `tests/integration/test_mcp_server.py` (write BEFORE implementing)

Use the `mcp` SDK's in-process test client — no network, no subprocess.

- `test_list_tools_returns_all_six_tools`
- `test_list_resources_returns_kb_topics_and_profile`
- `test_list_prompts_returns_quiz_me`
- `test_kb_retrieve_returns_chunks` — mock retriever returns 3 chunks; assert 3 dicts in output
- `test_kb_retrieve_empty_topic_returns_empty_list`
- `test_kb_generate_question_returns_required_keys` — mock adapters; assert `question/correct_answer/kb_excerpt/profile_used` in result
- `test_kb_generate_question_local_mode` — mode="local"; assert only local_adapter called
- `test_kb_generate_question_premium_mode` — mode="premium"; assert only premium_adapter called
- `test_kb_score_answer_fill_in_exact_match` — score=1.0
- `test_kb_score_answer_model_eval_conceptual` — mock adapter returns JSON score
- `test_kb_run_question_full_pipeline` — single tool call covers generate+score; assert all fields present
- `test_kb_list_topics_returns_source_files`
- `test_kb_session_summary_returns_dict`
- `test_resource_kb_topics_content`
- `test_resource_kb_profile_for_topic` — `kb://profile/EDR bypass` returns `reverse_engineer`
- `test_ptc_invariant_in_generate_question` — raw chunk text not in any adapter call

---

## Implementation Sequence

```
Step 0   Modify adapter.py, local_adapter.py, premium_adapter.py
         Extend tests/integration/test_adapters.py (~12 new tests)
         pytest → ~178 passed

Task 1   tests/unit/test_profiles.py     → RED
         engine/profiles.py              → GREEN (~8 new tests)
         pytest → ~186 passed

Task 2   tests/unit/test_scorer.py       → RED
         engine/scorer.py               → GREEN (~17 new tests)
         pytest → ~203 passed

Task 3   tests/unit/test_session_log.py  → RED
         engine/session_log.py          → GREEN (~18 new tests)
         pytest → ~221 passed

Task 4   tests/integration/test_sandbox.py  → RED
         engine/sandbox.py                  → GREEN (~13 new tests)
         pytest → ~234 passed

Task 5   tests/integration/test_prog_tool_calling.py  → RED
         engine/prog_tool_calling.py                   → GREEN (~8 new tests)
         pytest → ~242 passed

Task 6   tests/integration/test_quiz.py  → RED
         engine/quiz.py                  → GREEN (~22 new tests)
         pytest → ~264 passed

Task 7   Extend tests/e2e/test_cli.py    → RED
         Extend cli/main.py (quiz cmd)   → GREEN (~12 new tests)
         pytest → ~276 passed

Task 8   tests/integration/test_mcp_server.py  → RED
         engine/mcp_server.py                   → GREEN (~16 new tests)
         Extend cli/main.py (serve cmd)
         pytest → ~292 passed (all green)
```

---

## Mode-Flexibility Verification Matrix

All six scenarios must have test coverage in `test_quiz.py`:

| Scenario | local_adapter | premium_adapter | mode | Expected |
|---|---|---|---|---|
| local-only | MockAdapter | None | "local" | All tasks → local; profile still selected |
| premium-only | None | MockAdapter | "premium" | All tasks → premium |
| hybrid-both | MockAdapter | MockAdapter | "hybrid" | fill_in→local; conceptual/code→premium |
| hybrid-local-down | None | MockAdapter | "hybrid" | All degrade to premium; warning logged |
| hybrid-premium-down | MockAdapter | None | "hybrid" | All degrade to local; warning logged |
| both-None | None | None | any | ValueError at construction |

---

## Final File Map (New and Modified Files Only)

```
engine/
  profiles.py                       [NEW — Task 1]
  scorer.py                         [NEW — Task 2]
  session_log.py                    [NEW — Task 3]
  sandbox.py                        [NEW — Task 4]
  prog_tool_calling.py              [NEW — Task 5]
  quiz.py                           [NEW — Task 6]
  mcp_server.py                     [NEW — Task 8]
  models/
    adapter.py                      [MODIFIED — system_prompt param]
    local_adapter.py                [MODIFIED — system_prompt + retry]
    premium_adapter.py              [MODIFIED — system_prompt + retry]
cli/
  main.py                           [EXTENDED — quiz + serve commands]
tests/
  unit/
    test_profiles.py                [NEW]
    test_scorer.py                  [NEW]
    test_session_log.py             [NEW]
  integration/
    test_adapters.py                [EXTENDED]
    test_sandbox.py                 [NEW]
    test_prog_tool_calling.py       [NEW]
    test_quiz.py                    [NEW]
    test_mcp_server.py              [NEW]
  e2e/
    test_cli.py                     [EXTENDED]
```

### New dependency
```
mcp>=1.0.0    # Anthropic MCP SDK — add to requirements.txt
```

---

## Key Design Decisions

1. **Topic-based profile selection, not user-selected.** User types the topic naturally; cosine similarity picks the expert role automatically. Profile embeddings cached per process — computed once.

2. **Separate system prompts for generation vs evaluation.** `RoleProfile.question_prompts[q_type]` for generation; `RoleProfile.eval_prompt` for scoring. A reverse engineer generates differently than they evaluate.

3. **WeakAreaPolicy is epsilon-greedy, not pure greedy.** Pure greedy would endlessly drill the single weakest pair. Epsilon=0.2 ensures 20% exploration so new topic+type combinations get tried.

4. **`RoundRobinPolicy` when no history.** First quiz session has no data — fall back to deterministic round-robin. This is transparent: the CLI header says `Policy: RoundRobin (first session)`.

5. **`load_score_history` keyed by `(source_file, question_type)`.** Source file (e.g., `kb/edr_architecture.md`) is a stable identifier for a knowledge area. Combined with question type, this gives fine-grained weak-area detection without needing to track individual questions.

6. **`SelectionPolicy` receives `history` at call time, not construction.** The history can grow within a session (in-session learning). Each call to `policy.select()` gets the latest history snapshot.

7. **Profile displayed in quiz header and score summary.** User sees which expert role was selected and can verify it makes sense for their topic. No surprise "why am I getting EDR questions when I asked about memory manager."

8. **`_input_fn` / `_output_fn` injection in QuizSession.** Full test coverage without touching stdin/stdout. Pass scripted lambdas in tests.

9. **`ProgToolCalling` returns PTC fallback when `premium_adapter is None`.** In local-only mode: PTC compresses → prog_tool_calling returns fallback (compressed text) → local model generates question. Zero premium calls, PTC invariant holds.

10. **`JobObjectRunner` construction never fails on non-Windows.** `win32api` import deferred to `run()`. Safe to instantiate everywhere; `make_sandbox()` always returns `JobObjectRunner()` on Windows.

11. **MCP server is a thin wrapper — no business logic.** `engine/mcp_server.py` only wires tool names to existing engine function calls. All logic lives in `profiles.py`, `scorer.py`, `quiz.py`, etc. This means the MCP server gets all bug fixes and improvements to the engine for free.

12. **`kb_run_question` avoids round-trip state.** MCP is nominally stateless between tool calls. Rather than forcing the client to call `kb_generate_question`, store the result, then call `kb_score_answer`, the combined `kb_run_question` tool accepts question + answer in one call and returns score + feedback. Simpler for Claude Code to drive a full quiz turn.
