---
technique_id: T1548
technique_name: Abuse Elevation Control Mechanism
tactic: [Defense Evasion, Privilege Escalation]
platform: Windows
severity: High
data_sources: [ETW-Process, ETW-Registry, ETW-File, ETW-Security]
mitre_url: https://attack.mitre.org/techniques/T1548/
---

# T1548 — Abuse Elevation Control Mechanism

## Description (T1548)

T1548 Abuse Elevation Control Mechanism covers techniques that bypass Windows User Account Control (UAC) or otherwise manipulate the elevation infrastructure to obtain higher privilege without triggering a UAC dialog box. UAC divides every administrator-group account into two tokens: a filtered standard-user token used for most operations, and a full administrator token reserved for explicitly elevated tasks. Applications that require elevation carry an `asInvoker`, `highestAvailable`, or `requireAdministrator` auto-elevation manifest attribute. When a process requests elevation, the AppInfo service (`appinfo.dll` in `svchost.exe`) evaluates the request: binaries located in trusted system directories and digitally signed by Microsoft may auto-elevate without a UAC prompt.

UAC bypass techniques exploit these auto-elevation rules by either: hijacking the execution flow of an auto-elevating trusted binary so that it executes attacker code at high integrity; or abusing COM objects that auto-elevate and can be instantiated from a medium-integrity process to write attacker payloads into privileged locations. Successful UAC bypass elevates the attacker to a full administrator token without the user seeing any UAC dialog.

---

## Windows Implementation Details (T1548)

UAC integrity levels are implemented via mandatory labels in the access token. Every process and object carries a `TOKEN_MANDATORY_LABEL` structure containing a `SID` that encodes the integrity level: `S-1-16-4096` (Low), `S-1-16-8192` (Medium), `S-1-16-12288` (High), `S-1-16-16384` (System). The kernel enforces mandatory access control via `SeAccessCheck` — a process cannot write to objects at a higher integrity level than its own.

Auto-elevation is evaluated by the AppInfo service. The `appinfo.dll` `AiIsElevationRequired` function checks three conditions before granting silent elevation: the binary must be located under `%SystemRoot%` or `%ProgramFiles%`, it must be signed by the Windows certificate chain, and its manifest must specify `requireAdministrator` or `highestAvailable` with an appropriate `autoElevate` attribute. If all three conditions are met, the binary runs as High integrity without a UAC prompt.

Registry-based UAC bypasses work because several auto-elevating binaries (e.g., `fodhelper.exe`, `eventvwr.exe`, `sdclt.exe`) read registry keys from `HKCU` — the current user's hive — to determine which program to open or which verb to execute. Since `HKCU` is writable by medium-integrity processes, an attacker can inject a malicious executable path into `HKCU` before launching the auto-elevating binary, causing that binary to execute the attacker payload at high integrity.

COM-based UAC bypasses instantiate a COM object whose server is a high-integrity auto-elevating system binary. The elevated COM server then acts on behalf of the caller, performing file writes or registry operations that the medium-integrity caller could not perform directly. `ICMLuaUtil` (exposed by `cmstplua.dll`) and the `IFileOperation` COM interface (elevated via shell auto-elevation) are canonical examples.

---

## Observable Artifacts (T1548)

- A medium-integrity process (`svchost.exe` child or shell child) writing to a `HKCU` registry path that an auto-elevating system binary is known to read (`HKCU\Software\Classes\ms-settings\shell\open\command`, `HKCU\Software\Classes\Folder\shell\open\command`, etc.), followed within a short window by the launch of that auto-elevating binary.
- A medium-integrity process writing to `HKCU\Software\Classes\<ProgID>\shell\open\command` (file type verb override) targeting a payload, followed by a system binary executing as High integrity.
- Spawning of a high-integrity child process from a medium-integrity parent — particularly if the parent is a user-mode tool like `cmd.exe`, `powershell.exe`, or a scripting engine. Normal elevation paths produce a high-integrity child whose parent is `consent.exe` or the AppInfo service; a direct medium→high lineage without `consent.exe` in the chain is anomalous.
- `eventvwr.exe`, `fodhelper.exe`, `sdclt.exe`, `cmstp.exe`, `computerdefaults.exe`, or `wsreset.exe` launching a process other than their expected child.

---

## ETW / eBPF Telemetry Signals (T1548)

### Microsoft-Windows-Kernel-Process

- **Event ID 1 (ProcessStart)**: The key field is the integrity level of the newly created process relative to its parent. When a High-integrity process has a Medium-integrity parent without `consent.exe` appearing in the ancestry, UAC bypass is indicated. The event payload exposes `TokenElevationType` (1 = Default, 2 = Full, 3 = Limited); a process with `TokenElevationType = 2` (fully elevated) spawned from a non-elevated context is the primary indicator.
- The parent/child chain `medium-integrity-process → auto-elevating-binary → high-integrity-payload` is the canonical UAC bypass sequence. Comparing Process Start events by PID parent chains with expected elevation paths yields reliable detection.

### Microsoft-Windows-Kernel-Registry

- **RegSetValue** targeting HKCU paths associated with known bypass gadgets:
  - `HKCU\Software\Classes\ms-settings\shell\open\command` (`fodhelper.exe` bypass)
  - `HKCU\Software\Classes\Folder\shell\open\command` (`eventvwr.exe` bypass)
  - `HKCU\Software\Classes\exefile\shell\open\command` (file type override bypass)
  - `HKCU\Environment\windir` (`schtasks.exe` WINDIR environment hijack)
  - `HKCU\Environment\UserInitMprLogonScript` (logon script injection)
- When any of these key paths is written by a process not in the known-good installer set, and the write is followed within 30 seconds by a launch of the corresponding auto-elevating binary, confidence for T1548.002 is High.

### Microsoft-Windows-Security-Auditing

- **Event ID 4688** (Process Creation, with command line auditing enabled): Captures the full command line of every new process. The auto-elevating binary appears in a 4688 event at high integrity; correlating its preceding 4688 event for the medium-integrity parent and any intermediate registry writes builds the bypass chain.
- **Event ID 4673** (Privileged Service Called): Fires when a process accesses a privileged object. Useful for detecting AppInfo service calls that precede auto-elevation.

---

## Evasion Variants (T1548)

- **DiskCleanup scheduled task abuse**: The `SilentCleanup` scheduled task runs as the highest available privilege of the current user and is writable via `HKCU\Environment\windir`. Inserting `cmd /K <payload>&&` into `windir` causes the task to execute the payload at high integrity. No auto-elevating binary is launched — the attack runs entirely through the Task Scheduler service.
- **Fodhelper + DelegateExecute**: Some ProgID verb registrations in HKCU trigger execution via the `DelegateExecute` value rather than `(Default)`, allowing COM-based elevation without a visible command-line trace.
- **Token parent spoofing (PPID spoofing)**: Launching the elevated process with a spoofed parent PID (via `CreateProcess` with `PROC_THREAD_ATTRIBUTE_PARENT_PROCESS`) makes the high-integrity child appear to be the child of a trusted parent, hiding the actual medium-integrity launchers from parent-chain analysis. Detected by comparing the `EPROCESS.InheritedFromUniqueProcessId` field with actual handle relationships.
- **ICMLuaUtil COM interface**: Instantiated via a moniker that bypasses normal COM security checks. The medium-integrity process calls `CoCreateInstance(CLSID_CMSTPLUA)` and uses the `ICMLuaUtil::ShellExec` method to launch an arbitrary process at high integrity.
- **Cleanup via DelegateExecute → process exit**: Some bypass techniques write the HKCU key, launch the auto-elevating binary, wait for execution, and then delete the HKCU key before detection tools enumerate the registry. USN Journal monitoring can detect the key write even if the key is deleted before the next registry scan.

---

## Detection Logic (T1548)

### UAC Bypass HKCU Write + Auto-Elevating Binary Launch

```
SEQUENCE within 60 seconds:
  Step 1: RegSetValue(
    KeyName MATCHES "HKCU\Software\Classes\*\shell\open\command"
             OR "HKCU\Environment\windir"
             OR "HKCU\Environment\UserInitMprLogonScript"
    actor.process.integrity_level = Medium
  )
  Step 2: ProcessStart(
    image_name IN {fodhelper.exe, eventvwr.exe, sdclt.exe,
                   cmstp.exe, computerdefaults.exe, wsreset.exe}
    process.integrity_level = High
    parent.integrity_level = Medium
  )
→ T1548.002 High (0.92)
```

### Unexpected High-Integrity Child

```
ProcessStart(
  process.integrity_level = High
  parent.process.integrity_level = Medium
  parent.process.file.name NOT IN {consent.exe, msiexec.exe}
)
→ T1548 Medium (0.70) — investigate elevation path
```

---

## Sub-Techniques (T1548)

### T1548.002 — Bypass User Account Control

The primary Windows sub-technique. UAC bypass techniques use registry hijacking, COM object abuse, or auto-elevating binary exploitation to silently elevate from medium to high integrity. The distinguishing characteristic at the event level is the absence of `consent.exe` in the process creation chain despite a medium→high integrity transition.

As of Windows 10 and 11, many historically reliable UAC bypass gadgets (`eventvwr.exe`, `sdclt.exe`) have been patched or the registry paths they relied on have been protected. However, `fodhelper.exe` and COM-based approaches remain effective on unpatched systems. The attack surface expands with third-party installers that implement their own auto-elevation via AppInfo.

### T1548.004 — Elevated Execution with Prompt

Some malware deliberately triggers a UAC prompt rather than bypassing it, relying on social engineering to convince the user to approve elevation. This technique is trivially detectable by `consent.exe` spawning a user dialog, but the subsequent high-integrity process launch is not intrinsically malicious — context and payload analysis are required.

---

## Related Techniques (T1548)

- T1134 (Access Token Manipulation) — Full token theft can replace UAC bypass as a privilege escalation path
- T1547.001 (Registry Run Keys) — HKCU key writes for UAC bypass share infrastructure with ASEP writes
- T1574 (Hijack Execution Flow) — DLL hijacking within an auto-elevating binary is a variant of this technique
- T1218 (System Binary Proxy Execution) — Auto-elevating LOLBins overlap with UAC bypass gadgets

---

## OCSF Mapping (T1548)

| OCSF Class | Class ID | Discriminating Fields | Technique Confidence |
|---|---|---|---|
| Registry Value Activity | 201003 | `reg_key.path` matches bypass gadget path, `actor.process.integrity_level = Medium` | T1548.002 High |
| Process Activity | 1007 | `process.integrity_level = High`, `parent.integrity_level = Medium`, no consent.exe in chain | T1548.002 High |
| Process Activity | 1007 | `process.file.name` in auto-elevating binary set, unexpected child command | T1548.002 Medium |
