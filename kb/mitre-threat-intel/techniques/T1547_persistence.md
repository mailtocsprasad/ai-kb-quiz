---
technique_id: T1547
technique_name: Boot or Logon Autostart Execution
tactic: [Persistence, Privilege Escalation]
platform: Windows
severity: High
data_sources: [ETW-Registry, ETW-Process, ETW-File]
mitre_url: https://attack.mitre.org/techniques/T1547/
---

# T1547 — Boot or Logon Autostart Execution

## Description (T1547)

T1547 Boot or Logon Autostart Execution covers mechanisms that cause attacker-controlled code to run automatically when the system boots or a user logs on. Windows provides a large number of persistence locations — registry keys, startup folders, service registrations, scheduled tasks, and driver load paths — that the OS or the shell evaluates during initialization. Abusing these locations allows malware to survive system restarts without requiring re-exploitation; the persistence mechanism re-executes the payload on each boot or logon cycle. Many ASEP (Auto-Start Extensibility Point) locations are evaluatable from user context, making them accessible to unprivileged malware, though higher-privilege ASEPs (services, drivers, boot-execute entries) require administrator or SYSTEM context.

The kernel itself is not involved in most ASEP evaluations; rather, the Windows Session Manager (`smss.exe`), the Service Control Manager (`services.exe`), and the Windows Shell (`explorer.exe`) each evaluate distinct sets of persistence locations during their initialization sequences. This distributed evaluation model means that detection must span multiple registry hive paths and process hierarchies.

---

## Windows Implementation Details (T1547)

The Windows registry stores persistence entries across multiple hives. The `HKLM` (HKEY_LOCAL_MACHINE) hive is system-wide and requires at minimum `SeRestorePrivilege` to write; the `HKCU` (HKEY_CURRENT_USER) hive is per-user and writable by any process running in that user's context. This distinction matters for telemetry: a standard-user process writing to `HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Run` should be flagged immediately, because that requires elevation.

The Session Manager (`smss.exe`) — the first user-mode process started by the Windows kernel — reads `HKLM\SYSTEM\CurrentControlSet\Control\Session Manager\BootExecute` and executes each listed program before any other subsystem initializes. This is the earliest possible user-mode ASEP and runs before security products are loaded; entries here have high evasion potential. The default value is `autocheck autochk *`.

The Service Control Manager reads `HKLM\SYSTEM\CurrentControlSet\Services\*` to enumerate drivers and services. Driver entries with `Start = 0` (Boot) or `Start = 1` (System) load before user-mode processes, including EDR agents. This makes kernel-mode driver persistence (T1547.010) a powerful bypass vector.

The Windows Shell evaluates `Run` and `RunOnce` keys in both HKLM and HKCU during logon:
- `HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Run`
- `HKCU\SOFTWARE\Microsoft\Windows\CurrentVersion\Run`
- `HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\RunOnce`
- `HKCU\SOFTWARE\Microsoft\Windows\CurrentVersion\RunOnce`

Startup folder paths are also evaluated:
- `%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup` (per-user)
- `%ProgramData%\Microsoft\Windows\Start Menu\Programs\Startup` (all-users, requires admin to modify)

---

## Observable Artifacts (T1547)

- A registry write to any recognized ASEP key from a process whose image path is not a known system binary or installer. Specifically: `RegSetValue` or `RegCreateKey` targeting `...\CurrentVersion\Run*`, `BootExecute`, or `...\Services\*` from `powershell.exe`, `wscript.exe`, `mshta.exe`, or a process running from `%TEMP%` or `%APPDATA%`.
- A new file placed in a Startup folder from a non-installer process.
- A service registry key created with `ImagePath` pointing to a non-standard binary location (`%TEMP%`, `%APPDATA%`, or an unusual path outside `System32`).
- A `BootExecute` value modified to include additional entries beyond the default `autocheck autochk *`.
- A `RunOnce` key set with a `!`-prefixed value (the `!` prefix causes the entry to execute and then delete itself, a common technique for one-time payloads that leave minimal trace).

---

## ETW / eBPF Telemetry Signals (T1547)

### Microsoft-Windows-Kernel-Registry

This provider supplies the primary telemetry stream for ASEP detection.

- **RegSetValue events**: Fires on every successful registry value write. Fields: `KeyName` (full path), `ValueName`, `Type`, `DataSize`. The critical detection is `KeyName` matching any ASEP path AND `actor.process.file.name` not in an expected installer/update allowlist.
- **RegCreateKey events**: A new service or run-key subkey creation from a non-system process warrants investigation.
- **Event ID 4657 (Security Auditing)**: Fires when a registry value audit entry matches, if auditing is configured. Less reliable for real-time detection since auditing is not always enabled; use ETW-Registry as the primary signal.

### Microsoft-Windows-Kernel-Process

- **Event ID 1 (ProcessStart)**: When a process starts whose parent is `explorer.exe` or `userinit.exe` and whose image path matches a value in a Run key, this confirms ASEP execution. Comparing the parent chain with known shell initialization parents identifies persistence-triggered launches.
- **Event ID 4 (ImageLoad)**: A driver load event for a binary not in `System32\drivers\` or a signed driver load from an unexpected path warrants BYOVD investigation (see T1068).

### Microsoft-Windows-Kernel-File

- **File Create/Write events** targeting Startup folder paths from a non-installer process. The file name and extension (`.lnk`, `.exe`, `.vbs`, `.bat`) provide secondary classification signals.

---

## Evasion Variants (T1547)

- **WOW6432Node redirection**: On 64-bit Windows, 32-bit processes writing to `HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Run` are silently redirected to `HKLM\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Run`. Some EDR products only monitor the native path; both must be covered.
- **UserInitMprLogonScript**: `HKCU\Environment\UserInitMprLogonScript` is evaluated by `userinit.exe` and executes a script at logon. Less commonly monitored than standard Run keys.
- **AppInit_DLLs**: `HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Windows\AppInit_DLLs` causes the listed DLLs to be loaded into every process that loads `User32.dll`. This has been restricted since Windows 8 (requires `LoadAppInit_DLLs = 1` and Secure Boot disables it entirely), but remains observable in older environments.
- **COM object hijacking**: Writing a CLSID to `HKCU\SOFTWARE\Classes\CLSID\{<guid>}\InprocServer32` hijacks a COM instantiation call from a privileged process. The HKCU path takes priority over HKCR without requiring elevation.
- **Image File Execution Options (IFEO) debugger shim**: `HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Image File Execution Options\<exe>\Debugger` causes the listed debugger to launch in place of the target executable. Attackers set this to their payload path targeting commonly-executed system binaries.
- **Startup folder `.lnk` shortcut**: Placing a shortcut file rather than a binary reduces hash-based detection because the `.lnk` is small and its target can be buried in a benign-looking location.

---

## Detection Logic (T1547)

### Registry ASEP Write Heuristic

```
RegSetValue(
  KeyName MATCHES "*\CurrentVersion\Run*"
    OR KeyName MATCHES "*\Services\*" AND ValueName = "ImagePath"
    OR KeyName MATCHES "*BootExecute*"
    OR KeyName MATCHES "*UserInitMprLogonScript*"
    OR KeyName MATCHES "*AppInit_DLLs*"
    OR KeyName MATCHES "*IFEO*\Debugger"
) AND
actor.process.file.name NOT IN allowed_installer_set
→ T1547 Medium (0.70)
```

Raise to High (0.88) if actor process image path contains `%TEMP%`, `%APPDATA%`, or any user-writable non-standard directory.

### Startup Folder Write

```
FileCreate OR FileWrite
  target.path MATCHES "*\Start Menu\Programs\Startup\*"
  AND actor.process.file.name NOT IN {msiexec.exe, setup.exe, install.exe}
→ T1547.001 Medium (0.65)
```

### IFEO Debugger Pivot

```
RegSetValue(
  KeyName MATCHES "*Image File Execution Options\*\Debugger"
  AND DataValue NOT IN {vsjitdebugger.exe, drwtsn32.exe}
)
→ T1547 High (0.85) — potential IFEO hijack
```

---

## Sub-Techniques (T1547)

### T1547.001 — Registry Run Keys / Startup Folder

The most common persistence mechanism. Run key values execute at each logon; RunOnce values execute once and are deleted. Startup folder shortcuts achieve the same effect without requiring registry modification.

Key distinction: `HKLM` Run keys require elevation and execute for all users; `HKCU` Run keys run in the current user's context without elevation. Malware targeting stealth often prefers `HKCU` to avoid triggering elevation-required hooks.

### T1547.009 — Shortcut Modification

An existing `.lnk` shortcut (particularly on the Desktop or in Start Menu) is modified to point to attacker payload while retaining its original appearance. The modification date change on the shortcut file is the primary observable artifact. USN Journal tracks `.lnk` write operations with high fidelity.

### T1547.010 — Kernel Modules and Extensions (Driver Persistence)

A malicious driver is registered as a boot-start or system-start service in `HKLM\SYSTEM\CurrentControlSet\Services\`. The driver loads before EDR agents. `Microsoft-Windows-CodeIntegrity` events expose driver load failures (unsigned or revoked certificate), which can paradoxically indicate a BYOVD attempt if the failure is immediately followed by a successful load via a vulnerable signed driver.

### T1547.012 — Print Processors

A malicious DLL is registered as a print processor under `HKLM\SYSTEM\CurrentControlSet\Control\Print\Environments\Windows x64\Print Processors\`. The Spooler service (`spoolsv.exe`) loads it at startup. This ASEP persists across reboots and is less scrutinized than Run keys.

---

## Related Techniques (T1547)

- T1543 (Create or Modify System Process) — Service creation overlaps with driver persistence
- T1548 (Abuse Elevation Control Mechanism) — Elevation often precedes HKLM ASEP writes
- T1562.001 (Disable or Modify Tools) — Persistence mechanisms targeting EDR disable paths may pair with ASEP writes
- T1574 (Hijack Execution Flow) — DLL hijacking can be combined with ASEP-triggered executables

---

## OCSF Mapping (T1547)

| OCSF Class | Class ID | Discriminating Fields | Technique Confidence |
|---|---|---|---|
| Registry Value Activity | 201003 | `activity_id = Set`, `reg_key.path` matches ASEP pattern, `actor.process.file.path` non-system | T1547 Medium–High |
| File Activity | 1001 | `activity_id = Create`, `file.path` in Startup folder, actor not installer | T1547.001 Medium |
| Process Activity | 1007 | `activity_id = Launch`, `process.parent_process.file.name = explorer.exe`, launch path from ASEP | T1547 confirmation |
