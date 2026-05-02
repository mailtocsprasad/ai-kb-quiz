# Windows Debugging and EDR Internals: Technical Reference

A practical reference covering WinDbg mechanics, kernel telemetry, EDR internals,
evasion techniques, and memory analysis for kernel/user-mode and security engineering.

---

## 1. Windows Debugging Architecture

The Windows debugging stack centers on two core libraries:

- **dbgeng.dll** — the debugger engine. Exposes COM interfaces (`IDebugClient`,
  `IDebugControl`) for attaching to targets, controlling execution, reading/writing memory,
  and processing debug events. All debugger frontends — `cdb.exe`, `kd.exe`, `windbg.exe`,
  WinDbg Preview — share this same engine.
- **dbghelp.dll** — the symbol and stack library. Handles PDB loading, symbol resolution,
  stack walking, and minidump parsing.

Custom debugger extensions and automated analysis tools are built on top of these two
libraries. The COM interface model means any application can programmatically drive a debug
session the same way WinDbg does.

---

## 2. Kernel-Mode vs User-Mode Debugging

### User-Mode Debugging

Attaches to a single process. The debugger intercepts exceptions, breakpoints, and module
load events through the Windows Debug API. Runs with privileges at or slightly above the
target process.

Key tools:
- `cdb.exe` — console-based, low-level memory/thread inspection
- `ntsd.exe` — like cdb but spawns its own window; can attach to subsystem processes
  before the graphical subsystem initializes

### Kernel-Mode Debugging

Halts all CPUs on the target machine and provides global visibility: physical memory,
SSDT, IDT, PEBs across all sessions. Can redirect user-mode debuggers to synchronize
per-process sessions with system-wide activity (useful for non-interactive processes like
services and COM servers).

Key tools:
- `kd.exe` — character-based kernel debugger
- `windbg.exe` — graphical, supports source-level kernel driver debugging

### Setting Up a Kernel Debug Session

Configure the target's Boot Configuration Data using `bcdedit`:

```
bcdedit /debug on
bcdedit /dbgsettings net hostip:<host-ip> port:<port>
```

This produces an encryption key for KDNET — kernel debug traffic encapsulated over
standard network interfaces. For VMs, use a named pipe mapped to a virtual serial port
instead of KDNET.

Once connected, the host debugger breaks into the target and gains full kernel visibility.

---

## 3. Symbol Resolution

### PDB Files

Compilers and linkers emit Program Database (`.pdb`) files mapping raw addresses to
function names, variable boundaries, and FPO (Frame Pointer Omission) data. Without
correct symbols, call stacks fragment and structure layouts cannot be decoded.

### Public vs. Private Symbols

Microsoft's public symbol server (`https://msdl.microsoft.com/download/symbols`) provides
stripped PDBs for all Windows binaries: exported names and basic structure layouts, but no
source paths or local variable names. Private symbol servers hold full PDBs including all
debug information.

### Configuring the Symbol Path

```
.sympath srv*c:\symbols*https://msdl.microsoft.com/download/symbols
```

This caches downloaded symbols locally. Local caching accelerates subsequent sessions and
enables offline analysis.

### Source Servers

PDBs can embed version control metadata via source server indexing. The `cv2http.cmd`
utility rewrites the source server block inside a PDB to point at an HTTP or UNC path.
When a breakpoint is hit, the debugger fetches the exact source revision that matches the
compiled binary automatically.

---

## 4. Debugger Data Model (DDM) and LINQ

### Overview

The Debugger Data Model projects the entire debug target into a queryable, hierarchical
object namespace. The primary access point is the `dx` command. Processes, threads,
modules, handles, and devices all become typed objects traversable without manual pointer
arithmetic.

### LINQ Queries

The DDM implements LINQ with C#-style method syntax: `Select`, `Where`, `OrderBy`,
`Flatten`, `GroupBy`, `Take`. This turns memory inspection into structured database queries.

**Examples:**

```
// Top 5 processes by thread count
dx Debugger.Sessions.First().Processes
  .Select(p => new { Name = p.Name, TC = p.Threads.Count() })
  .OrderByDescending(p => p.TC).Take(5)

// Find a suspicious module by name
dx @$curprocess.Modules.Select(m => m.Name).Where(n => n.Contains("maldll"))

// Identify processes with ASLR disabled
dx @$cursession.Processes
  .Where(p => p.KernelObject.MitigationFlagsValues.HighEntropyASLREnabled == 0)

// Group PnP devices by driver name
dx Debugger.Sessions.First().Devices.DeviceTree
  .Flatten(n => n.Children)
  .GroupBy(n => n.PhysicalDeviceObject->Driver->DriverName.ToDisplayString())
```

### DKOM Detection

Rootkits hide processes by unlinking their `_EPROCESS` structure from the
`ActiveProcessLinks` doubly-linked list. The process disappears from task managers and
user-mode enumeration APIs, but must remain in the scheduler to run.

Use `Debugger.Utility.Collections.FromListEntry` to traverse the raw kernel list manually:

```
dx Debugger.Utility.Collections.FromListEntry(
    *(nt!PsActiveProcessHead), "nt!_EPROCESS", "ActiveProcessLinks")
```

Cross-referencing this traversal against handle tables and `PsActiveProcessHead`
exposes any `_EPROCESS` nodes that were unlinked by a rootkit.

---

## 5. Native Type Visualization (Natvis)

Natvis is an XML-based framework that tells the debugger how to display complex C++ types
in watch windows and the DDM, eliminating the need to read raw memory for deeply nested
templates and custom containers.

### Schema Structure

```xml
<AutoVisualizer>
  <Type Name="MyNamespace::MyType<*>">
    <DisplayString>{{ size={_size} }}</DisplayString>
    <Expand>
      <ArrayItems>
        <Size>_size</Size>
        <ValuePointer>_data</ValuePointer>
      </ArrayItems>
    </Expand>
  </Type>
</AutoVisualizer>
```

Key expansion nodes:
- `<ArrayItems>` — contiguous arrays (size + pointer)
- `<LinkedListItems>` — singly-linked lists
- `<TreeItems>` — tree structures (e.g., red-black trees)
- `<CustomListItems>` — arbitrary iteration with loop variables and conditionals

Because Natvis integrates with the DDM, custom visualizers become queryable objects
accessible via `dx` and LINQ, not just passive GUI decorations. EDR developers use this to
decode proprietary telemetry buffers and IPC packets during live debugging.

---

## 6. JavaScript Scripting

WinDbg embeds the Chakra JavaScript engine, giving scripts direct access to the DDM.

### Script Types

- **Imperative scripts** — execute linearly on invocation; used for automating repetitive
  tasks (step sequences, memory dumps, thread state queries).
- **Extension scripts** — define `initializeScript()` and `invokeScript()` entry points to
  permanently project custom properties, classes, and methods into
  `Debugger.State.Scripts`.

### Malware Analysis Pattern

Malicious scripts running in `wscript.exe` often use `eval()` or ActiveX objects to unpack
payloads dynamically. The analysis pattern:

1. Script a breakpoint on the target DLL load (e.g., `jscript.dll`, `shell32.dll`)
2. On hit, read function arguments from the stack or registers
3. Log the deobfuscated payload
4. Resume execution automatically

This bypasses multi-layer obfuscation without manual step-through for each stage.

---

## 7. Time Travel Debugging (TTD)

### How It Works

TTD records a complete execution trace of a user-mode process: every instruction, memory
write, exception, and register state. Output is a compressed trace file (`.run`) and an index
file (`.idx`). Loading the trace in WinDbg creates a fully deterministic replay environment.

### Navigation Commands

| Command | Effect |
|---------|--------|
| `g-` | Reverse go (run backward) |
| `t-` | Reverse step into |
| `p-` | Reverse step over |
| `!tt <position>` | Jump to a specific time position or step count |

### Process Hollowing Analysis

Classic .NET hollowing sequence:
1. Spawn a legitimate process suspended (`CREATE_SUSPENDED`)
2. Unmap its code with `NtUnmapViewOfSection`
3. Allocate new memory with `VirtualAllocEx`
4. Write the payload with `WriteProcessMemory`
5. Redirect execution with `SetThreadContext`, then resume

With TTD, the approach is:
1. Query the DDM for all exception events or API calls in the trace
2. Locate the address where the PE header (`MZ` signature) was written
3. Set a hardware memory access breakpoint (`ba`) on that address
4. Execute backward (`g-`) to find the exact routine that decrypted and injected the payload

TTD trace files are portable — teams can collaborate on a captured trace without
reproducing the original environment.

---

## 8. Kernel Telemetry and EDR Internals

### Kernel Callbacks

The kernel exposes notification routines that let registered drivers receive synchronous
alerts on critical events. Core callbacks used by EDR drivers:

| Callback | Trigger | EDR Use |
|----------|---------|---------|
| `PsSetCreateProcessNotifyRoutineEx` | Process create/terminate | Inspect `PS_CREATE_NOTIFY_INFO`: cmdline, PPID, image name; optionally block |
| `PsSetCreateThreadNotifyRoutine` | Thread create (local and remote) | Detect remote thread injection |
| `PsSetLoadImageNotifyRoutineEx` | DLL/image mapped into memory | Scan image, hook IAT before execution |
| `ObRegisterCallbacks` | Handle open/duplicate for process/thread/desktop | Strip `PROCESS_VM_WRITE` / `PROCESS_VM_OPERATION` from attacker handles |

### Enumerating Callback Arrays in WinDbg

The kernel stores process-creation callbacks in `PspCreateProcessNotifyRoutine`. Entries
are encoded as `_EX_FAST_REF` structures — mask the lower bits to get the real pointer:

```
dx -r1 ((void**[64])&nt!PspCreateProcessNotifyRoutine)
```

Or manually: `dqs nt!PspCreateProcessNotifyRoutine L40` and AND each value with
`0xFFFFFFFFFFFFFFF8` to strip the reference count bits.

BYOVD attackers exploit arbitrary kernel write vulnerabilities to null out these pointers,
silently blinding the EDR without terminating it.

### Windows Filtering Platform (WFP)

WFP operates below the Windows Firewall, allowing kernel drivers to perform deep packet
inspection, modify traffic, and block connections at multiple TCP/IP stack layers. Key concept:
WFP **callouts** are kernel functions registered with the Base Filtering Engine (BFE) to
apply custom inspection logic.

**Offensive use:** Attackers create WFP filters blocking outbound traffic to the EDR vendor's
cloud infrastructure. The local agent continues running but cannot forward telemetry or
receive updated threat intelligence.

**Defensive analysis:** Hunt for unauthorized callouts via `netio!gWfpGlobal`, the root
pointer to the registered callout array. Traverse the array, inspect layer identifiers, and
correlate back to the originating driver.

### ETW Threat Intelligence (ETWti)

ETW is the kernel's high-performance logging system. The **Threat Intelligence provider**
(ETWti) emits security-relevant events directly from kernel code, covering activities that
bypass user-mode hooks:

- Remote memory allocation (`THREATINT_WRITEVM_REMOTE`)
- APC injection
- Thread context manipulation
- Hardware debug register modification

**Access control:** Only processes with `PROTECTED_ANTIMALWARE_LIGHT` PPL level and
a valid ELAM certificate can consume ETWti feeds. The kernel emits events through inline
`EtwTiLog*` calls scattered throughout critical system APIs. ETWti is the primary telemetry
source for modern behavioral detection engines and therefore a primary target for advanced
evasion.

---

## 9. Evasion Techniques and Detection

### User-Mode Hook Architecture

Classic EDR DLL injection hooks APIs in `ntdll.dll` using trampoline patches (similar to
Detours): redirect function prologues through EDR inspection code before reaching the
kernel. Targets: `CreateRemoteThread`, `VirtualAlloc`, `LoadLibrary`, `NtWriteVirtualMemory`.

### Bypass Techniques

**1. Direct Syscalls**

Skip the hooked `ntdll.dll` wrapper entirely. Move the syscall number into `EAX`, execute
the `syscall` instruction. The call goes directly to the kernel with no user-mode inspection.

*Halo's Gate* variant: if the target syscall stub is hooked, parse adjacent unhooked stubs to
infer the correct syscall number from neighboring ordinal offsets.

**2. Module Unhooking**

Map a fresh copy of `ntdll.dll` directly from disk into the process using `NtOpenFile` /
`NtCreateSection` / `NtMapViewOfSection`. Overwrite the patched `.text` section in-place,
restoring the original bytes and removing the EDR's hooks from that process.

**3. Hardware Breakpoint Abuse via NtContinue**

Setting hardware debug registers (DR0–DR3) normally via `NtSetContextThread` triggers
ETWti. Instead, construct a `CONTEXT` record with the desired debug registers populated
and call `NtContinue` — which restores thread context after exceptions. `NtContinue` does
not trigger the same ETWti event, achieving stealthy control-flow hijacking.

**Detecting hooks in WinDbg:**

```
!chkimg -d ntdll
```

Compares the in-memory module against the on-disk binary, highlighting patched bytes and
trampoline jumps.

### Thread Pool Injection ("Pool Party")

Rather than creating a remote thread (which fires `PsSetCreateThreadNotifyRoutine`),
attackers hijack the target process's existing **User-Mode Thread Pool**:

1. Allocate memory in the target, write shellcode
2. Locate `_TP_POOL` and `_TP_WORK` structures in the target
3. Queue a malicious work item pointing at the shellcode into an existing worker factory

A legitimate pre-existing worker thread picks up and executes the payload. No new thread
is created, so the kernel callback is never fired.

**Detection:** Use the DDM to inspect thread pool internals of suspicious processes, looking
for unexpected function pointers in queued work items.

---

## 10. PatchGuard (Kernel Patch Protection)

PatchGuard runs periodically on 64-bit Windows, computing checksums of:
- SSDT (System Service Descriptor Table)
- IDT (Interrupt Descriptor Table)
- GDT (Global Descriptor Table)
- Key kernel code regions

If a rootkit or legacy AV driver patches the SSDT or places an inline kernel hook,
PatchGuard detects the mismatch and triggers **Bugcheck 0x109
(CRITICAL_STRUCTURE_CORRUPTION)**.

This forced EDR vendors to abandon SSDT hooking and adopt supported callback APIs.

**Analyzing a 0x109 bugcheck:**

```
.bugcheck
!analyze -v
```

The fourth bugcheck argument identifies the corruption type: `0` = generic data region,
`1` = SSDT, `2` = GDT, etc.

---

## 11. Memory Corruption Analysis

### Heap Corruption

The Windows Heap Manager uses a front-end Low Fragmentation Heap for small allocations
and a back-end allocator for large ones. Corruptions (buffer overruns, double-frees) overwrite
heap block metadata, but the access violation typically fires long after the original bug.

**Diagnosis with PageHeap:**

Enable via GFlags or AppVerifier:
```
gflags /p /enable myapp.exe /full
```

Each allocation gets its own memory page with an inaccessible guard page immediately
adjacent. An overrun hits the guard page at the exact offending instruction — no delayed
crash.

```
!heap -p -a <address>   ; inspect allocation + call stack
!heap -l                ; find leaked heap blocks
```

### Stack Corruption

Common cause: calling convention mismatch. If a DLL exports a function using `__cdecl`
(caller cleans stack) but the caller assumes `__stdcall` (callee cleans stack), the stack
pointer (`RSP`) is misaligned after the call. The `ret` instruction pops an invalid return address,
jumping to unmapped memory.

**In the debugger:** The call stack appears completely invalid — frame pointers don't resolve.
Manual reconstruction:

```
dqs rsp L40          ; dump raw stack memory
ln <candidate-addr>  ; map candidate values back to function names
```

Look for values within loaded module address ranges as candidate return addresses.

### Deadlocks and Orphaned Critical Sections

```
!locks          ; enumerate all active CRITICAL_SECTIONs and their owning threads
!cs -l          ; list all critical sections with lock counts and debug info
```

If a thread was terminated via `TerminateThread` while holding a lock:
- `LockCount` remains non-zero (locked)
- `OwningThread` is null or points to a terminated thread
- All threads waiting to enter it are permanently blocked

### Resource Leaks

Use UMDH (User-Mode Dump Heap) to snapshot allocation state:

```
umdh -pn:myapp.exe -f:snap1.txt
; ... wait and repro ...
umdh -pn:myapp.exe -f:snap2.txt
umdh snap1.txt snap2.txt -f:diff.txt
```

The diff shows call stacks for allocations that grew between snapshots.

```
!analyze -v     ; automated triage: identifies faulting thread, instruction, and known patterns
```

---

## 12. Quick Reference: Key WinDbg Commands

| Command | Purpose |
|---------|---------|
| `dx` | Query Debugger Data Model |
| `!analyze -v` | Automated crash triage |
| `!heap -p -a <addr>` | Inspect heap allocation and stack |
| `!locks` | List active critical sections |
| `!cs` | Critical section details |
| `!chkimg -d <module>` | Detect in-memory hooks vs. disk image |
| `dqs <addr> L<n>` | Dump quad-word symbols (e.g., callback arrays) |
| `ba r4 <addr>` | Hardware memory access breakpoint |
| `g-` / `t-` / `p-` | TTD reverse execution |
| `!tt <pos>` | TTD jump to position |
| `ln <addr>` | List nearest symbol to address |
| `.sympath` | Configure symbol paths |
| `lm` | List loaded modules |
| `!process 0 0` | Enumerate all processes (kernel mode) |

---

## 13. EDR Telemetry Summary

| Source | Coverage | Bypass Resistance |
|--------|----------|------------------|
| User-mode hooks (DLL injection) | API-level visibility | Low — direct syscalls, unhooking |
| `PsSetCreateProcessNotifyRoutineEx` | Process create/terminate | Medium — BYOVD can null pointers |
| `PsSetCreateThreadNotifyRoutine` | Thread creation | Medium — thread pool injection bypasses |
| `PsSetLoadImageNotifyRoutineEx` | DLL/image loads | Medium — manual mapping bypasses |
| `ObRegisterCallbacks` | Handle operations | Medium — kernel write can remove |
| ETWti | Memory ops, APC, context changes | High — requires kernel-level manipulation |
| WFP callouts | Network traffic | Medium — attacker can add blocking filters |
