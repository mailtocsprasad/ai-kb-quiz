---
technique_id: T1574
technique_name: Hijack Execution Flow
tactic: [Defense Evasion, Persistence, Privilege Escalation]
platform: Windows
severity: High
data_sources: [ETW-Process, ETW-File, ETW-Registry]
mitre_url: https://attack.mitre.org/techniques/T1574/
---

# T1574 — Hijack Execution Flow

## Description (T1574)

T1574 Hijack Execution Flow covers techniques that redirect a legitimate executable's code loading behavior to instead load attacker-controlled code. Rather than creating a new malicious process, the attacker plants a malicious DLL or modifies a load path such that an existing trusted process loads and executes attacker code as part of its normal startup. Because the malicious code executes inside a trusted process, it inherits that process's security context, network identity, and reputation — bypassing allow-list controls, firewall rules, and parent-process checks keyed on image name.

The Windows DLL loading model is the primary attack surface. When a process calls `LoadLibrary` or imports a DLL via its import address table, the loader walks a defined search order to resolve the DLL name to a filesystem path. Placing a malicious DLL earlier in this search order than the legitimate DLL causes the malicious version to be loaded instead.

---

## Windows Implementation Details (T1574)

The Windows DLL search order for most processes (when `LOAD_WITH_ALTERED_SEARCH_PATH` is not specified and the process has not called `SetDllDirectory`) is:
1. The directory containing the loading executable
2. `%SystemRoot%\System32`
3. `%SystemRoot%\System16` (legacy)
4. `%SystemRoot%`
5. The current working directory (CWD)
6. Directories listed in the `PATH` environment variable

DLL search order hijacking (T1574.001) plants a malicious DLL with the same name as an expected DLL in a location earlier in this list — most commonly in the directory of the loading executable (#1), which is often user-writable for applications installed in `%ProgramFiles%` subdirectories or `%AppData%`. Alternatively, if the CWD is a user-controlled directory (e.g., a download folder), placing the DLL there can intercept loads for DLLs that the target application does not have in its own directory.

DLL side-loading (T1574.002) exploits applications that specify their DLL dependencies using relative or unqualified paths and do not use Safe DLL Search Mode (`SetDllDirectory("")` or the `IMAGE_DLLCHARACTERISTICS_FORCE_INTEGRITY` flag). An attacker places a renamed malicious DLL alongside a legitimate application binary (often one that the OS or a popular product trusts for auto-elevation or code signing), causing the application to load the malicious DLL when it starts. The legitimate application binary is untouched; only the accompanying malicious DLL is new.

The `Microsoft-Windows-Kernel-File` provider records every DLL load via Image Load events. The kernel's `PsSetLoadImageNotifyRoutine` callback fires on every image map, carrying the file path and process context. When a DLL loads from an unexpected path — particularly from the executable's own directory for a DLL that should come from `System32` — this discrepancy is detectable.

Path interception (T1574.004) places a malicious binary earlier in the `PATH` environment variable than the legitimate binary, or creates a malicious executable in a location searched before the intended one. Services that run command names without full paths are particularly vulnerable.

---

## Observable Artifacts (T1574)

- A DLL file created in the same directory as a legitimate application binary, bearing the name of a DLL that the application imports from `System32` — particularly when the creator process is not the application's own installer.
- An Image Load event where the same DLL name loads from two different paths in the same process (the malicious path shadowing the legitimate one is less common since only one loads, but the load path itself is the indicator).
- A DLL loading from `%APPDATA%`, `%TEMP%`, or the CWD with a name matching a System32 DLL (e.g., `version.dll`, `dwmapi.dll`, `cryptbase.dll` in unusual locations).
- A side-loaded binary placed alongside a legitimate application: `<AppDir>\<legitimate.exe>` + `<AppDir>\<imported_dll_name>.dll` where the DLL did not exist before and was recently created.
- Registry `AppPaths` or `AppInit_DLLs` values modified to include additional DLL paths.

---

## ETW / eBPF Telemetry Signals (T1574)

### Microsoft-Windows-Kernel-File

- **Image Load events (kernel callback)**: Every DLL load fires an image load notification callback. The path field exposes the fully-qualified filesystem path of the loaded DLL. Comparing this path against an expected-path baseline (DLLs that should only load from `System32`) identifies hijacked loads. Key DLLs frequently targeted for hijacking: `version.dll`, `dbghelp.dll`, `dwmapi.dll`, `cryptbase.dll`, `uxtheme.dll`, `winhttp.dll`, `wtsapi32.dll`.
- **File Create events**: A non-installer process creating a `.dll` file in a directory containing a signed Microsoft or popular application executable is a strong side-loading setup indicator. Correlating the new DLL's name against the host application's import table (available from PE parsing) confirms the hijack target.
- **File Rename events**: Attackers may stage a malicious DLL under a benign name and rename it to the target DLL name just before execution, evading content-based static detection of the original filename.

### Microsoft-Windows-Kernel-Registry

- **RegSetValue** targeting `HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Windows\AppInit_DLLs`: Any write from a non-system process. AppInit_DLLs causes the listed DLLs to be injected into every User32-loading process — a form of DLL injection masquerading as a configuration entry.
- **RegSetValue** targeting `HKLM\SYSTEM\CurrentControlSet\Control\Session Manager\KnownDLLs`: This key lists DLLs that bypass the search order entirely (they are always loaded from System32). Adding a name to this list from user mode does not actually add it to the known DLL cache (that requires a reboot and kernel validation), but modification of the key itself is anomalous.
- **AppPaths registry key writes**: `HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\<exe>` entries that redirect a binary name to a different path.

### Microsoft-Windows-Kernel-Process

- **Event ID 1 (ProcessStart)**: The process that was injected into via side-loading will appear as the actor of subsequent malicious actions. The parent image is the legitimate host application, but the behavior (network connections, registry writes, additional process spawns) is unexpected for that host. Behavioral anomaly on the `actor.process.file.name` field — known binary behaving unexpectedly — is the residual signal after the DLL is loaded.

---

## Evasion Variants (T1574)

- **Proxying all exports**: A malicious DLL implements all the exported functions of the DLL it replaces as forwarding stubs to the real DLL (loaded from `System32` directly), while also executing malicious code in `DllMain`. The application functions correctly, defeating behavioral anomaly detection based on the host application crashing or misbehaving after the DLL loads.
- **Signed malicious DLL**: Attackers use a legitimately signed DLL (acquired through code signing certificate theft or supply chain compromise) to bypass signature-based DLL validation. Some EDR products skip hooking signed DLLs; side-loading a signed malicious DLL into a trusted process may evade user-mode hook installation.
- **Manifest-directed DLL side-loading**: Windows SxS (Side-by-Side) assembly manifests can redirect a DLL load to a specific path via `<assemblyIdentity>` entries in `.manifest` files. Placing a malicious manifest alongside an executable can redirect its DLL loads without touching the executable itself.
- **CWD manipulation**: Some LOLBins (living-off-the-land binaries) load DLLs from the CWD without checking for them in System32 first. Launching the LOLBin from a directory under attacker control (via a spear-phishing attachment that sets the initial directory) places the malicious DLL in the search path.
- **PATH environment variable injection**: Adding a user-writable directory to the beginning of the PATH variable causes unqualified command-line program names to resolve to attacker binaries. This persists across shell sessions if the variable is set in the user's environment block (`HKCU\Environment`).

---

## Detection Logic (T1574)

### DLL Loaded from Unexpected Path

```
ImageLoad(
  dll_name IN known_system32_dll_set  -- e.g., version.dll, dbghelp.dll, etc.
  AND load_path NOT MATCHES "C:\Windows\System32\*"
             AND NOT MATCHES "C:\Windows\SysWOW64\*"
             AND NOT MATCHES "C:\Windows\WinSxS\*"
)
→ T1574.001/002 High (0.85) — load path mismatch for System32 DLL
```

### Suspicious DLL Placement

```
SEQUENCE within 300 seconds:
  Step 1: FileCreate(
    target.extension = ".dll"
    target.directory = same directory as known_trusted_application.exe
    actor.process.file.name NOT IN {msiexec.exe, <app_installer>, trustedinstaller.exe}
  )
  Step 2: ImageLoad(
    dll_path = target.path from Step 1
    hosting_process.file.name = known_trusted_application.exe
  )
→ T1574.002 High (0.90)
```

### AppInit_DLLs Write

```
RegSetValue(
  KeyName MATCHES "*AppInit_DLLs*"
  DataValue ≠ ""
  actor NOT IN {trustedinstaller.exe, system_update_services}
)
→ T1574 High (0.80)
```

---

## Sub-Techniques (T1574)

### T1574.001 — DLL Search Order Hijacking

Exploits the loader's search order by placing a same-named DLL in a directory earlier in the search path. Requires write access to that directory. Most commonly exploited for applications in `%ProgramFiles%` that load DLLs non-absolutely, or for applications that load optional DLLs from the CWD.

### T1574.002 — DLL Side-Loading

Places a malicious DLL alongside a legitimate (often signed) application to be loaded by that application. The application binary is unmodified; it acts as an unwitting launcher for the malicious DLL. Frequently used for persistence by coupling with a legitimate application that auto-starts (via ASEP).

### T1574.007 — Path Interception by PATH Environment Variable

Inserts a user-controlled directory into the PATH environment variable before System32. Subsequent unqualified command executions from that user's shell resolve to attacker binaries. Requires registry write to `HKCU\Environment` (achievable at medium integrity).

### T1574.011 — Services Registry Permissions Weakness

A service's registry key or binary path is writable by a lower-privileged user. Modifying the `ImagePath` value substitutes the malicious binary. The SCM launches the malicious binary at the next service start in the service's configured account context.

---

## Related Techniques (T1574)

- T1547 (Boot or Logon Autostart Execution) — DLL side-loading combined with ASEP achieves persistence
- T1548 (Abuse Elevation Control Mechanism) — Side-loading into auto-elevating binaries provides privilege escalation
- T1055 (Process Injection) — DLL side-loading is a form of code injection via the OS loader
- T1218 (System Binary Proxy Execution) — LOLBins used for DLL hijacking often overlap with LOLBin proxying

---

## OCSF Mapping (T1574)

| OCSF Class | Class ID | Discriminating Fields | Technique Confidence |
|---|---|---|---|
| Module Activity | 1008 | `module.file.path` not in System32 for known system DLL name | T1574.001/002 High |
| File Activity | 1001 | `activity_id = Create`, `.dll` in application directory, non-installer actor | T1574.002 Medium–High |
| Registry Value Activity | 201003 | `reg_key.path` matches AppInit_DLLs, non-empty write | T1574 High |
