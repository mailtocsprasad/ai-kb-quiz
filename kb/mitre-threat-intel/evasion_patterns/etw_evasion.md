---
content_type: evasion
category: etw_evasion
platform: Windows
techniques: [T1562, T1106]
severity: Critical
data_sources: [ETWTI, ETW-Process, ETW-Security]
---

# ETW Evasion Patterns

ETW (Event Tracing for Windows) evasion techniques suppress, corrupt, or redirect the telemetry stream that security products depend on. Unlike most evasion techniques that avoid triggering events, ETW evasion attacks the instrumentation channel itself — allowing the attacker to then proceed with otherwise-detectable operations without generating observable signals.

Detection of ETW evasion is a bootstrapping problem: if the evasion is fully successful, the telemetry stream goes silent, and absence-of-signal detection is the only remaining option. The defensive answer is layered telemetry sources with independent attack surfaces, so that silencing one source does not eliminate all visibility.

---

## EE-001: EtwEventWrite Patch (In-Process ETW Provider Disabling)

**Technique:** T1562.006 (Indicator Blocking)

**Description:** `EtwEventWrite` is the core user-mode function in `ntdll.dll` that all ETW providers call to emit events. Patching the first bytes of `EtwEventWrite` with a `ret 0` instruction (opcode `C3` or `C2 00 00`) silences all user-mode ETW providers in the patching process — including PowerShell's script block logging, the .NET framework's CLR provider, and any user-mode security provider. After patching, all `EtwEventWrite` calls return immediately without emitting events.

**Scope:** This patch affects only the process that performs it. Kernel-mode ETW providers (including ETWTI, `Microsoft-Windows-Kernel-Process`, `Microsoft-Windows-Kernel-File`) are unaffected because they call `EtwWrite` (the kernel counterpart) directly, bypassing the user-mode `EtwEventWrite` function entirely.

**Detection:**

- **ETWTI WRITEVM_REMOTE / self-PROTECTVM**: Patching `EtwEventWrite` requires modifying executable code in a DLL's `.text` section. `ntdll.dll` is loaded as `PAGE_EXECUTE_READ`; writing to it requires first calling `VirtualProtect` to change its protection. ETWTI emits a PROTECTVM event when a process changes the protection of its own executable image sections — this is never legitimate for `ntdll.dll` in production code.

  ```
  ETWTI PROTECTVM(
    base_address IN ntdll_text_section_range
    NewProtect ∈ {PAGE_EXECUTE_READWRITE, PAGE_READWRITE}
    target_pid = caller_pid (self-modification)
  )
  → EE-001 Critical (0.95)
  ```

- **Kernel callback cross-reference**: Kernel ETW providers still fire for process operations in the patching process. If PowerShell events (4104) stop being emitted by a process that is still running (evidenced by Kernel-Process events), the script block logging provider in that process has been silenced.

- **ETWTI stays active**: ETWTI events for process/memory operations in the same PID where PowerShell logging has gone silent confirm that the process is still active but its user-mode ETW channel has been disabled.

---

## EE-002: ETW Session Hijacking

**Technique:** T1562.006

**Description:** ETW operates on a session model: a controller (e.g., the EDR agent) creates an ETW session, subscribes providers to it, and receives events via a buffer ring. The session is identified by a `TRACEHANDLE`. If an attacker can enumerate and stop the EDR's ETW session (via `ControlTrace(WNODE_FLAG_TRACED_GUID, EVENT_TRACE_CONTROL_STOP)` or by closing the session handle), all subscribed providers stop delivering events to that session.

Stopping an ETW session requires `SeSystemProfilePrivilege` or administrator rights. The attack is therefore limited to elevated processes.

**Detection:**

- **Event ID 1109 (Microsoft-Windows-EventLog)**: Some ETW infrastructure logging captures session state changes. However, this is not universally configured.
- **ETW session health monitoring**: The EDR can implement a keepalive mechanism — a heartbeat event emitted every N seconds that, if absent for > 2× N seconds, indicates the session has been disrupted.
- **Multiple concurrent sessions**: An EDR can run two independent ETW sessions subscribing to the same providers. Stopping one session leaves the other active; the attacker must stop both. The second session's events can be used to detect the stoppage of the first.

---

## EE-003: ETW Provider Unhooking / Registration Removal

**Technique:** T1562.006

**Description:** ETW providers register themselves at process startup via `EventRegister`. The registration record is maintained in the provider list of the process's ETW control block (`EtwpRegistrationList`). An attacker with in-process execution can walk this list and call `EventUnregister` on registered provider handles — silencing specific providers (e.g., the PowerShell script block logging provider) while leaving others active.

**Scope:** Same-process only. Kernel-mode providers are unaffected.

**Detection:** Similar to EE-001: the absence of expected user-mode ETW events from a still-running process, while kernel ETW events continue for that process, is the signal. Script Block Logging (4104) events ceasing mid-session without a PowerShell engine shutdown (Event 403) is the specific indicator.

---

## EE-004: NtTraceEvent Direct Syscall Bypass

**Technique:** T1106 (Native API bypass)

**Description:** Some EDR products hook `EtwEventWrite` in ntdll to perform inline inspection of ETW events. An attacker who is aware of this hook can bypass the hook by calling the underlying syscall directly: `NtTraceEvent` (which `EtwEventWrite` calls internally) or by emitting events via a direct syscall stub that bypasses the hooked ntdll function entirely.

This is less relevant for blocking ETW events (the attacker wants to prevent, not emit events) and more relevant for malware that wants to emit false/benign events to confuse an EDR that uses ETW in a bidirectional way (consuming and inspecting events the process emits).

**Note:** Most ETW evasion targets suppression, not injection of false events. ETW session authentication is enforced by the kernel for many providers — user processes cannot register as system providers or emit events to kernel-only sessions.

---

## EE-005: ETWTI Restriction Bypass (PPL Registration Attack)

**Technique:** T1562.006, T1068

**Description:** ETWTI (Microsoft-Windows-Threat-Intelligence) is a restricted provider: only processes with `PS_PROTECTED_ANTIMALWARE_LIGHT` or higher protection level can subscribe to it as a consumer. The attacker cannot simply open an ETWTI session from standard code. However, if the attacker achieves kernel code execution, they can either: (a) patch the kernel's session validation for ETWTI, (b) modify the session state directly in kernel memory to disable ETWTI event delivery, or (c) remove the ETWTI callbacks from the kernel's ETW callback array.

**Scope:** Requires kernel code execution (T1068 or T1014). Represents the top of the escalation chain: a kernel-mode attacker who neutralizes ETWTI has eliminated the highest-fidelity user-mode memory monitoring signal.

**Detection:**

- **CodeIntegrity events for the kernel exploit or rootkit driver** that achieved kernel code execution precede ETWTI manipulation.
- **ETW kernel session health check**: If ETWTI events from a known-active process (one that should be generating ALLOCVM/WRITEVM events based on its behavior) suddenly stop, ETWTI has been disrupted.
- **Hardware-level attestation**: TPM PCR measurements of the kernel image can detect kernel code modification. Intel CET/IBT (Indirect Branch Tracking) violations may be generated if the exploit modifies kernel code flow in a CET-enabled system.

---

## EE-006: PowerShell Script Block Logging Bypass via Reflection

**Technique:** T1562, T1059.001

**Description:** PowerShell's script block logging provider emits Event ID 4104 for all scripts compiled by the PowerShell parser. Bypasses:

- **Compile-time bypass**: Generating PowerShell commands at the .NET bytecode level (compiling C# that calls PowerShell APIs, or using `System.Management.Automation.ScriptBlock::Create` with `skipAnalysis = true`) can avoid triggering the standard 4104 path.
- **System.Reflection bypass**: Using .NET reflection to directly instantiate `System.Management.Automation.Language.Parser` and compile scripts without going through the standard event-emitting path.
- **PowerShell 2.0 downgrade**: Invoking `powershell -version 2.0` starts an older engine version that does not support script block logging. This requires .NET 2.0 to be installed. Windows 10 can have .NET 2.0 removed via optional features; its presence or absence can be used as an environment fingerprint.

**Detection:**

- `powershell.exe -version 2.0` or `-v 2` in a command line (Event ID 4688 or ETW ProcessStart) is a strong indicator of a downgrade bypass attempt.
- Event ID 400 (PowerShell engine started) with `EngineVersion = 2.0` when the current system default is 5.x.
- Absence of 4104 events from a PowerShell process that is otherwise active (kernel ETW showing file/network activity from `powershell.exe` without any corresponding script block log events).

---

## Summary: ETW Evasion Detection Resistance

| Attack | Silences | Survives | Primary Counter-Detection |
|---|---|---|---|
| EtwEventWrite patch | User-mode providers (PowerShell, .NET) | ETWTI, Kernel-Process, Kernel-File | PROTECTVM on ntdll .text |
| Session hijacking | All providers in that session | Providers in secondary session | Session keepalive heartbeat |
| Provider unregistration | Specific provider only | Other providers | 4104 gap with active kernel events |
| ETWTI bypass (kernel) | ETWTI | Kernel-Process, Kernel-File ETW | CodeIntegrity events, PCR |
| PS v2 downgrade | Script Block Logging | Process ETW, command-line logging | -version 2 in command line |
