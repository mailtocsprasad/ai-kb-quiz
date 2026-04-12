# C++ EDR Architecture Guide — Summary
> Source: `KnowledgeBase\edr-architecture-guide\Comprehensive-Architecture-Guide-for-Endpoint-Detection-and-Response-Systems-A-C.md`
> Domain: EDR component architecture (kernel + user mode, C++)
> Load when: Designing, reviewing, or implementing EDR components or the overall system architecture

## Purpose & Scope
Exhaustive analysis of Pattern-Oriented Software Architecture (POSA) applied to EDR development.
Covers the full stack from Ring 0 kernel telemetry through user-mode orchestration to agentic AI
analysis — with specific C++20/23 techniques and Windows kernel API guidance throughout.

## Key Concepts

**Structural / Partitioning Patterns**
- **Layers Pattern**: Kernel Telemetry Layer (.sys) → Orchestration/Processing Layer (.exe service) → Analytics/Response Layer. Each layer may only call downward; heuristic logic never touches kernel code.
- **Microkernel Pattern**: Kernel driver holds only the absolute core (process creation, memory tracking, hard blocks). All scanning, parsing, cloud comms run as user-mode plug-ins — a crash there is recoverable; a kernel crash is a BSOD.
- **Pipes and Filters**: Telemetry flows through independent stages — Ingestion → Transformation → Enrichment → Evaluation → Routing. Each filter is independently replaceable and parallelizable.

**C++ / OS Adaptation Patterns**
- **Wrapper Facade**: Wrap every WDM/WDF C API in a C++ class. Enforces type-safety, prevents raw handle leaks, isolates kernel code from OS version differences.
- **RAII / Execute-Around Object**: Constructor acquires (lock, pool alloc, IRP); destructor releases unconditionally. Eliminates the entire class of resource-leak vulnerabilities on early return or exception.
- **Interceptor Pattern**: Foundation of all hooking. User-mode inline hooks (ntdll JMPE) are trivially bypassed via direct syscalls — move all interceptors to OS-sanctioned kernel callbacks.

**Kernel Telemetry**
- **Kernel Callbacks**: `PsSetCreateProcessNotifyRoutineEx` (process lineage), `PsSetLoadImageNotifyRoutine` (unbacked DLL detection), `ObRegisterCallbacks` (LSASS handle protection), WFP (network C2 detection).
- **ETW (EtwTi)**: Resilient to evasion; records cross-process memory allocations and driver loads without modifying execution flow. BYOVD can silence it — correlate ETW silence with WFP anomalies.

**Kernel ↔ User Communication**
- **Inverted Call Model**: User service pre-posts pending IRPs to driver; driver completes them on callback trigger. Zero-polling, IOCP-based, instantaneous telemetry delivery across the privilege boundary.
- **Filter Manager Communication Ports**: `FltCreateCommunicationPort` + strict security descriptor. Bind to multiple IOCPs for high-concurrency minifilter telemetry.

**Concurrency Models**
- **Proactor Pattern (IOCP)**: Async I/O completion — multiple in-flight operations without a thread-per-operation. Correct choice for EDR user-mode event processing.
- **Reactor Pattern**: Synchronous event dispatch — one blocking handler stalls all others. Wrong choice for high-volume telemetry.
- **Half-Sync/Half-Async**: Async layer (kernel callbacks, non-blocking) → lock-free queue → synchronous thread pool (safe for cloud APIs, ML inference). Reconciles kernel timing constraints with analytics complexity.
- **Leader/Followers Thread Pool**: Applied to the synchronous layer to minimize context-switch and lock-contention overhead under bursty ingress.

**Modern C++ Techniques**
- **C++20 Concepts**: Enforce semantic constraints on template parameters at compile time (e.g., trivially copyable before crossing the user-kernel boundary). Eliminates runtime type-confusion bugs.
- **`constexpr`/`consteval`**: Shift AES lookup tables, hash precomputation, detection signatures to compile time — zero runtime overhead in the hot path.
- **AES-NI Inline Assembly**: `asm volatile` with `aesenc`/`aesdec` instructions for hardware-accelerated crypto in the telemetry pipeline. Orders-of-magnitude faster than software AES.

**Agentic AI Systems**
- **Blackboard Pattern**: Centralized shared knowledge base updated by specialized AI agents (Alert Triage, Cloud Metric, Network Correlation) — handles threats with no deterministic algorithmic solution.
- **MCP Tool Invocation**: Agents dynamically discover and call tools (disassembler, quarantine API, log aggregator) via Model Context Protocol. Perception → Reasoning → Acting loop.

## Heuristics & Design Rules
- Kernel driver = minimal core only. Any non-essential logic in Ring 0 risks a BSOD.
- Never block in a kernel callback. Push data to a queue; return immediately.
- Use RAII for every kernel resource — locks, pool allocations, IRPs, handles.
- Wrap all WDM/WDF APIs in C++ Wrapper Facades; never write security logic against raw C APIs.
- `ProbeForRead`/`ProbeForWrite` inside `__try`/`__except` before touching any user-mode pointer from kernel context.
- Use Proactor (IOCP), not Reactor, for user-mode telemetry processing.
- Pre-compute all static detection data (`constexpr`) — runtime computation in the critical path is unacceptable.
- Don't store plain-text API strings in the driver — use `constexpr` hash precomputation to deny adversaries a reverse-engineering map.
- Correlate ETW silence + suspicious WFP events → flag as BYOVD compromise attempt.
- Apply a strict security descriptor to `FltCreateCommunicationPort` — prevents malware from spoofing telemetry.
- Use `FltCreateCommunicationPort` + multiple IOCP bindings for minifilter high-volume concurrency.
- Scale individual Pipes-and-Filters stages independently — if the Enrichment filter is the bottleneck, parallelize only that stage.
- Use the Leader/Followers pattern on the synchronous thread pool to reduce context-switch overhead under bursty telemetry ingress.
- Design for telemetry volumes of tens of thousands of events per second — sequential processing architectures will drop events under real load.

## Critical Warnings / Anti-Patterns
- Avoid user-mode inline hooking (ntdll JMPE) as the primary telemetry mechanism — direct syscalls bypass it trivially.
- Avoid complex parsing, ML inference, or cloud calls in the kernel driver — crashes there are unrecoverable system crashes.
- Avoid the Reactor pattern for telemetry — one blocking handler starves all events.
- Avoid trusting ETW continuity alone as a health signal — BYOVD attacks silence ETW providers from Ring 0.
- Avoid single-threaded synchronous event dispatch at scale — the Half-Sync/Half-Async pattern is the correct abstraction.

## Section Map (single chapter file)
| Section | Key Patterns | Relevance |
|---------|-------------|-----------|
| Foundational Structural Patterns | Layers, Microkernel, Pipes and Filters | Component decomposition design |
| Interface and Adaptation Patterns | Wrapper Facade, RAII, Interceptor | C++ kernel code quality and safety |
| Kernel Telemetry and ETW | Kernel Callbacks, ETW, BYOVD detection | Sensor implementation |
| Kernel-to-User Communication | Inverted Call Model, Filter Manager Ports | IPC between .sys and service |
| Concurrency Architecture | Proactor, Half-Sync/Half-Async, Leader/Followers | User-mode pipeline design |
| Modern C++ Engineering | Concepts, constexpr, AES-NI asm | Driver performance and safety |
| Agentic AI Systems | Blackboard, MCP, multi-agent orchestration | AI-driven threat analysis |

## Architecture Decision Checklist
Use when reviewing a new EDR component design:
- [ ] Kernel driver limited to callbacks + queue? No scanning/parsing in Ring 0?
- [ ] All kernel resources wrapped in RAII objects?
- [ ] User-mode service uses IOCP (Proactor), not polling or blocking handlers?
- [ ] Kernel-to-user transport uses Inverted Call Model or Filter Manager ports?
- [ ] Communication port protected by a security descriptor?
- [ ] All static detection data precomputed with `constexpr`?
- [ ] Template parameters constrained with C++20 Concepts before crossing privilege boundary?
- [ ] ETW telemetry correlated with network signals (not trusted in isolation)?
- [ ] Agentic AI layer uses Blackboard + tool invocation, not a monolithic rule engine?
- [ ] Performance-critical crypto uses hardware acceleration (AES-NI) not software libraries?

## Cross-References
- See also: `edr-design-reference.md` — detailed design patterns and interface contracts
- See also: `edr-enhancement.md` — telemetry concurrency optimizations and agentic AI integration
- See also: `windows-internals.md` — kernel internals underlying the callback and memory APIs
- See also: `io-driver-overview.md` — IRP handling, minifilter depth, IOCTL patterns
- See also: `process-thread-overview.md` — `PsSetCreateProcessNotifyRoutineEx` and thread callbacks
- See also: `edr-critical-thinking.md` — decision frameworks for architecture trade-offs in EDR design
- See also: `windows-debugging.md` — debugging tools for when the kernel driver or user-mode service misbehaves
