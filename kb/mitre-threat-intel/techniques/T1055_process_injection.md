---
technique_id: T1055
technique_name: Process Injection
tactic: [Defense Evasion, Privilege Escalation]
platform: Windows
severity: High
data_sources: [ETW-Process, ETW-Memory, ETW-File, ETWTI]
mitre_url: https://attack.mitre.org/techniques/T1055/
---

# T1055 — Process Injection

## Description (T1055)

T1055 Process Injection is a collection of techniques that cause malicious code to execute inside the virtual address space of a separate, often legitimate, process. The attacker gains the security context and apparent identity of the host process, which makes detection harder and can grant elevated privileges if the target process runs as a privileged account. The Windows process model enforces memory isolation between processes; injection techniques defeat this isolation by using legitimate Win32 and native API functions to write code into a remote process and trigger its execution. Because the injected code appears as activity originating from the host process, it can bypass process-level firewalls, audit rules keyed on process image name, and user-mode EDR hooks installed in the injecting process.

The key Windows mechanisms that enable injection are: the handle-based cross-process memory access model (requiring `PROCESS_VM_WRITE` and related access rights), the ability to create threads or queue APCs in remote processes, and the section-object / view-mapping subsystem that allows sharing memory regions across process boundaries.

---

## Windows Implementation Details (T1055)

T1055 exploits several Windows kernel subsystems. The EPROCESS structure tracks every process and its `VadRoot` field anchors the Virtual Address Descriptor (VAD) tree — an AVL-balanced tree where each node describes one contiguous virtual memory region. When injection writes a new executable region into a remote process, the kernel creates a new VAD node with `VadType = VadNone` (private anonymous allocation) and marks `PrivateMemory = 1`. This combination is the kernel-level signature of injected shellcode: image-backed code always uses `VadType = VadImageMap` with a backing file pointer, whereas VadNone regions have no `Subsection` pointer.

The Windows security model controls cross-process operations through the handle access mask. `OpenProcess` with `PROCESS_VM_WRITE | PROCESS_VM_OPERATION | PROCESS_CREATE_THREAD` is the canonical set of rights required for most injection variants. The object manager's `SeAccessCheck` enforces these rights against the target process's security descriptor at handle-open time, not at the time of each API call.

ETW kernel providers, particularly `Microsoft-Windows-Kernel-Process` and the Threat Intelligence provider (`Microsoft-Windows-Threat-Intelligence`, commonly abbreviated ETWTI), emit events at each stage of the injection lifecycle. ETWTI is the highest-fidelity source because it fires from kernel mode, bypassing user-mode interception.

---

## Observable Artifacts (T1055)

The following observable artifacts appear across injection sub-techniques:

- A new VAD node with `VadType = VadNone`, `PrivateMemory = 1`, and an executable protection flag (`PAGE_EXECUTE_READ` or `PAGE_EXECUTE_READWRITE`) in the target process's VAD tree. Image-legitimate code never appears as VadNone + executable without a corresponding `LDR_DATA_TABLE_ENTRY` in the Process Environment Block (PEB) loader list.
- An ETHREAD whose `Win32StartAddress` field points into a VadNone region rather than into a mapped image. `ZwQueryInformationThread(ThreadQuerySetWin32StartAddress)` can retrieve this value from user mode; EDR kernel callbacks receive it directly in the thread-create notification.
- An `OpenProcess` handle acquisition targeting a process the caller does not own, requesting memory-write and thread-creation access rights simultaneously.
- Cross-process `WriteProcessMemory` activity followed within a short time window by thread creation in the same target process.

---

## ETW / eBPF Telemetry Signals (T1055)

### Microsoft-Windows-Kernel-Process

This provider emits events that bracket the injection lifecycle at the process and thread level.

- **Event ID 1 (ProcessStart)** and **Event ID 5 (ThreadCreate)**: Event ID 5 fires whenever a new thread is created in any process. The event payload includes `ProcessId`, `ThreadId`, `StartAddress` (the kernel-recorded start address), and `Win32StartAddress`. When a thread is created via `CreateRemoteThread` targeting a foreign process, the `StartAddress` value reflects the shellcode's entry point. If that address falls outside any image-backed VAD in the target process, it is a strong injection indicator.
- **Image Load events (Event ID 5 or provider-specific)**: Absence of an Image Load event for a memory region that is executing code is itself a signal — it indicates code running from anonymous private memory.

### Microsoft-Windows-Threat-Intelligence (ETWTI)

ETWTI is a restricted provider (requires PPL `ANTIMALWARE_LIGHT` signer level to consume) that emits events from deep within the kernel memory manager and executive. It is the hardest telemetry source for attackers to suppress without kernel-mode code execution.

- **ALLOCVM_REMOTE**: Fires when a process allocates virtual memory in a different process via `NtAllocateVirtualMemory` with a process handle argument. Fields: `TargetPid`, `BaseAddress`, `RegionSize`, `AllocationType`, `Protect`. `Protect = PAGE_EXECUTE_READWRITE (0x40)` on initial alloc is a high-confidence indicator. The pattern `AllocationType = MEM_COMMIT | MEM_RESERVE` combined with `Protect = PAGE_EXECUTE_READWRITE` distinguishes injection staging from legitimate cross-process operations.
- **WRITEVM_REMOTE**: Fires on `NtWriteVirtualMemory` (the kernel backing of `WriteProcessMemory`) when the target process differs from the caller. Fields: `TargetPid`, `BaseAddress`, `BytesWritten`.
- **MAPVIEW_REMOTE**: Fires when a section view is mapped into a foreign process. Used by shared-memory injection and reflective variants that use `NtMapViewOfSection`.
- **QUEUEAPCTHREAD_REMOTE**: Fires when a thread APC is queued from a different process context. The `TargetPid` and `TargetTid` fields identify the thread receiving the APC.
- **SETTHREADCONTEXT_REMOTE**: Fires when `NtSetContextThread` is called against a thread in a different process. Required for thread context hijacking and some hollowing variants.

### Microsoft-Windows-Kernel-Registry

Indirectly relevant: some injection loaders read `HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Image File Execution Options` to locate targets or install debugger shims. Registry events on IFEO keys from unexpected processes can indicate loader reconnaissance.

---

## Evasion Variants (T1055)

- **RW → RX permission transition**: Attackers allocate with `PAGE_READWRITE`, write the payload, then call `VirtualProtect` / `NtProtectVirtualMemory` to transition to `PAGE_EXECUTE_READ`. This avoids the `PAGE_EXECUTE_READWRITE` flag on the ALLOCVM_REMOTE event, but ETWTI still emits a `PROTECTVM_REMOTE` event on the permission change.
- **Section-based injection (no WriteProcessMemory)**: Create a pagefile-backed section, map it RW into the attacker's space, write the payload, unmap, remap as RX into the target. This avoids WRITEVM_REMOTE but generates MAPVIEW_REMOTE.
- **Transacted section (process doppelganging)**: Covered in `T1055_013_process_doppelganging.md`.
- **Gargoyle / intermittent execution**: Timer-based technique that marks shellcode as non-executable while idle, flipping to executable only during brief execution windows, to defeat memory scanners. A VirtualProtect sequence with rapid RX → RW → RX transitions visible in ETWTI PROTECTVM events is the indicator.
- **Module stomping**: Instead of allocating new memory, overwrite the `.text` section of an existing mapped image. This keeps VadType as VadImageMap but causes a hash mismatch between the on-disk PE and the in-memory content.

---

## Detection Logic (T1055)

### High-Confidence Injection Sequence (T1055.003 — CreateRemoteThread)

```
OpenProcess(PROCESS_VM_WRITE | PROCESS_VM_OPERATION | PROCESS_CREATE_THREAD, target_pid)
  → VirtualAllocEx(target_handle, NULL, payload_size, MEM_COMMIT|MEM_RESERVE, PAGE_EXECUTE_READWRITE)
  → WriteProcessMemory(target_handle, allocated_base, shellcode, payload_size)
  → CreateRemoteThread(target_handle, NULL, 0, shellcode_entry, arg, 0, NULL)
```

When this exact sequence appears within a genome window (all four calls from the same PID against the same target PID), confidence for T1055.003 is **High (0.90+)**.

### Medium-Confidence Heuristic

A process that:
1. Acquires an `OpenProcess` handle to a process it did not create
2. Within 5 seconds, calls `VirtualAllocEx` or triggers ALLOCVM_REMOTE
3. Within 5 seconds, triggers WRITEVM_REMOTE to the same target

— but without an observable thread creation — should be scored as T1055 with **Medium (0.65)** confidence. The thread creation may use a less observable path (e.g., APC delivery to an existing alertable thread).

### VAD-Based Detection

Scan the target process's VAD tree at genome capture time:
- Any VAD node with `VadType = VadNone AND PrivateMemory = 1 AND Protection ∈ {PAGE_EXECUTE_READ, PAGE_EXECUTE_READWRITE, PAGE_EXECUTE_WRITECOPY}` and for which no corresponding `LDR_DATA_TABLE_ENTRY` exists in the PEB module list = **shellcode region** indicator, score T1055 at High.

---

## Sub-Techniques (T1055)

### T1055.001 — Reflective DLL Injection

T1055.001 Reflective DLL Injection avoids `LoadLibrary` by embedding a custom reflective loader stub within the DLL itself. The attacker writes the full PE (including headers) into a VadNone region, then calls the reflective loader entry point. The loader manually parses the PE headers, resolves imports against the target process's PEB module list, applies relocations, and transfers control to DllMain — all without any OS loader involvement.

Detection: The injected DLL appears as a VadNone executable region with no corresponding `LDR_DATA_TABLE_ENTRY`. The PE signature (`MZ` / `0x5A4D`) is typically present at the base of the allocation. ETWTI ALLOCVM_REMOTE and WRITEVM_REMOTE precede execution. The Image Load callback (`PsSetLoadImageNotifyRoutine`) does **not** fire for reflective loads, creating a discrepancy between executing modules and the OS's image-load event stream.

Genome sequence: `VirtualAllocEx(PAGE_EXECUTE_READWRITE)` → `WriteProcessMemory(full_PE_size_bytes)` → `CreateRemoteThread(reflective_loader_offset)`. The size of the WriteProcessMemory write matching a plausible PE size (> 4KB, aligned to section boundaries) raises confidence.

### T1055.003 — CreateRemoteThread Injection

T1055.003 is the canonical injection technique and uses the `CreateRemoteThread` API directly. The call chain — `OpenProcess` → `VirtualAllocEx` → `WriteProcessMemory` → `CreateRemoteThread` — is well-understood and generates telemetry from multiple providers simultaneously. This is the injection variant with the highest detection fidelity.

The kernel records the new thread's `Win32StartAddress` in the ETHREAD structure, and the `Microsoft-Windows-Kernel-Process` thread-create event (Event ID 5) exposes this value. When `Win32StartAddress` falls in a VadNone region of the target process, the combination is a definitive signal.

### T1055.004 — Asynchronous Procedure Call (APC) Injection

T1055.004 exploits the Windows APC delivery mechanism. Every thread maintains two APC queues: a kernel-mode APC queue (delivered unconditionally on the next kernel-to-user transition) and a user-mode APC queue (delivered only when the thread is in an alertable wait state, such as `SleepEx`, `WaitForSingleObjectEx`, or `MsgWaitForMultipleObjectsEx` with `bAlertable = TRUE`).

The `ETHREAD.ApcState` field contains the pending APC lists. APC injection via `QueueUserAPC` / `NtQueueApcThread` adds a function pointer plus optional argument to the user-mode APC queue. When the target thread enters an alertable wait, the Windows kernel drains the APC queue by calling each function in turn.

Detection: ETWTI QUEUEAPCTHREAD_REMOTE fires when a cross-process APC is enqueued. The `ApcRoutine` field in this event contains the function pointer — if it falls in a VadNone region, injection is indicated. The "Early Bird" variant queues an APC before the target thread's first alertable wait (while the thread is still in its initialization phase), allowing the APC to execute before any user-mode hooks are installed.

### T1055.012 — Process Hollowing

T1055.012 Process Hollowing creates a legitimate process in a suspended state, unmaps its original image, and replaces it with a malicious PE, then resumes the thread. The result is a process whose EPROCESS.ImageFileName and PEB.ImagePathName refer to a benign executable, but whose executing code is entirely attacker-controlled.

The hollowing sequence:
1. `CreateProcess(..., CREATE_SUSPENDED, ...)` — creates the victim process suspended.
2. `NtUnmapViewOfSection` (or `ZwUnmapViewOfSection`) — unmaps the original image from the victim's address space.
3. `VirtualAllocEx` — allocates a new region at the image's preferred base address (or at a new base if ASLR prevents that).
4. `WriteProcessMemory` — writes the malicious PE headers and sections.
5. `SetThreadContext` — updates the suspended thread's RIP/EIP to point to the malicious entry point, and potentially updates the PEB's `ImageBaseAddress` field.
6. `ResumeThread` — starts execution.

Detection: The `NtUnmapViewOfSection` call on a freshly-created process is a critical indicator — legitimate processes virtually never unmap their own image section at startup. ETWTI SETTHREADCONTEXT_REMOTE fires at step 5. The discrepancy between the process's nominal image path (from `EPROCESS.SeAuditProcessCreationInfo.ImageFileName`) and the actual VAD content (private committed memory at the image base address rather than a mapped image section) is the definitive VAD-level indicator. Private bytes at the image base of a process that was just created = strong hollowing signal.

---

## Related Techniques (T1055)

- T1055.013 (Process Doppelganging) — See `T1055_013_process_doppelganging.md`
- T1106 (Native API) — Injection typically uses native APIs (`NtAllocateVirtualMemory`, `NtWriteVirtualMemory`, `NtCreateThreadEx`) to bypass user-mode hooks
- T1134 (Access Token Manipulation) — Injecting into a high-privilege process is a common privilege escalation path
- T1027 (Obfuscation) — Injected payloads are often packed or encoded to defeat static analysis

---

## OCSF Mapping (T1055)

| OCSF Class | Class ID | Discriminating Fields | Technique Confidence |
|---|---|---|---|
| Process Activity | 1007 | `activity_id = 2 (Launch)`, `process.pid ≠ actor.process.pid`, `process.file.path` in VadNone region | T1055 Medium |
| Memory Activity (extension) | custom | `activity_id = Allocate`, `target_process.pid ≠ actor.process.pid`, `memory.protection = PAGE_EXECUTE_READWRITE` | T1055 High |
| Module Activity | 1008 | Absence of expected Image Load for executing address | T1055 High |
