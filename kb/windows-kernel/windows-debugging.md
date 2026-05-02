# Advanced Windows Debugging & System Reversing — Summary
> Source: `KnowledgeBase\windows-debugging\Advanced-Windows-Debugging-and-System-Reversing-A-Comprehensive-Guide-for-Kernel.md`
> Domain: WinDbg, DDM/LINQ, TTD, kernel forensics, memory corruption analysis, evasion technique detection
> Load when: Debugging kernel drivers or user-mode services, investigating malware/EDR bypasses, analyzing crashes or memory corruption, or writing WinDbg scripts

## Purpose & Scope
Comprehensive reference for Windows debugging at both kernel and user-mode levels. Covers
the WinDbg architecture, Debugger Data Model (DDM) with LINQ, Natvis visualizers, JavaScript
scripting, Time Travel Debugging (TTD) for deterministic malware analysis, kernel forensics for
EDR telemetry inspection, and memory corruption root-cause analysis.

## Key Concepts

**WinDbg Architecture**
- `dbgeng.dll` — core debugging engine (breakpoints, command parsing, symbol resolution).
- `dbghelp.dll` — symbol handler (PDB parsing, stack walking, type information).
- WinDbg Preview is the modern frontend; both user-mode and kernel-mode sessions supported.

**Kernel Debug Setup**
- KDNET: HOST runs WinDbg; TARGET VM configured via `bcdedit /dbgsettings net hostip:<IP> port:<N> key:<key>`.
- Named pipe: `bcdedit /dbgsettings serial port:1 baudrate:115200` + VM serial → named pipe.
- Symbol path: `.sympath srv*C:\Symbols*https://msdl.microsoft.com/download/symbols` then `.reload /f`.

**Debugger Data Model (DDM) — `dx` Command**
- Object model over all kernel/process state; supports LINQ queries inline in the debugger.
- Key LINQ operations: `Select`, `Where`, `OrderBy`, `Flatten`, `GroupBy`, `Any`, `Count`.
- Example — find processes with open handles to lsass:
  `dx @$cursession.Processes.Where(p => p.Name == "lsass.exe")`
- Example — enumerate thread call stacks for a suspicious process by PID:
  `dx @$cursession.Processes[<PID>].Threads.Select(t => t.Stack)`

**DKOM Detection**
- DKOM (Direct Kernel Object Manipulation): attackers unlink an EPROCESS node from `ActiveProcessLinks` to hide a process from standard enumeration.
- Detection: `Debugger.Utility.Collections.FromListEntry(*(nt!PsActiveProcessHead), "nt!_EPROCESS", "ActiveProcessLinks")` — walks the raw linked list, exposing unlinked entries that `!process` misses.
- `_EX_FAST_REF` masking: stored pointers have low 3 bits used as reference count. Apply `& 0xFFFFFFFFFFFFFFF8` before dereferencing to get the real object address.

**Kernel Callback Enumeration**
- `PspCreateProcessNotifyRoutine`: 64-entry array in kernel space. Iterate with `dx` to display all registered callback pointers; `_EX_FAST_REF` masking required. Zeroed entries indicate BYOVD callback stripping.
- WFP inspection: `netio!gWfpGlobal` — global WFP engine state; `WfpAleQueryEndpointSecurityInfo` enumerates active callout filters.
- ETWti: consumer must run as PPL ANTIMALWARE_LIGHT with ELAM certificate; emits `THREATINT_WRITEVM_REMOTE`, `EtwTiLogReadWriteVm`, `EtwTiLogSetContextThread`.

**Natvis — Custom Type Visualizers**
- XML files (`.natvis`) placed in `%USERPROFILE%\Documents\Visual Studio <ver>\Visualizers\` or `.nvload`ed in session.
- `<Type Name="MyStruct">` with `<DisplayString>` and `<Expand>` elements → clean object display in locals/watch.
- Supports template specializations: `<Type Name="Container&lt;*&gt;">`.
- Use for rendering EPROCESS, IRP stacks, ring buffer state, or any opaque kernel struct in human-readable form.

**WinDbg JavaScript Scripting (Chakra Engine)**
- Two modes: **Imperative** (`.scriptrun <file>`) — runs top-level code once, used for one-shot queries.
  **Extension** (`.scriptload <file>`) — registers functions into the debugger namespace for reuse.
- Access debugger object model via `host.namespace.Debugger`, `host.currentProcess`, `host.currentThread`.
- Output via `host.diagnostics.debugLog()`.
- Use case: automate DKOM detection, extract all registered callbacks, correlate thread stacks across processes.

**Time Travel Debugging (TTD)**
- Capture: `ttd.exe -out C:\traces <exe>` or WinDbg "Record" → produces `.run` trace file + `.idx` index file.
- Reverse execution commands: `g-` (reverse go), `t-` (reverse step into), `p-` (reverse step over).
- `!tt <position>` jumps to a specific position in the trace (e.g., `!tt 50%` for midpoint).
- TTD LINQ queries: `dx @$cursession.TTD.Calls("ntdll!NtWriteVirtualMemory")` — enumerate all calls to a function across the entire trace.

**Process Hollowing Analysis via TTD**
- Capture the hollow loader; search trace for `WriteProcessMemory` → `CreateRemoteThread` sequence.
- `dx @$cursession.TTD.Calls("kernel32!WriteProcessMemory")` to find all write events with target addresses.
- Reverse from the hollow shell's entry point back to the allocation site, confirming the payload source.
- Detects .NET-based and unmanaged hollowing regardless of packing or obfuscation.

**Evasion Technique Detection**
- **Direct syscalls**: KTRAP_FRAME captures RIP where `syscall` was executed. If RIP falls outside `ntdll.dll` / `win32u.dll` mapped range → flag as anomaly.
- **Indirect syscalls** (Halo's Gate, Tartarus' Gate): dynamically parse ntdll memory at runtime for clean `syscall; ret` stubs; SSN placed in EAX; jmp into ntdll. KTRAP_FRAME check bypassed — need ETWti for detection.
- **Call stack spoofing**: ROP/JOP gadgets overwrite return addresses with legitimate function pointers from trusted modules; forces stack walk to observe benign-looking chain. Counter: ETWti + VBS shadow stacks (KCET).
- **Hardware breakpoints via NtContinue**: `NtContinue` updates debug registers (Dr0–Dr7) without triggering `EtwTiLogSetContextThread`. Register VEH to catch debug exceptions and redirect execution. Counter: monitor NtContinue frequency; VBS shadow stacks.
- **Hook detection**: `!chkimg nt` compares in-memory kernel bytes against clean PDB symbols on disk. Highlights patched bytes, inline hooks, and JMP stubs inserted by rootkits or EDRs.

**PatchGuard (KPP)**
- Periodic checksum verification of SSDT, IDT, GDT, and other critical kernel structures.
- Detection triggers Bugcheck 0x109 `CRITICAL_STRUCTURE_CORRUPTION`. Arg4 specifies the corrupted region type (SSDT, generic data, etc.).
- Forces EDR vendors to use supported callbacks/ETWti instead of SSDT hooks.

**Pool Party — Thread Pool Injection**
- Manipulates `_TP_WORK` / `_TP_POOL` structures in the target process to queue malicious work items.
- Legitimate pre-existing worker thread executes the payload — no `CreateRemoteThread`, no `PsSetCreateThreadNotifyRoutine` trigger.
- Detection: use DDM to inspect thread pool worker factory structures for unauthorized function pointers.

**Memory Corruption Analysis**
- **Heap corruption**: enable PageHeap via GFlags → each allocation gets a guard page; overrun causes immediate exception at the offending instruction. `!heap` traverses segments, inspects block headers, shows allocation stack trace.
- **Stack corruption** (calling convention mismatch, async out-of-scope write): corrupted RBP makes call stack unreadable. Manual reconstruction: `d rsp` dumps raw stack memory; `ln <addr>` maps addresses back to function names.
- **Deadlocks**: `!locks` enumerates active critical sections and owning threads; orphaned sections show `LockCount` locked but `OwningThread` null/terminated. `!cs` gives spin count and debug info.
- **Resource leaks**: UMDH + LeakDiag capture allocation snapshots; diff reveals call stacks that allocated memory never freed. `!analyze -v` automates crash triage, cross-references signature against known issues.

## Heuristics & Design Rules
- Always configure symbols before any debugging session: `.sympath srv*C:\Symbols*https://msdl.microsoft.com/...` then `.reload /f`.
- Use `dx` + LINQ instead of legacy `!process` / `!thread` for any systematic enumeration — DDM is orders of magnitude more scriptable.
- For DKOM detection: always walk `ActiveProcessLinks` via `FromListEntry` independently from `!process` — DKOM hides entries from the latter only.
- Capture TTD traces for all intermittent bugs and injection scenarios — determinism eliminates Heisenbugs by replaying exact execution.
- Build Natvis visualizers for all major custom kernel structs during development, not retroactively.
- Validate KTRAP_FRAME RIP on every suspicious syscall telemetry event to distinguish direct syscalls from ntdll-originating ones.
- Use `!chkimg` at the start of malware investigations to detect if the sample has already patched kernel or ntdll bytes.

## Critical Warnings / Anti-Patterns
- Avoid using `!process` alone for process enumeration in malware investigations — DKOM hides entries; always cross-validate with `FromListEntry`.
- Avoid TTD on production systems or processes with real-time constraints — recording overhead is significant; use on test VMs.
- Avoid rebuilding call stacks manually without UMDH baseline snapshots — heap leak root-cause without baselines is guesswork.
- Avoid trusting ETWti alone for call stack spoofing detection — hardware shadow stacks (KCET) are required for robust coverage.
- Avoid `.scriptload` for one-shot queries — use `.scriptrun`; `.scriptload` persists in the namespace and can shadow built-in commands.

## Section Map
| Section | Key Topics |
|---------|-----------|
| Debugger Architecture | dbgeng/dbghelp, KDNET setup, PDB symbols |
| DDM & LINQ | `dx` queries, DKOM detection, callback enumeration |
| Natvis & JavaScript | Custom visualizers, Chakra scripting, automation |
| TTD | Capture, reverse execution, process hollowing case study |
| Kernel Callbacks & WFP | PspCreateProcessNotifyRoutine, WFP callouts, ETWti |
| Evasion Techniques | Direct/indirect syscalls, call stack spoofing, hardware BPs, BYOVD |
| PatchGuard & Pool Party | 0x109 bugcheck, thread pool injection detection |
| Memory Corruption | Heap/stack analysis, deadlocks, leak diagnosis |

## Cross-References
- See also: `windows-internals.md` — SSDT, EPROCESS/ETHREAD structures, VAD tree that WinDbg commands inspect
- See also: `edr-architecture-guide.md` — kernel callback registration that `PspCreateProcessNotifyRoutine` enumeration verifies
- See also: `edr-critical-thinking.md` — adversarial thinking for interpreting debugging findings
- See also: `io-driver-overview.md` — IRP and minifilter structures visible in WinDbg
