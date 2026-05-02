# Process & Thread Internals — Structures, Lifecycle & Kernel Callbacks
> Domain: Windows process/thread model, EDR callback registration, injection detection
> Load when: Implementing process/thread notification callbacks, analysing injection techniques, designing process-creation vetting logic, or understanding EPROCESS/ETHREAD field semantics

## Purpose & Scope
Detailed reference for Windows process and thread internals from the kernel's perspective: EPROCESS and ETHREAD structure fields relevant to EDR, the full process-creation pipeline, all notification callback APIs with their parameter structures, process protection levels (PPL), and the key injection vectors visible from kernel callbacks.

## Key Concepts

**EPROCESS Key Fields**

| Field | Type | EDR Relevance |
|-------|------|---------------|
| `UniqueProcessId` | `HANDLE` | PID — use for correlation, not as pointer |
| `InheritedFromUniqueProcessId` | `HANDLE` | Parent PID — verify parent matches expected launcher |
| `ActiveProcessLinks` | `LIST_ENTRY` | DKOM target — validate with independent traversal |
| `VadRoot` | `RTL_AVL_TREE` | VAD tree root — scan for unbacked executable regions |
| `Token` | `EX_FAST_REF` | Access token — mask low 4 bits before deref: `token & ~0xF` |
| `ThreadListHead` | `LIST_ENTRY` | Enumerate threads for APC injection detection |
| `ImageFileName` | `UCHAR[15]` | Short name only (≤14 chars) — use `SeLocateProcessImageName` for full path |
| `Protection` | `PS_PROTECTION` | PPL level and signer type |
| `MitigationFlags` | `ULONG` | Process mitigation policies (DEP, CFG, ACG, CIG) |
| `Job` | `PEJOB` | Job object membership |
| `Peb` | `PPEB` | User-mode PEB pointer — readable for loaded module list |

**ETHREAD Key Fields**

| Field | Type | EDR Relevance |
|-------|------|---------------|
| `Cid.UniqueThread` | `HANDLE` | Thread ID |
| `StartAddress` | `PVOID` | Kernel-set start address |
| `Win32StartAddress` | `PVOID` | User-mode start — injected threads often show non-module address |
| `ApcState.ApcListHead` | `LIST_ENTRY[2]` | Pending APC queues (kernel/user) |
| `ApcState.UserApcPending` | `BOOLEAN` | User APC queued — injection indicator when combined with cross-process origin |
| `ImpersonationInfo` | `PPS_IMPERSONATION_INFO` | Thread impersonation token |
| `CrossThreadFlags` | `ULONG` | Includes `PS_CROSS_THREAD_FLAGS_IMPERSONATING` |

**Process Creation Pipeline (7 Stages)**
1. **Parameter validation** — `NtCreateUserProcess` validates image path, security descriptor, attributes.
2. **EPROCESS allocation** — `PspAllocateProcess`: allocate and zero-init EPROCESS; assign PID from handle table.
3. **Address space creation** — `MmCreateProcessAddressSpace`: allocate page tables, set CR3 value.
4. **PEB initialisation** — map `ntdll.dll`; create user-mode PEB with `ProcessParameters`.
5. **Executable mapping** — `MmMapViewOfSection` for the PE image; set `ImageBaseAddress` in PEB.
6. **Handle inheritance** — copy inheritable handles from parent's handle table.
7. **Callback notification + resume** — `PspCallProcessNotifyRoutines` fires all registered callbacks; first thread created and resumed.

EDR veto opportunity: callbacks registered with `PsSetCreateProcessNotifyRoutineEx2` receive `PS_CREATE_NOTIFY_INFO`; setting `NotifyInfo->CreationStatus = STATUS_ACCESS_DENIED` prevents process start.

**PsSetCreateProcessNotifyRoutineEx2**
```c
// Registration:
PsSetCreateProcessNotifyRoutineEx2(
    PsCreateProcessNotifySubsystems,   // fires for all subsystems including WSL
    MyProcessCallback,
    FALSE                               // FALSE = add; TRUE = remove
);

// Callback signature:
VOID MyProcessCallback(
    PEPROCESS Process,
    HANDLE    ProcessId,
    PPS_CREATE_NOTIFY_INFO CreateInfo  // NULL on termination
) {
    if (CreateInfo) {
        // Creation path
        PCUNICODE_STRING imagePath = CreateInfo->ImageFileName;
        PCUNICODE_STRING commandLine = CreateInfo->CommandLine;
        HANDLE parentPid = CreateInfo->ParentProcessId;
        // Veto:
        // CreateInfo->CreationStatus = STATUS_ACCESS_DENIED;
    }
    // Else: termination — CreateInfo is NULL
}
```

**PS_CREATE_NOTIFY_INFO Fields**

| Field | Notes |
|-------|-------|
| `ParentProcessId` | Not necessarily the creating process — check `CreatingThreadId` |
| `CreatingThreadId.UniqueProcess` | Actual creator process ID |
| `FileObject` | File object for the image — use `FltGetFileNameInformationUnsafe` for full path |
| `ImageFileName` | `UNICODE_STRING` pointer to full NT path |
| `CommandLine` | Full command line if available; may be NULL |
| `CreationStatus` | Write `STATUS_ACCESS_DENIED` to veto; read to check if blocked by another callback |

**PsSetCreateThreadNotifyRoutineEx**
```c
PsSetCreateThreadNotifyRoutineEx(
    PsCreateThreadNotifyNonSystem,  // fires for non-system threads only
    MyThreadCallback
);

VOID MyThreadCallback(HANDLE ProcessId, HANDLE ThreadId, BOOLEAN Create) {
    if (Create) {
        PETHREAD thread;
        if (NT_SUCCESS(PsLookupThreadByThreadId(ThreadId, &thread))) {
            PVOID startAddr = PsGetThreadWin32StartAddress(thread);
            // Check startAddr against loaded modules — unbacked = injection indicator
            ObDereferenceObject(thread);
        }
    }
}
```

**PsSetLoadImageNotifyRoutineEx**
```c
PsSetLoadImageNotifyRoutineEx(MyImageCallback, PS_IMAGE_NOTIFY_CONFLICTING_ARCHITECTURE);

VOID MyImageCallback(
    PUNICODE_STRING FullImageName,
    HANDLE          ProcessId,
    PIMAGE_INFO     ImageInfo
) {
    if (ImageInfo->SystemModeImage) return; // kernel driver — handle separately
    // ImageInfo->ImageBase: where mapped in process
    // ImageInfo->ImageSize
    // Check for PE anomalies, unsigned DLLs, reflective load patterns
    if (!ImageInfo->ImageSigningLevel /* SIGNATURE_LEVEL_UNSIGNED */) {
        // unsigned DLL loaded — log or block
    }
}
```

**Process Protection Levels (PPL)**

| Level | Signer | Examples |
|-------|--------|---------|
| PP (Full Protection) | WinSystem | System, Registry, MemCompression |
| PPL Antimalware | Antimalware | AV/EDR protected processes |
| PPL Windows | Windows | wininit, lsass (if configured) |
| PPL WindowsTcb | WindowsTcb | csrss, smss |

- A PPL process can only be opened by another process at equal or higher protection level.
- EDR kernel driver can still access PPL processes via kernel pointers — `PsLookupProcessByProcessId` returns `EPROCESS*` regardless of protection.
- `ObRegisterCallbacks` with `OB_OPERATION_HANDLE_CREATE` can enforce minimum access mask even for high-privilege callers.

**Injection Vectors Detectable from Kernel Callbacks**

| Technique | Detection Point | Signal |
|-----------|----------------|--------|
| Classic `CreateRemoteThread` | Thread notify callback | `Win32StartAddress` outside any loaded module |
| APC injection | `ETHREAD.ApcState.UserApcPending` + ETWti | Cross-process APC queue + no legitimate caller |
| Reflective DLL injection | Image load callback | `ImageInfo->ImageBase` not backed by a file object |
| Process hollowing | Image load + ETWti `EtwTiLogReadWriteVm` | Write to remote process after create-suspended |
| `NtQueueApcThreadEx2` (special user APC) | ETWti | Bypasses alertable-wait requirement |

## Heuristics & Design Rules
- Always use `PsCreateProcessNotifySubsystems` over legacy `PsSetCreateProcessNotifyRoutine` — it fires for WSL2 and all non-Win32 subsystems.
- Validate `ImageFileName` against the file object (`CreateInfo->FileObject`) — the string can be spoofed by manipulating the PEB; the file object cannot.
- Check `Win32StartAddress` for new threads — legitimate system threads start inside a known module; injected threads start in heap or anonymous regions.
- Correlate PPL level + command line + parent process before veto decisions — false positives in process-creation veto are non-recoverable.
- Register callbacks at PASSIVE_LEVEL during `DriverEntry`; never dynamically register/unregister from within a callback.

## Critical Warnings / Anti-Patterns
- Never dereference `EPROCESS.ActiveProcessLinks` as the sole list — DKOM rootkits unlink the entry; always cross-validate with `PsGetNextProcess`.
- Never hold a spinlock across `PsLookupProcessByProcessId` — the lookup may block.
- `CreateInfo->CommandLine` is NULL for processes launched via `NtCreateProcess` (non-`NtCreateUserProcess`) — handle NULL gracefully.
- Vetoing process creation in the notify callback has no effect after Stage 7 completes — the veto window closes at callback return.
- `ImageFileName` in `PS_CREATE_NOTIFY_INFO` uses kernel memory that is freed after the callback returns — copy to your own buffer if you need it asynchronously.

## Cross-References
- See also: `kernel-primitives-overview.md` — ETHREAD.ApcState fields and APC delivery mechanism
- See also: `windows-internals.md` — EPROCESS/ETHREAD structure overview and SSDT dispatch
- See also: `edr-architecture-guide.md` — EDR callback registration architecture and altitude assignment
- See also: `io-driver-overview.md` — ObRegisterCallbacks for handle access stripping
