# Advanced Windows Internals & Kernel Architecture — Summary
> Source: `KnowledgeBase\windows-internals\Advanced-Windows-Internals-Kernel-Architecture-and-EDR-Telemetry-A-Comprehensive.md`
> Domain: Windows kernel architecture, security subsystems, EDR telemetry mechanisms, adversarial tradecraft
> Load when: Implementing EDR sensors, analyzing kernel structures, understanding security subsystems, reviewing adversarial evasion techniques, or planning BYOVD mitigations

## Purpose & Scope
Deep reference for the Windows kernel execution model from Ring 0 hardware primitives through
the Executive subsystems, security architecture (SRM, tokens, MIC, sandboxing), EDR telemetry
pipelines (kernel callbacks, minifilters, WFP, ETWti), adversarial evasion tradecraft, and
upcoming architectural shifts (user-mode EDR, Rust, eBPF, KCET).

## Key Concepts

**Kernel Layering**
- **HAL** (Hardware Abstraction Layer): isolates Ntoskrnl from platform-specific differences (interrupt controllers, DMA, cache topology).
- **Kernel** (Ntoskrnl lower half): scheduling, synchronization, interrupt dispatch, trap handling.
- **Executive** (Ntoskrnl upper half): Object Manager, Process Manager, Memory Manager, Security Reference Monitor, I/O Manager, Configuration Manager.
- Ring 0 (kernel) / Ring 3 (user): hardware-enforced privilege boundary; user-mode code cannot directly access kernel structures or issue privileged instructions.

**Syscall Dispatch Mechanism**
- User mode executes `syscall` instruction; CPU transitions to Ring 0 via LSTAR MSR → `KiSystemCall64`.
- SSN (System Service Number) placed in EAX register; SSDT (`KeServiceDescriptorTable`) maps SSN to kernel function.
- `KTRAP_FRAME` saved on kernel stack: captures RIP, RSP, registers — source of KTRAP_FRAME-based direct syscall detection.
- EDR hook detection: if KTRAP_FRAME.RIP falls outside `ntdll.dll` / `win32u.dll` → direct syscall anomaly.

**Process and Thread Structures**
- `EPROCESS`: `UniqueProcessId`, `ActiveProcessLinks` (DKOM target), `VadRoot` (VAD tree), `Token` (access token pointer, `_EX_FAST_REF` encoded), `ThreadListHead`.
- `ETHREAD`: `Cid` (client ID), `StartAddress`, `Win32StartAddress`, `ApcState` (for APC injection tracking).
- 7-stage `NtCreateUserProcess`: validate parameters → alloc EPROCESS/ETHREAD → init PEB → map executable → inherit handles → fire process-creation callbacks → resume thread.

**Scheduling**
- Priority levels 0–31: 0 = zero-page thread; 1–15 = variable/dynamic; 16–31 = real-time.
- Preemptive: higher-priority thread immediately preempts running thread.
- Quantum exhaustion, DPC interrupts (DISPATCH_LEVEL), and APC delivery (APC_LEVEL) all interact with the scheduler.

**WoW64 (32-bit on 64-bit)**
- Dual PEB/TEB: 32-bit PEB at `FS:0x30`; 64-bit PEB at `GS:0x60`.
- `wow64.dll` + `wow64cpu.dll`: thunking layer converts 32-bit API calls to 64-bit equivalents.
- ARM64 devices: additional binary translation layer for x86 executables.
- EDR note: WoW64 thunk layer is a common evasion point — monitor both 32-bit and 64-bit API surfaces.

**Object Manager**
- Every kernel resource (process, thread, file, event, mutex) is an Object: Object Header + body.
- Object Header fields: `TypeIndex`, `PointerCount` (kernel references), `HandleCount` (user handle table references), `SecurityDescriptor`.
- Namespace root `\` — objects accessible by name (e.g., `\Device\HarddiskVolume3`). `OBJ_INHERIT` flag propagates handles to child processes.
- `ObRegisterCallbacks`: EDR registers pre/post-operation callbacks for handle operations; can strip `PROCESS_ALL_ACCESS` to prevent LSASS dumps.

**ALPC (Advanced Local Procedure Call)**
- Two port types: Connection Port (server listens) + Communication Port (per-client pair after accept).
- Short message mode: payload < ~256 bytes fits in-line in the IPC buffer.
- Large message mode: sender creates a Section object; both sides map views into their address space — zero-copy data transfer for large payloads.
- CNG Key Isolation: private key operations dispatched via ALPC to LSA (lsass.exe); raw key never leaves LSA memory space.

**Security Reference Monitor (SRM)**
- "Check at Open" model: access check performed when a handle is opened, not on each use. Result stored in `ACCESS_MASK` in the handle table entry.
- Access check inputs: caller's Access Token, object's Security Descriptor (DACL).
- DACL traversal: (1) no DACL → full access; (2) null DACL → no access; (3) iterate ACEs: explicit Deny first, accumulate Allow, implicit deny at end if not fully satisfied.

**Access Tokens**
- Fields: User SID, Group SIDs (with `SE_GROUP_USE_FOR_DENY_ONLY` flag for deny-only contexts), Privileges (bitmask), Default DACL.
- Types: Primary token (process), Impersonation token (thread-level; SecurityIdentification/Impersonation/Delegation levels).
- `CreateRestrictedToken`: produces a restricted token with additional restricted SID list — access check runs twice (normal + restricted SID sets); both must grant access.

**Mandatory Integrity Control (MIC)**
- Integrity levels: Untrusted → Low → Medium → High → System.
- **No-Write-Up**: process at Medium cannot write to objects labeled High — blocks privilege escalation via shared objects.
- **No-Read-Up** (optional): blocks reading from higher integrity objects.
- Integrity level is an additional ACE type (`SYSTEM_MANDATORY_LABEL_ACE`) in the security descriptor.

**Sandboxing Architecture**
- `CreateRestrictedToken` + `SE_GROUP_USE_FOR_DENY_ONLY` restricted SIDs for deny-only group membership.
- Two-pass access check: token's normal access check AND restricted SID check must both permit access.
- AppContainer: namespace virtualization under `AC\<PackageSID>` — isolated object namespace per app.
- Job Objects: `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` terminates all processes when job handle closes; UI restrictions limit desktop access.

**Virtual Address Space**
- VAD (Virtual Address Descriptor) tree: red-black tree rooted at `EPROCESS.VadRoot`; describes every committed virtual region (type, protection, backing file).
- PML4 paging: CR3 → PML4 (512 entries) → PDPT → PD → PT → PFN → physical address.
- TLB caches virtual-to-physical translations; CR3 reload flushes TLB (costly — see KVA Shadow below).
- Modified Page Writer flushes dirty pages to `pagefile.sys`, freeing PFNs for active processes.

**Hardware Side-Channel Mitigations**
- **KVA Shadowing** (Meltdown): kernel address space removed from user-mode page tables. CR3 swap on every syscall entry/exit — performance cost on high-frequency syscall paths.
- **Retpoline** (Spectre v2): replaces indirect jumps with return trampolines that trap speculative execution.
- **IBRS + STIBP**: CPU hardware controls preventing branch-predictor poisoning across privilege levels and sibling hyper-threads.

**EDR Telemetry — Kernel Callbacks**
| API | Event | EDR Use |
|-----|-------|---------|
| `PsSetCreateProcessNotifyRoutineEx2` | Process create/terminate | Inspect `PS_CREATE_NOTIFY_INFO`; can veto launch |
| `PsSetCreateThreadNotifyRoutineEx` | Thread create/terminate | Detect remote thread injection |
| `PsSetLoadImageNotifyRoutineEx` | Image/DLL map into memory | Identify unbacked payloads, DLL side-loading |
| `ObRegisterCallbacks` | Handle pre/post operations | Strip `PROCESS_ALL_ACCESS` from LSASS handles |
| `CmRegisterCallbackEx` | Registry access/modification | Block persistence, ASEP keys, service disabling |
- Altitude: integer assigned by Microsoft; determines callback dispatch order for multiple registered drivers.

**File System Minifilters**
- `IRP_MJ_CREATE`, `IRP_MJ_WRITE` PreOperation callbacks inspect I/O before reaching the file system; PostOperation inspects results.
- Context management: associate per-stream/per-volume state with `FltAllocateContext` — avoid global variables for per-file tracking.
- Use for ransomware detection (mass `IRP_MJ_WRITE` to renamed files) and data exfiltration blocking.

**WFP (Windows Filtering Platform)**
- Callout drivers register at layers (e.g., `FWPM_LAYER_ALE_AUTH_CONNECT_V4`) for connection-level interception.
- Deep packet inspection before data reaches application; track C2 connections, DNS tunneling.
- `netio!gWfpGlobal`: WFP engine state root — enumerable in WinDbg for forensic callout inspection.

**ETW Threat Intelligence (ETW-Ti)**
- Restricted: consumer must run as PPL ANTIMALWARE_LIGHT + ELAM certificate.
- Key events: `EtwTiLogReadWriteVm` (cross-process memory R/W), `EtwTiLogSetContextThread` (thread context modification), APC queuing, `VirtualProtect` equivalents.
- Tamper resistance: kernel-pushed telemetry bypasses user-mode interception (unlike standard LSA auditing).

**Cryptography — CNG Architecture**
- `BCrypt.dll`: stateless primitives (hashing, symmetric encryption, signature verification) — kernel-mode safe.
- `NCrypt.dll`: key storage via Key Storage Providers (KSPs): Software KSP (DPAPI-encrypted files), Smart Card KSP, Platform Crypto Provider (TPM-backed — keys physically non-exportable).
- Key Isolation: private operations dispatched via ALPC to LSA; key material never enters application memory.
- SSPI + SChannel TLS workflow: `AcquireCredentialsHandle` → `InitializeSecurityContext` loop → `EncryptMessage`/`DecryptMessage`.

**Upcoming Architecture Changes**
- **EDR to User Mode** (July 2025 preview): Microsoft shifting EDR sensors out of Ring 0 via expanded ETWti + VBS enclaves. Deprecates `ObRegisterCallbacks` and minifilter architectures.
- **Rust in Windows kernel**: Microsoft Secure Future Initiative; Rust borrow checker eliminates heap overruns, UAF, and stack corruptions at compile time.
- **DTrace** (Server 2025 + 24H2): dynamic kernel/user instrumentation without binary modification.
- **KASAN, KDP, KCET**: Kernel Address Sanitizer, Kernel Data Protection, and hardware shadow stacks (blocks ROP/JOP call stack spoofing).
- **Regression risk**: CVE-2024-43511 patch introduced CVE-2025-53136 — race in `RtlSidHashInitialize` leaked kernel pointers from TOKEN structure into user buffers, enabling KASLR bypass.

## Heuristics & Design Rules
- Always treat `EPROCESS.ActiveProcessLinks` as potentially tampered — validate with `FromListEntry` traversal in parallel with `!process`.
- Apply `_EX_FAST_REF` masking (`& ~0x7`) before dereferencing any fast-ref encoded pointer (`Token`, callback pointers).
- Register EDR callbacks at PASSIVE_LEVEL; never perform synchronous analysis in the callback itself — push to queue and return.
- Correlate ETWti silence + `PspCreateProcessNotifyRoutine` zeroed entries as a combined BYOVD indicator.
- Use `ObRegisterCallbacks` to protect LSASS handle access rights even if kernel-based LSASS protection is unavailable.
- Treat the "user mode EDR" transition as a near-term architectural requirement — begin designing ETWti-native and VBS-enclave-based sensors now.

## Critical Warnings / Anti-Patterns
- Avoid accessing KVA Shadow–protected kernel structures from user-mode — CR3 swap cost is real; don't design sensors that trigger it on every event.
- Avoid relying on `FS:0x30` TEB access as a universal PEB indicator — WoW64 processes have dual TEB/PEB at different segment bases.
- Avoid SSDT patching for telemetry — PatchGuard triggers Bugcheck 0x109 immediately; use supported callback APIs exclusively.
- Avoid raw OpenSSL on Windows for key management — file-based `.pem`/`.key` loading bypasses CNG Key Isolation, exposing private keys to memory scrapers.

## Cross-References
- See also: `edr-architecture-guide.md` — architectural patterns built on these kernel primitives
- See also: `edr-design-reference.md` — IRQL-aware synchronization and RAII patterns for kernel code
- See also: `edr-enhancement.md` — BYOVD case studies and upcoming eBPF/user-mode EDR transitions
- See also: `windows-debugging.md` — WinDbg commands for inspecting EPROCESS, SSDT, VAD, and callback arrays
- See also: `io-driver-overview.md` — IRP handling and minifilter depth
- See also: `process-thread-overview.md` — process/thread callback registration detail
