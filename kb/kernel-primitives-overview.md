# Windows Kernel Primitives — Object Manager, Dispatch Objects & Synchronization
> Domain: Windows kernel internals, synchronization, memory management
> Load when: Implementing kernel-mode drivers, designing EDR synchronization, understanding object lifecycle, debugging reference-count leaks or IRQL violations

## Purpose & Scope
Deep reference for the Windows kernel primitives layer: Object Manager internals, all kernel dispatcher objects and their IRQL constraints, synchronization primitives from spinlock through push lock, and pool allocation patterns. This is the foundation layer on which all higher EDR components (callbacks, minifilters, WFP callouts) are built.

## Key Concepts

**Object Manager Architecture**
- Every kernel resource is wrapped in an Object: fixed-size `OBJECT_HEADER` prefixed to a type-specific body.
- `OBJECT_HEADER` fields: `PointerCount` (kernel references via `ObReferenceObject`), `HandleCount` (user-space handle table entries), `TypeIndex` (index into `ObpObjectTypes` array), `SecurityDescriptor`, `NameInfoOffset`.
- `OBJECT_TYPE` defines per-type callbacks: `OpenProcedure`, `CloseProcedure`, `DeleteProcedure`, `ParseProcedure`, `SecurityProcedure`. EDR uses `OpenProcedure` interception via `ObRegisterCallbacks`.
- Reference counting rules: `ObReferenceObject` increments `PointerCount`; `ObDereferenceObject` decrements; when both counts reach 0 the `DeleteProcedure` fires. Mismatched ref/deref causes BSOD 0xC (`MAXIMUM_WAIT_OBJECTS_EXCEEDED`) or use-after-free.
- Named objects live in the Object Namespace (`\`). Lookup via `ObOpenObjectByName` / `ObReferenceObjectByName`. Anonymous objects have no name entry — referenced by handle only.
- Handle table: per-process `HANDLE_TABLE`; kernel global table at `ObpKernelHandleTable`. Handle value encodes table index + attributes (inherit, protect-from-close) in low bits.

**Kernel Dispatcher Objects**
All dispatcher objects share a `DISPATCHER_HEADER` as their first field — the kernel wait infrastructure operates on this header directly.

| Object | Type | Signal Condition | Key API |
|--------|------|-----------------|---------|
| `KEVENT` (Notification) | Manual-reset | Set until `KeClearEvent` | `KeSetEvent`, `KeClearEvent`, `KeWaitForSingleObject` |
| `KEVENT` (Synchronisation) | Auto-reset | Automatically cleared when one waiter released | `KeSetEvent` |
| `KMUTEX` | Mutex | Not owned | `KeWaitForMutexObject`, `KeReleaseMutex` |
| `KSEMAPHORE` | Semaphore | Count > 0 | `KeReleaseSemaphore`, `KeWaitForSingleObject` |
| `KTIMER` | Timer | Expiry reached | `KeSetTimer`, `KeSetTimerEx`, `KeCancelTimer` |
| `KQUEUE` | Queue | Item enqueued | `KeInsertQueue`, `KeRemoveQueue` (used by I/O completion) |

- `KeWaitForSingleObject` / `KeWaitForMultipleObjects`: valid at PASSIVE_LEVEL and APC_LEVEL only. Never call from DISPATCH_LEVEL or higher — immediate deadlock or BSOD 0xA.
- `WaitMode = KernelMode` vs `UserMode`: kernel-mode waits cannot be alerted or APCed by user mode; user-mode waits can be interrupted by APC delivery.

**Synchronization Primitives by IRQL**

| Primitive | Max Acquisition IRQL | Notes |
|-----------|---------------------|-------|
| `KMUTEX` (kernel mutex) | APC_LEVEL | Raises IRQL to APC_LEVEL; cannot be held across wait |
| `FAST_MUTEX` | APC_LEVEL | `ExAcquireFastMutex`; slightly faster than KMUTEX; no recursion |
| `ERESOURCE` | APC_LEVEL | Shared/exclusive; reader-writer; reentrant for exclusive holder |
| `KSPIN_LOCK` (spin lock) | DISPATCH_LEVEL | Raises IRQL to DISPATCH_LEVEL; hold < 25 µs; no paging |
| `EX_SPIN_LOCK` (queued) | DISPATCH_LEVEL | Fair — FIFO ordering; better cache behaviour on MP |
| `PushLock` | APC_LEVEL | Shared/exclusive; optimistic path avoids interlocked ops; non-reentrant |
| Interlocked ops | Any | `InterlockedIncrement`, `InterlockedCompareExchange` — no IRQL requirement |

- Spinlock rules: code holding a spinlock must not access pageable memory, call any function that might block, or raise IRQL further.
- `ERESOURCE` is the correct choice for reader-heavy workloads (e.g., a lookup table read by many callbacks, written occasionally): `ExAcquireResourceSharedLite` / `ExAcquireResourceExclusiveLite`.
- `PushLock` preferred for per-object locks in high-concurrency paths — lower overhead than ERESOURCE when contention is rare.

**Kernel Timer and DPC Pattern**
```c
KTIMER   g_Timer;
KDPC     g_Dpc;

// Init:
KeInitializeTimer(&g_Timer);
KeInitializeDpc(&g_Dpc, DpcRoutine, context);

// Arm (100ms periodic):
LARGE_INTEGER due = RtlConvertLongToLargeInteger(-100 * 10000); // 100ms in 100ns units
KeSetTimerEx(&g_Timer, due, 100 /*period ms*/, &g_Dpc);

// DPC fires at DISPATCH_LEVEL — no waits, no paging:
VOID DpcRoutine(PKDPC, PVOID ctx, PVOID, PVOID) {
    // fast path only; queue work item for heavy lifting
    IoQueueWorkItem(workItem, WorkItemRoutine, DelayedWorkQueue, ctx);
}
```

**Pool Allocation**

| Pool Type | Pageable | IRQL Constraint | Tag Example |
|-----------|----------|----------------|-------------|
| `PagedPool` | Yes | PASSIVE / APC only | `'rDEF'` |
| `NonPagedPool` | No | Any IRQL | `'rEDR'` |
| `NonPagedPoolNx` | No, NX | Any IRQL | `'xEDR'` (preferred — W^X) |
| `PagedPoolCacheAligned` | Yes | PASSIVE / APC | Rare; DMA buffers |

- Always tag allocations: `ExAllocatePool2(POOL_FLAG_NON_PAGED, size, 'rEDR')`. Tag visible in `!poolfind` and crash dump analysis.
- Lookaside lists (`ExInitializeLookasideListEx`) eliminate per-allocation overhead on hot paths — preallocate a free list of fixed-size blocks.
- Free with matching routine (`ExFreePoolWithTag`). Never free a pool allocation from a DPC if the allocation used `PagedPool`.

**APC (Asynchronous Procedure Call)**
- Kernel APC: queued to a thread's `ETHREAD.ApcState.ApcListHead[KernelMode]`; delivered at APC_LEVEL when thread is in alertable wait or exits a critical region.
- User APC: delivered when thread enters alertable wait (`SleepEx`, `WaitForSingleObjectEx` with `bAlertable=TRUE`); common injection vector — `QueueUserAPC` / `NtQueueApcThread`.
- EDR detection: monitor `ETHREAD.ApcState.UserApcPending` + cross-process `NtQueueApcThread` calls via ETWti.

## Heuristics & Design Rules
- Use `NonPagedPoolNx` for all new allocations — enforces W^X, required under HVCI.
- Hold spinlocks for microseconds only; push any non-trivial work to a work item or DPC-queued callback at PASSIVE_LEVEL.
- Use `ERESOURCE` for shared lookup tables; use `PushLock` for per-object locks accessed from callbacks.
- Always pair `ObReferenceObject` with `ObDereferenceObject` in all code paths — use RAII wrappers in C++ drivers.
- `ExAcquireFastMutex` is faster than `KeWaitForMutexObject` but cannot be used recursively — use `KMUTEX` if the lock may be re-acquired by the same thread.

## Critical Warnings / Anti-Patterns
- Never call `KeWaitForSingleObject` while holding a spinlock — BSOD 0xA (`IRQL_NOT_LESS_OR_EQUAL`).
- Never access paged memory from a DPC routine or spinlock-protected region.
- Avoid `ExAllocatePool` (deprecated) — use `ExAllocatePool2` which zero-initialises and supports flags.
- Never rely on `PointerCount == 0` to detect object deletion — `DeleteProcedure` fires asynchronously; use reference-counting discipline instead.
- APC injection via `NtQueueApcThread` into system threads can destabilise the kernel — validate thread APC acceptance before use in EDR response actions.

## Cross-References
- See also: `edr-design-reference.md` — IRQL-aware synchronization patterns in EDR driver code
- See also: `windows-internals.md` — Object Manager namespace, handle tables, EPROCESS/ETHREAD structures
- See also: `io-driver-overview.md` — IRP dispatch and pool allocation patterns for I/O drivers
- See also: `process-thread-overview.md` — APC injection via ETHREAD.ApcState and thread callback registration
