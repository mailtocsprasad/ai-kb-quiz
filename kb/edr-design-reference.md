# C++ EDR Design Reference Guide — Summary
> Source: `KnowledgeBase\edr-design-reference\Advanced-C-Design-Patterns-and-Architectural-Reference-for-Endpoint-Detection-an.md`
> Domain: EDR design patterns, interface contracts, C++ kernel idioms, synchronization
> Load when: Implementing EDR features, defining component interfaces, reviewing C++ kernel code quality, or addressing synchronization/memory issues

## Purpose & Scope
Deep reference for applying SOLID principles, structural/behavioral design patterns, and modern
C++ resource management to EDR kernel and user-mode code. Covers IRQL-aware synchronization,
lock-free data structures, and telemetry pipeline architecture at the implementation level.

## Key Concepts

**C++ in the Kernel — Permitted Features**
- **No C++ exceptions**: Standard `throw`/`catch` prohibited — emit too-large exception tables and risk exploitable unwinding. Use NTSTATUS return codes throughout.
- **Monadic error handling**: `std::optional`, `std::variant`, `std::expected` (C++23) wrap NTSTATUS alongside returned objects. Enforces compile-time handling of failure paths.
- **Approved STL headers**: `<type_traits>`, `<concepts>`, `<span>`, `<string_view>` — no dynamic allocation, no exceptions. Safe for kernel use.
- **Forbidden features**: RTTI, standard exception handling, most allocator-heavy STL containers.

**SOLID Principles Applied to EDR**
- **SRP**: Separate telemetry collection, event filtering, memory management, and IPC into distinct classes. A process-callback class must not also serialize JSON.
- **OCP**: New detection rules or telemetry parsers added by implementing existing interfaces — never modifying the core kernel driver execution loops.
- **LSP**: Subclasses must honor IRQL and memory constraints of the base interface, not just the method signature. Violating hidden concurrency contracts causes kernel panics.
- **ISP**: Expose `IProcessMonitor`, `INetworkMonitor` separately — not a monolithic `ISystemMonitor`. Limits recompilation blast radius.
- **DIP**: High-level detection engine depends on abstract interfaces only, not on concrete ETW or callback implementations.

**Stairway Pattern (Fixes Entourage Anti-Pattern)**
- Entourage Anti-pattern: interface and implementation in the same module — clients transitively depend on low-level Windows APIs, destroying decoupling.
- Stairway Pattern: `Interface Module` (pure abstract, no OS deps) → `Implementation Module` (wraps ETW/WDF) → `Client Module` (depends on Interface only) → `Composition Root` (DriverEntry — sole wiring point).
- Allows swapping ETW-TI callbacks for a different collection mechanism without touching the detection engine.

**Structural Patterns — Telemetry Collection**
- **Proxy Pattern**: Hook trampoline intercepts syscall; validates args against threat signatures; delegates to original if benign. User-mode hooks are bypassable via direct syscalls — treat as supplementary, not primary.
- **Decorator Pattern**: Wraps syscall with pre/post telemetry capture without modifying kernel binaries. Appends timing and return-value context.
- **Adapter Pattern**: `EtwAdapter` and `CallbackAdapter` convert OS-specific raw structs to internal `TelemetryItem` format. Detection engine sees only clean, normalized objects.
- **Facade Pattern**: Wraps `OBJECT_ATTRIBUTES`/`UNICODE_STRING` initialization boilerplate behind a clean C++ API. Keeps detection logic readable and OS-version-agnostic.
- **Builder Pattern**: Ensures telemetry events are always fully constructed before dispatch — no partial/invalid packets reach the analysis engine.

**Resource Management at Ring 0**
- **RAII pattern**: Constructor acquires resource; destructor releases unconditionally. Eliminates complex `goto`-based cleanup chains in kernel code.
- **Two-stage initialization**: Constructor sets safe empty state; `Initialize()` method allocates and returns NTSTATUS. Avoids invalid state from failed construction.
- **Static factory + `std::expected`**: Returns fully initialized RAII object or failure code; forces callers to handle both paths at compile time.
- **Custom kernel deleters**: `std::unique_ptr` with a deleter wrapping `ExFreePoolWithTag`. Required — standard `delete` is incompatible with kernel pool allocation.
- **Slab allocators**: Pre-allocated memory slabs for objects created/destroyed thousands of times per second (telemetry structs). Eliminates runtime allocation overhead on the hot path.

**IRQL-Aware Synchronization**
- **Mutexes (KMUTEX / FAST_MUTEX)**: Suspend waiting threads; require context switch. PASSIVE_LEVEL only — using at DISPATCH_LEVEL crashes the kernel immediately.
- **Spinlocks (KSPIN_LOCK)**: Busy-wait; raise IRQL to DISPATCH_LEVEL. Required for data touched at or above DISPATCH_LEVEL. Must never be held > 25 microseconds.
- **Spinlock constraint**: No paged memory access while a spinlock is held — a page fault at DISPATCH_LEVEL causes `IRQL_NOT_LESS_OR_EQUAL` BSOD.
- **KLockGuard (RAII wrapper)**: Custom class acquires spinlock in constructor (saves IRQL), releases in destructor. Guarantees lock release on early return or validation failure.

**Lock-Free Ring Buffers**
- Fixed-size circular buffer allocated at driver init — zero runtime allocation on the hot path.
- Head index (producer) and tail index (consumer) manipulated via `std::atomic<size_t>` with acquire-release memory ordering (not sequential consistency — avoids full barrier overhead).
- SPSC (single producer/consumer) or MPSC patterns depending on callback concurrency.
- Bridges high-IRQL producers (kernel callbacks) with slower user-mode consumers without mutex contention or blocking.

## Heuristics & Design Rules
- Use NTSTATUS return codes everywhere; never use C++ exceptions in kernel code.
- Apply RAII to every kernel resource without exception — locks, pool memory, handles, IRPs.
- Implement the Stairway Pattern for every major subsystem; never colocate interface and implementation.
- Choose synchronization primitive based on IRQL: PASSIVE_LEVEL → mutex; DISPATCH_LEVEL+ → spinlock.
- Hold spinlocks for fewer than 25 microseconds. Never access pageable memory inside a spinlock.
- Wrap `KSPIN_LOCK` in a RAII `KLockGuard` — manual lock/unlock pairs will eventually be skipped on an error path.
- Use pre-allocated ring buffers for kernel-to-user-mode telemetry routing; avoid mutex-synchronized queues on high-frequency paths.
- Apply the Adapter pattern at every OS/telemetry boundary; detection logic should never see raw Windows structs.
- Use the Builder pattern for telemetry event construction; partial telemetry is worse than no telemetry.

## Synchronization Decision Matrix
| Situation | Primitive | Reason |
|-----------|-----------|--------|
| Shared list at PASSIVE_LEVEL, long hold | KMUTEX / FAST_MUTEX | Context-switch allowed; prevents CPU starvation |
| Shared counter at DISPATCH_LEVEL | KSPIN_LOCK | Only option — thread suspension is forbidden |
| Shared counter in DPC routine | KSPIN_LOCK | DPC runs at DISPATCH_LEVEL |
| Ring buffer head/tail indices (lock-free) | `std::atomic` acquire-release | No blocking needed; avoid full memory barrier cost |
| Reference-counted shared config object | `std::shared_ptr` + custom deleter | Thread-safe ref count; custom kernel pool deleter |
| Single-owner telemetry buffer | `std::unique_ptr` + custom deleter | Exclusive ownership; deterministic pool release |
| Guard any critical section | RAII KLockGuard | Prevents forgotten unlock on error paths |

## Implementation Checklist (per new component)
- [ ] Interface defined in a separate module from its implementation (Stairway Pattern)?
- [ ] All kernel resources wrapped in RAII objects?
- [ ] Error handling via NTSTATUS + `std::expected`, not exceptions?
- [ ] Synchronization primitive matched to IRQL (mutex only at PASSIVE, spinlock at DISPATCH+)?
- [ ] Spinlock hold time bounded under 25 µs? No pageable access inside?
- [ ] Telemetry data normalized via Adapter before reaching detection logic?
- [ ] Telemetry events fully constructed via Builder before dispatch?
- [ ] Dynamic allocations in hot path eliminated (slab allocator or pre-allocated ring buffer)?
- [ ] Template parameters constrained with C++20 Concepts at privilege boundaries?

## Critical Warnings / Anti-Patterns
- Avoid the Entourage Anti-pattern — interfaces and implementations in the same module destroy decoupling and expose the kernel to unnecessary attack surface.
- Avoid using mutexes at DISPATCH_LEVEL — this is an immediate, non-recoverable kernel crash.
- Avoid holding spinlocks for long operations (hashing, parsing, I/O) — use a queue handoff instead.
- Avoid relying on user-mode hooks (Proxy/Decorator at ntdll) as the primary detection layer — direct syscalls bypass them completely.
- Avoid raw `new`/`delete` in kernel code — always use `ExAllocatePoolWithTag`/`ExFreePoolWithTag` via RAII wrappers.
- Avoid sequential consistency (`std::memory_order_seq_cst`) in ring buffer hot paths — use acquire-release semantics.

## Cross-References
- See also: `edr-architecture-guide.md` — high-level patterns this design reference implements in detail
- See also: `edr-enhancement.md` — performance enhancements built on these design foundations
- See also: `io-driver-overview.md` — IRP handling, pool allocation, IRQL reference
- See also: `kernel-primitives-overview.md` — object manager, dispatch objects, synchronization primitives
