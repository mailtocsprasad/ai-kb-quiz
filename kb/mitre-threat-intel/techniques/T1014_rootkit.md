---
technique_id: T1014
technique_name: Rootkit
tactic: [Defense Evasion]
platform: Windows
severity: Critical
data_sources: [ETW-Process, ETWTI, eBPF]
mitre_url: https://attack.mitre.org/techniques/T1014/
---

# T1014 — Rootkit

## Description (T1014)

T1014 Rootkit covers techniques where adversaries use rootkits to hide the presence of programs, files, network connections, services, drivers, and other system components. On Windows, rootkits typically operate in kernel mode (Ring 0), where they can manipulate the kernel data structures that user-mode APIs rely on to enumerate system state. The most prevalent modern approach is Direct Kernel Object Manipulation (DKOM), which modifies in-memory kernel structures to selectively hide artifacts from enumeration calls without patching any code. DKOM requires kernel execution, which attackers obtain through BYOVD (T1068) or driver vulnerabilities.

---

## Windows Implementation Details (T1014)

### ActiveProcessLinks and DKOM

The kernel maintains all live processes in a doubly-linked circular list rooted at `PsActiveProcessHead` (a global variable in ntoskrnl.exe). Each EPROCESS contains an `ActiveProcessLinks` field of type `LIST_ENTRY`, with `Flink` pointing to the next EPROCESS's `ActiveProcessLinks` and `Blink` pointing to the previous one.

`NtQuerySystemInformation(SystemProcessInformation)` — the function underlying `EnumProcesses`, `GetSystemProcesses`, `tasklist`, and Process Explorer's process list — walks this doubly-linked list to enumerate all processes. When user-mode tools enumerate processes, they are walking this same list.

DKOM process hiding requires two pointer updates:
```c
// Remove target_eprocess from the active process list:
target_eprocess->ActiveProcessLinks.Blink->Flink = target_eprocess->ActiveProcessLinks.Flink;
target_eprocess->ActiveProcessLinks.Flink->Blink = target_eprocess->ActiveProcessLinks.Blink;
// The EPROCESS itself remains in memory; the process continues running.
// The process is now invisible to NtQuerySystemInformation.
```

After unlinking, the EPROCESS object still exists in kernel memory and the process continues to execute, receive CPU time, make network connections, and perform I/O. Only enumeration APIs that walk `ActiveProcessLinks` are blinded.

### PspCidTable — Handle-Based Process Hiding

Windows maintains a global handle table called `PspCidTable` that maps every live process ID (PID) and thread ID (TID) to the corresponding EPROCESS or ETHREAD pointer. This table is used by `OpenProcess(pid)` — when user mode requests a handle to a PID, the kernel looks up the PID in `PspCidTable` to find the EPROCESS.

If an attacker removes the PID entry from `PspCidTable`, then `OpenProcess(target_pid)` returns `ERROR_INVALID_PARAMETER`, and any API that resolves a PID to a kernel object fails. Combined with `ActiveProcessLinks` unlinking, this creates a doubly-hidden process: invisible to enumeration and inaccessible by PID.

Removing a `PspCidTable` entry requires kernel write access to a specialized handle table structure. The table is a three-level handle table (same structure as the per-process handle table) with entries referencing EPROCESS/ETHREAD pointers. Overwriting an entry with zero effectively removes the PID.

### Thread Hiding via ETHREAD Unlinking

Individual threads can be hidden by unlinking their `ETHREAD.Tcb.ThreadListEntry` from `KPROCESS.ThreadListHead`. After unlinking, the thread is invisible to `NtQuerySystemInformation(SystemProcessInformation)` thread enumeration and to `Thread32Next` API calls. The thread continues to execute, making this technique useful for hiding a persistence or command-and-control thread within a visible process.

---

## Observable Artifacts (T1014)

- **ETW gap**: `Microsoft-Windows-Kernel-Process` provider stops emitting process-create or process-terminate events for the hidden process entirely after the DKOM operation, yet ETWTI events (which reference PIDs captured at event-creation time, before the unlink) may still reference the hidden PID.
- **PID in eBPF events without matching ETW Process event**: Windows eBPF socket events (captured at network connection time) record the PID that owns the socket. If a PID appears in eBPF network events but has no corresponding ETW Kernel-Process EPROCESS record, the process has been DKOM-hidden from ETW enumeration but is still making network connections.
- **Discrepancy between pool allocation counts and enumerated processes**: Kernel memory analysis tools that scan for `POOL_TAG = 'Proc'` allocations can find EPROCESS objects that are not in the active process list.

---

## ETW / eBPF Telemetry Signals (T1014)

### Microsoft-Windows-Kernel-Process

- DKOM-hidden processes cause the Kernel-Process provider to emit no further events for that PID. If a PID was previously active and its process events abruptly stop while the system continues operating, this is anomalous.
- A process being hidden will not generate a Process Terminate (EventID 2) event — because the DKOM operation does not terminate the process, it only hides it. The absence of a clean ProcessCreate → ProcessTerminate lifecycle for a known PID is a secondary indicator.

### Windows eBPF Socket Events

- eBPF programs attached at the socket layer (`FWPM_LAYER_ALE_AUTH_CONNECT_V4`, `FWPM_LAYER_ALE_RECV_ACCEPT_V4`) capture the owning process's PID at the kernel level, independently of `ActiveProcessLinks`. This cross-reference is the primary detection mechanism for DKOM-hidden processes: a PID making network connections that does not appear in the ETW process list.
- **Detection Rule**: `eBPF.socket_event.pid NOT IN etw_kernel_process.active_pid_set` at any point in the genome = T1014 DKOM indicator, confidence **Critical (0.95)**.

### Microsoft-Windows-Threat-Intelligence (ETWTI)

- ETWTI events for ALLOCVM, WRITEVM, or MAPVIEW that reference a PID not in the ETW process list are a strong DKOM indicator.
- ETWTI kernel-mode events cannot be suppressed by `ActiveProcessLinks` manipulation because they fire at IRQLs above what DKOM can affect.

---

## Detection Logic (T1014)

### Primary DKOM Detection Rule

```
IF:
  pid P appears in eBPF network events (socket connect / accept)
  AND pid P is NOT present in etw_kernel_process.pid_set (no active process event)
  AND time_since_last_process_create_for_P > 0  [P was never seen created in this session]
THEN:
  technique = T1014 (DKOM), confidence = 0.92, severity = CRITICAL
```

### Callback Monitoring Cross-Validation

```
IF:
  T = current_time
  AND etw_kernel_process.event_rate(window=60s before T) > threshold_normal
  AND etw_kernel_process.event_rate(window=60s after T) ≈ 0
  AND etwti.event_rate(window=60s after T) > 0  [ETWTI still active]
THEN:
  technique = T1014 (callback removal) OR T1562.006, confidence = 0.88
```

### Thread Hiding Detection

```
IF:
  etwti.QUEUEAPCTHREAD_REMOTE.TargetTid NOT IN etw_kernel_process.active_thread_set(for_target_pid)
THEN:
  suspect hidden thread, investigate T1014 + T1055.004 combination
```

---

## DKOM vs. Other Hiding Techniques (T1014)

| Technique | What It Hides | Detection Residual |
|---|---|---|
| ActiveProcessLinks unlink | Process from NtQuerySystemInformation | eBPF PIDs, ETWTI PIDs, pool allocation scan |
| PspCidTable NULL | PID from OpenProcess resolution | eBPF PIDs, ETWTI (uses PID at event time) |
| ETHREAD list unlink | Thread from thread enumeration | ETWTI QUEUEAPCTHREAD with unmapped TID |
| IFEO debugger injection | N/A — launches new process | IFEO registry key modification event |
| File hiding (minifilter) | Files from directory enumeration | USN Journal still records changes |

---

## OCSF Mapping (T1014)

| OCSF Class | Class ID | Discriminating Fields | Technique Confidence |
|---|---|---|---|
| Network Activity | 4001 | `src_endpoint.pid NOT IN active_process_list` | T1014 Critical |
| Process Activity | 1007 | Process PID in ETWTI but absent from Kernel-Process list | T1014 High |
