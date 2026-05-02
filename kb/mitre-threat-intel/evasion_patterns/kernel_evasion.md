---
content_type: evasion
category: kernel_evasion
platform: Windows
techniques: [T1014, T1068, T1106]
severity: Critical
data_sources: [ETW-Process, ETW-CodeIntegrity, ETWTI, eBPF]
---

# Kernel Evasion Patterns

Kernel-mode evasion techniques modify the kernel's own data structures or loaded code to remove process visibility, evade kernel callbacks, and manipulate security enforcement. These techniques are the hardest to detect because they operate at or below the same privilege ring as security agents; once a kernel rootkit is active, any data the EDR agent reads from the kernel may have been tampered with. Detection depends on correlating multiple independent telemetry sources and identifying structural inconsistencies that the rootkit cannot simultaneously falsify.

---

## KE-001: Direct Kernel Object Manipulation (DKOM) — ActiveProcessLinks Unlinking

**Technique:** T1014 (Rootkit)

**Description:** Every `EPROCESS` structure contains a `LIST_ENTRY ActiveProcessLinks` field that links it into the global `PsActiveProcessHead` doubly-linked list. Tools that enumerate processes via `NtQuerySystemInformation(SystemProcessInformation)` walk this list. A rootkit unlinks its target EPROCESS from the list — setting `ActiveProcessLinks.Flink->Blink = ActiveProcessLinks.Blink` and `ActiveProcessLinks.Blink->Flink = ActiveProcessLinks.Flink` — making the process invisible to the standard enumeration API while it continues to run.

**Kernel structures involved:** `EPROCESS.ActiveProcessLinks` (offset varies by Windows build; PDBs provide current offsets), `PsActiveProcessHead`.

**Detection approaches:**

- **PspCidTable cross-reference**: The `PspCidTable` (a kernel handle table keyed by PID) maintains entries for every process regardless of its list-linked state. A process that appears in `PspCidTable` (accessible via NtQuerySystemInformation with the appropriate class or via handle enumeration) but not in the `ActiveProcessLinks` walk is DKOM-hidden. EDR kernel drivers can enumerate both structures and compare; any PID in the table without a corresponding list entry is hidden.
- **ETW callback cross-reference**: `PsSetCreateProcessNotifyRoutine` callbacks fire at process creation and termination. An EDR that maintains its own process tree from these callbacks and compares it against the `ActiveProcessLinks` walk can identify hidden processes whose creation was seen but whose list entry has since been removed.
- **ETWTI baseline**: ETWTI emits events for all process memory operations regardless of DKOM state. A PID appearing in ETWTI events that is absent from enumeration APIs indicates active DKOM.

**Telemetry signals:**

- Absence of a process in standard enumeration when it was previously visible (disappearance event).
- A kernel driver load event (ETWTI or CodeIntegrity) from a process PID that subsequently cannot be found via standard APIs.
- Handle opens to a now-"invisible" process PID still succeeding (because PspCidTable is intact).

---

## KE-002: PspCidTable Manipulation

**Technique:** T1014 (Rootkit)

**Description:** A more thorough rootkit targets `PspCidTable` itself — the kernel's master process-ID-to-EPROCESS mapping. Removing an entry from `PspCidTable` makes the process invisible to all user-mode handle operations and makes the PID unusable (subsequent `OpenProcess` calls with that PID return `STATUS_INVALID_CID`). This is rare in commodity malware because it causes system instability if not done perfectly, but it is known in APT-grade rootkits.

**Detection approaches:**

- Kernel-level scanning of the physical `PspCidTable` structure (a 3-level table for large PID spaces, or a simpler flat table on smaller systems) and comparing the result against all other enumeration mechanisms. Any discrepancy between what `PspCidTable` scanning finds and what `NtQuerySystemInformation` returns indicates manipulation.
- Post-mortem: memory forensics tools like Volatility's `pstree` plugin scan raw memory for `EPROCESS` pool tags (`Proc`) and compare against all known enumeration paths, catching processes hidden from all in-OS mechanisms.

---

## KE-003: Callback Removal (PsSetCreateProcessNotifyRoutine / ObRegisterCallbacks)

**Technique:** T1014, T1562 (Impair Defenses)

**Description:** The kernel maintains arrays of registered callbacks for process creation (`PspCreateProcessNotifyRoutine`), image load (`PspLoadImageNotifyRoutine`), thread creation (`PspCreateThreadNotifyRoutine`), and object operations (`ObpCallPreOperationCallbacks`). A rootkit that can locate these arrays in kernel memory — by scanning for the exported kernel symbols or using brute-force scanning of kernel sections — can zero out or replace callback entries, silencing the EDR agent's notification channel.

**Impact:** The EDR loses real-time notification of process creation, image loads, and thread creation. Its process tree becomes stale; injection into a process after callback removal generates no notification. ETWTI remains active (it fires from kernel components not dependent on callback arrays) but the EDR may not be listening.

**Detection approaches:**

- **Callback array integrity monitoring**: A kernel driver that periodically re-reads the callback arrays and compares them against its initial registration can detect removals. If the driver's own entry disappears from the array, callback removal has occurred.
- **Self-presence verification**: An EDR that uses multiple registration mechanisms (callbacks + ETW session + minifilter) can detect when one channel goes silent while others remain active — a strong signal of targeted callback removal.
- **ETWTI cross-check**: If ETWTI shows a process creation event but the EDR's process-creation callback did not fire, callback removal is indicated.
- **Driver removal events**: `Microsoft-Windows-CodeIntegrity` events for the rootkit driver's load or unload activity prior to callback removal.

**Telemetry signals:**

- ETW `Microsoft-Windows-Kernel-Process` events (from Microsoft's own ETW instrumentation, which is separate from callback-based notification) for processes that were not seen in the EDR's callback stream.
- ETWTI events for memory operations in processes whose creation the EDR never observed.

---

## KE-004: LSTAR/SSDT Hook Modification (Legacy)

**Technique:** T1106 (Native API), T1014

**Description:** On older Windows versions (pre-HVCI/Secure Boot enforcement), rootkits could modify the SSDT (System Service Descriptor Table) to replace native syscall handlers with attacker-controlled routines. This allowed filtering or falsifying all syscall results. On modern Windows with HVCI (Hypervisor-Protected Code Integrity), the kernel's code pages are mapped as read-only in the second-level page tables maintained by the hypervisor; any write attempt triggers a #GP fault and a BSOD. This defense makes SSDT hooking impractical on HVCI-enabled systems.

**Detection on legacy systems:** SSDT integrity verification by comparing the current handler addresses against known-good values from a clean system image.

**Modern relevance:** Attackers on HVCI-disabled systems or VMs may still attempt SSDT modification. The primary detection is a kernel driver load event followed by unexpected behavioral changes (syscall results inconsistent with ETW-observed kernel activity).

---

## KE-005: VDM / Hypervisor-Level Evasion (Blue Pill)

**Technique:** T1068 (Exploitation), T1014

**Description:** A hypervisor rootkit (Blue Pill variant) inserts itself below the OS hypervisor layer, virtualizing the existing OS into a VM. The OS's own kernel runs inside a virtual machine that the rootkit controls; all hardware access, memory reads, and CPU state pass through the rootkit's VMM. This provides complete visibility and control over all OS operations with no detectable presence in the OS's kernel structures.

**Detection difficulty:** True hypervisor rootkits are detectable only from outside the compromised OS instance — via another hypervisor layer above it, or via hardware attestation (TPM PCR measurements, Secure Boot chain of trust). From within the OS, all integrity checks are subject to falsification.

**Practical note:** Hypervisor rootkits are extremely rare in operational malware due to implementation complexity and hardware compatibility requirements. They are documented primarily in research and nation-state-grade tools.

---

## Summary: Detection Priority for Kernel Evasion

| Pattern | ETWTI Available | ETW-Process Available | Detection Confidence |
|---|---|---|---|
| DKOM ActiveProcessLinks | Yes (events still fire for PID) | Partial (may be hidden from NtQuerySI) | High via cross-reference |
| PspCidTable removal | Partial | No | Medium via memory forensics |
| Callback removal | Yes | Partial (own callbacks silent) | High via self-check |
| SSDT hooking | Yes (kernel behavior anomaly) | Depends | Medium (legacy systems) |
| Hypervisor rootkit | No (ETWTI is in-guest) | No | Low (out-of-band only) |
