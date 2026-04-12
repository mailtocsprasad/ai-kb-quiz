# AI-KD: AI-Augmented Kernel Debugging — Summary

> **Source:** `ai-kd\AI-KD-AI-Augmented-Kernel-Debugging-for-WinDbg.md`
> **Domain:** Agentic AI tooling for WinDbg crash dump analysis (Python + Claude API + pykd)
> **Load when:** Building or extending AI-KD; designing agentic debugging loops; integrating Claude API with kernel tooling

---

## Purpose & Scope

AI-KD is a WinDbg extension that embeds Claude as an agentic debugger for kernel crash dumps. It extracts crash context via `pykd`, sanitises sensitive memory data, and runs an interactive tool-calling loop with the Claude API to produce automated C++ root-cause analysis — without a human manually executing debugger commands.

Primary use case: EDR sensor driver (`EdrSensor.sys`) and other C++ kernel component failures (IRQL bugs, null pointer dereferences, pool corruptions).

---

## 4-Layer Architecture

| Layer | Name | Tech | Job |
|---|---|---|---|
| 1 | **The Probe** | `pykd` | Extract raw WinDbg output (`!analyze -v`, `k`) into staged JSON |
| 2 | **The Filter** | Python regex | Strip 64-bit hex addresses → `[HEX_ADDR]`, collapse whitespace |
| 3 | **The Brain** | Claude API | Agentic reasoning with `execute_windbg_action` tool |
| 4 | **The UI** | WinDbg console | Display AI theories, tool calls, final root-cause analysis |

Strict pipeline rule: **no data reaches the API without passing through Layer 2.**

---

## Key Design Pattern: Programmable Tool Calling

Instead of defining 50+ WinDbg command tools, AI-KD uses **one flexible tool**:

```json
{
  "name": "execute_windbg_action",
  "input_schema": {
    "command": "string  // exact WinDbg command, e.g. 'dt nt!_EPROCESS'",
    "reasoning": "string  // why this command is needed"
  }
}
```

**Why one tool:** Defining 50+ tools inflates the system prompt on every API call. A single dynamic router keeps context overhead minimal while giving Claude access to the full WinDbg command set.

**Loop logic:**
- `stop_reason == "tool_use"` → extract command, run via `pykd.dbgCommand()`, sanitise output, feed back as `tool_result`
- `stop_reason == "end_turn"` → extract text block, print final analysis

---

## Context Synthesiser (Layer 2)

```python
hex_pattern = r'\b(0x)?[0-9a-fA-F]{8,16}`?[0-9a-fA-F]{0,8}\b'
sanitised = re.sub(hex_pattern, "[HEX_ADDR]", raw_text)
sanitised = re.sub(r'\n\s*\n', '\n', sanitised)
```

**Effect:** Replaces addresses (`fffff801\`56781234`) with `[HEX_ADDR]`, collapses blank lines. Forces Claude to focus on function names and bugcheck codes (architectural signal) rather than transient memory values (noise).

---

## System Prompt Design (Layer 3)

Key directives in the system prompt:
1. **INITIAL ASSESSMENT** — analyse bugcheck, faulting IP, stack trace; form hypothesis
2. **GATHER CONTEXT** — never guess offsets; always call `execute_windbg_action` for `dt`/`!pool` lookups
3. **ITERATE** — evaluate results; call tool again if needed
4. **FINAL ANALYSIS** — output C++ logic flaw + remediation (RAII, IRQL management, synchronisation)

Persona constraint: "Never output generic steps like 'run sfc /scannow'. Focus strictly on kernel-level C++ architecture."

---

## Deployment Package Structure

```
ai_kd_extension/
├── __init__.py
├── main.py          # Entry: !py ai_kd_extension/main.py
├── probe.py         # Phase 1: pykd extraction
├── synthesiser.py   # Phase 2: sanitisation + JSON payload
├── agent.py         # Phase 3: Claude API + agentic loop
└── requirements.txt # pykd>=0.3.4.15, anthropic>=0.18.0
```

**API key:** Never hardcoded. Read from `os.environ.get("CLAUDE_API_KEY")`, set once via `setx CLAUDE_API_KEY "..."`.

---

## Heuristics & Design Rules

- **Sanitise before transmit** — Layer 2 is a mandatory gate, never optional
- **Single tool, dynamic commands** — keeps system prompt token cost flat regardless of WinDbg surface area
- **Feed errors back to Claude** — failed `pykd.dbgCommand()` calls return error text as `tool_result`; Claude self-corrects
- **Add max_iterations guard** — default 10 tool calls before forcing `end_turn`; prevents runaway API costs
- **IRQL awareness** — post-mortem dump analysis is safe; running commands inside live callbacks is not

---

## Known Gaps / Anti-Patterns

| Gap | Risk | Fix |
|---|---|---|
| No `max_iterations` limit | Infinite loop → unbounded API cost | Add counter in `execute_windbg_tool` |
| Hex regex too broad | Strips symbol names containing hex chars | Scope to `Arg1`/`Arg2` lines in `!analyze -v` |
| `windbg_tool` not in scope inside loop | `NameError` at runtime | Pass tool schema as parameter |
| No message history on first call | Multi-turn context lost | Initialise `message_history` before first API call |
| Model ID pinned to `claude-3-5-sonnet-20241022` | Outdated model | Update to `claude-sonnet-4-6` |

---

## Phase Completion Checklist

- [x] Phase 1: `probe.py` — `extract_crash_context()` drafted
- [x] Phase 2: `synthesiser.py` — `sanitise_windbg_output()` + `build_claude_payload()` drafted
- [x] Phase 3: `agent.py` — tool schema, query, loop drafted (bugs noted above)
- [ ] Integration: wire all phases in `main.py`
- [ ] Bug fixes: max_iterations, hex regex, scope, history
- [ ] Tests: unit tests for synthesiser; mock pykd for agent
- [ ] Deployment: package as `ai_kd_extension/` with README

---

## Cross-References

| Topic | KB |
|---|---|
| WinDbg commands, crash analysis, IRQL debugging | `summaries\windows-debugging.md` |
| EDR sensor driver architecture, process callbacks | `summaries\edr-architecture-guide.md` |
| C++ kernel patterns: RAII, IRQL sync, null checks | `summaries\edr-design-reference.md` |
| Agentic AI patterns, Blackboard, tool calling | `summaries\edr-enhancement.md` |
| Claude API tool use, SDK patterns | `claude-developer-platform` skill |
