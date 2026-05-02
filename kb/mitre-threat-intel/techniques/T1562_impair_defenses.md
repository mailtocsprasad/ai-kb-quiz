---
technique_id: T1562
technique_name: Impair Defenses
tactic: [Defense Evasion]
platform: Windows
severity: Critical
data_sources: [ETW-Process, ETW-Registry, ETWTI, ETW-Security]
mitre_url: https://attack.mitre.org/techniques/T1562/
---

# T1562 — Impair Defenses

## Description (T1562)

T1562 Impair Defenses covers adversary actions that disable, modify, or circumvent security monitoring tools and mechanisms before or during an attack. On Windows, defensive tooling depends on a chain of trust from kernel callbacks through ETW providers to user-mode agents. Disrupting any link in this chain can selectively blind defenders to subsequent malicious activity. Because `ai-procwatch-mcp` itself depends on ETW providers and kernel callbacks, this technique family is directly relevant to assessing whether the genome being analyzed is complete or whether telemetry gaps indicate active evasion.

---

## Windows Implementation Details (T1562)

### ETW Provider Architecture as an Attack Surface

Windows ETW providers are registered through `EtwRegister` (kernel-mode) or `EventRegister` (user-mode), which creates an `ETW_REG_ENTRY` structure in kernel memory. This structure is linked into a global hash table keyed by provider GUID. When a controller enables a provider via `EnableTraceEx2`, the kernel sets the provider's enablement state in the `ETW_REG_ENTRY.EnableInfo` array. User-mode providers then check this state through a shared memory page (the "enable callback") before each event emission.

The critical user-mode path is `ntdll!EtwEventWrite`. When a user-mode provider emits an event, execution flows through this function, which checks whether any session has enabled the provider and, if so, formats and dispatches the event through the `NtTraceEvent` syscall. This user-mode function is a high-value target for patching because disabling it silences all user-mode events from the patched process without affecting kernel-mode providers.

### Kernel Callback Arrays as Attack Surfaces

EDR solutions register callbacks via:
- `PsSetCreateProcessNotifyRoutineEx2` — callback array: `PspCreateProcessNotifyRoutine` (kernel global array, 64 entries max)
- `PsSetCreateThreadNotifyRoutineEx` — callback array: `PspCreateThreadNotifyRoutine`
- `PsSetLoadImageNotifyRoutineEx` — callback array: `PspLoadImageNotifyRoutine`
- `ObRegisterCallbacks` — per-object-type callback list
- `CmRegisterCallbackEx` — registry callback list

Each array is a table of NOTIFY_ENTRY structures in kernel memory. Overwriting an entry with NULL or a benign function pointer effectively removes that EDR callback without crashing the system. This operation requires kernel-mode write access, obtainable via BYOVD (see `T1068_exploitation_privilege_escalation.md`).

---

## Observable Artifacts (T1562)

- A sudden, sustained drop in the event rate from a specific ETW provider (e.g., `Microsoft-Windows-Kernel-Process` emitting zero events despite active process activity) indicates provider-level tampering.
- `EtwEventWrite` patched with a `RET` instruction (0xC3) or `NOP` sled (0x90 * N) at the function entry point in a specific process's ntdll.dll. Detectable by scanning mapped ntdll.dll images and comparing against the on-disk hash.
- `PspCreateProcessNotifyRoutine` array entries set to NULL where a known EDR driver previously registered.
- `NtUnregisterTraceGuids` or `EtwUnregisterTraceGuids` called for provider GUIDs belonging to security tools.
- `wevtutil.exe` or `auditpol.exe` invocations in the genome that modify or clear audit settings.
- Registry writes to `HKLM\SYSTEM\CurrentControlSet\Services\<EDR_driver>\Start` changing the value to 4 (disabled).
- Service control commands (`sc stop <EDR_service>`, `net stop <EDR_service>`) in child process genomes.

---

## ETW / eBPF Telemetry Signals (T1562)

### Microsoft-Windows-Threat-Intelligence (ETWTI)

ETWTI fires from kernel mode and is the hardest source to suppress without kernel execution. It provides the best coverage for detecting ETW tampering attempts:

- **WRITEVM_LOCAL**: When a process writes to its own address space in a region corresponding to a loaded module (ntdll.dll address range), and the write size matches the function prologue of `EtwEventWrite`, this is a strong indicator of ETW function patching.
- **PROTECTVM_LOCAL**: `VirtualProtect` calls that change the protection of ntdll.dll's `.text` section from `PAGE_EXECUTE_READ` to `PAGE_EXECUTE_READWRITE` (required before patching, unless the process uses kernel-level writes). This appears as a PROTECTVM event on a region whose base address matches the mapped ntdll image base.

### Microsoft-Windows-Security-Auditing

- **Event 1102** (The audit log was cleared): A direct indicator of T1070.001 / T1562.002. Any occurrence during a genome capture is treated as a critical indicator.
- **Event 4719** (System audit policy was changed): Fires when `auditpol.exe` or direct registry manipulation disables audit categories. `SubjectProcessName` other than a known audit management tool = malicious.
- **Event 4657** (Registry value modified): For writes to `HKLM\SYSTEM\CurrentControlSet\Control\WMI\Security` (ETW session security) or `HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Perflib` (performance counter registry) — these control ETW session permissions and provider registrations.

### Microsoft-Windows-Kernel-Process

- Process creation of `net.exe`, `sc.exe`, `taskkill.exe`, `powershell.exe -command Stop-Service`, or known EDR service names in child process chains — these are the user-mode vectors for service-based defense impairment.
- Image Load events for `ntdll.dll` immediately followed by private executable memory allocation of the same size — this is the "ntdll unhooking" pattern (mapping a fresh ntdll from disk to bypass hooks, closely related to T1106).

---

## Sub-Techniques (T1562)

### T1562.006 — Indicator Blocking via ETW Patching (T1562)

T1562.006 Indicator Blocking encompasses techniques that prevent security tools from receiving telemetry. ETW patching is the most technically significant Windows variant.

**EtwEventWrite NOP Patching**: The attacker calls `VirtualProtect` to make ntdll.dll's `.text` section writable in the attacker's process, then overwrites the first several bytes of `EtwEventWrite` with `NOP` instructions (0x90) or a `RET` instruction (0xC3). All subsequent ETW event emissions from that process silently succeed (no crash) but produce no events. This technique affects only user-mode events; ETWTI kernel events are unaffected.

Detection: ETWTI PROTECTVM_LOCAL on the ntdll.dll image range followed by WRITEVM_LOCAL to the same address. Pattern in the genome: `NtProtectVirtualMemory(ntdll_base + EtwEventWrite_offset, PAGE_EXECUTE_READWRITE)` → `NtWriteVirtualMemory(same_address, [0xC3])`. Confidence = **Critical (0.95)**.

**EtwUnregisterTraceGuids / Provider Unregistration**: Calling `EtwUnregisterTraceGuids` with the GUID of a security-relevant provider removes the `ETW_REG_ENTRY` from the kernel's registration table. Subsequent `EnableTraceEx2` calls for that GUID succeed (no error) but the provider no longer receives enable notifications. Detection: monitor for `NtTraceControl(TraceCode_UnregisterProvider)` syscall activity targeting known security provider GUIDs.

**_ETW_GUID_ENTRY Manipulation**: With kernel write access, an attacker can directly NULL out the `EnableInfo.IsEnabled` fields in the `ETW_GUID_ENTRY` structure for a target provider, preventing event emission without calling any detectable API. This requires kernel execution (typically BYOVD). Detectable only through ETWTI (which operates independently of `_ETW_GUID_ENTRY` state) or via cross-validation: ETWTI still emitting events while the expected high-level provider (e.g., Kernel-Process) shows zero events.

### T1562.001 — Disable or Modify Security Tools (T1562)

T1562.001 covers stopping security product services or deleting their files. Common patterns:
- `sc stop <AV_service>` — stops the security product's service.
- `taskkill /F /IM <EDR_agent.exe>` — kills the agent process.
- Registry modification of the driver service's `Start` value to 4 (disabled on next boot).
- Deleting or corrupting the EDR driver binary from `\System32\drivers\`.

Detection: ETW process creation events for `sc.exe`, `net.exe`, `taskkill.exe` with command-line arguments referencing known security tool service names. Registry write events on `HKLM\SYSTEM\CurrentControlSet\Services\<EDR_driver>\Start` via ETW-Registry.

### T1562.002 — Disable Windows Event Logging (T1562)

T1562.002 targets the Windows Event Log service (EventLog / wevtsvc.dll) directly.

- `wevtutil.exe cl Security` / `wevtutil.exe cl System` — clears event log channels.
- `net stop EventLog` or `sc stop EventLog` — stops the Event Log service.
- CLFS journal file deletion (`%SystemRoot%\System32\Winevt\Logs\*.evtx`).
- PowerShell: `Clear-EventLog -LogName Security`.

Detection: Security Event 1102 (Audit Log Cleared) is the direct indicator. Process creation of `wevtutil.exe` with `cl` argument. ETW Kernel-File delete events on `.evtx` files in the Winevt Logs directory.

### Callback Array Removal (T1562 — kernel variant)

With kernel write access from BYOVD, removing entries from `PspCreateProcessNotifyRoutine` silences all `PsSetCreateProcessNotifyRoutineEx2` callbacks registered by EDR drivers. The attack nulls the pointer at the target driver's slot in the 64-entry array.

Detection correlation: If ETWTI continues emitting events but Sysmon (which uses `PsSetCreateProcessNotifyRoutineEx2`) stops generating process create events, the divergence indicates callback array tampering. Genome-level indicator: ETW telemetry shows a process creating subprocesses (visible via ETWTI CREATEPROCESS or direct network events) while the expected Kernel-Process events are absent.

---

## Detection Logic (T1562)

### ETW Rate Drop Rule

```
IF:
  provider_event_rate(provider = "Microsoft-Windows-Kernel-Process", window = 30s) = 0
  AND system.uptime > 5min  [not a fresh boot]
  AND etwti.events_in_same_window > 0  [ETWTI still receiving events]
THEN:
  technique = T1562.006, confidence = 0.90, severity = CRITICAL
```

### ntdll Patching Rule

```
IF:
  etwti.PROTECTVM_LOCAL(target_address ∈ ntdll_image_range, protect = PAGE_EXECUTE_READWRITE)
  AND within 2s: etwti.WRITEVM_LOCAL(target_address ∈ [ntdll_EtwEventWrite, ntdll_EtwEventWrite + 16])
THEN:
  technique = T1562.006, confidence = 0.95, severity = CRITICAL
```

### Service Stop Rule

```
IF:
  process.create(image = sc.exe, cmdline contains stop <known_edr_service>)
  OR process.create(image = net.exe, cmdline contains stop <known_edr_service>)
THEN:
  technique = T1562.001, confidence = 0.85
```

---

## OCSF Mapping (T1562)

| OCSF Class | Class ID | Discriminating Fields | Technique Confidence |
|---|---|---|---|
| Process Activity | 1007 | `activity_id = Terminate`, `process.name in {security_tool_names}` | T1562.001 High |
| Registry Key Activity | 201001 | `reg_key.path contains \Services\<edr>\Start`, `reg_value.data = 4` | T1562.001 High |
| Memory Activity (extension) | custom | `target_address ∈ ntdll_image_range`, `activity = Protect+Write` | T1562.006 Critical |
