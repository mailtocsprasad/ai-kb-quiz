---
technique_id: T1070
technique_name: Indicator Removal
tactic: [Defense Evasion]
platform: Windows
severity: High
data_sources: [ETW-Security, ETW-Process, ETW-File, USN-Journal]
mitre_url: https://attack.mitre.org/techniques/T1070/
---

# T1070 — Indicator Removal

## Description (T1070)

T1070 Indicator Removal covers techniques that delete, clear, or alter forensic evidence of compromise to hinder incident response and avoid detection. On Windows, the primary forensic evidence stores are the Windows Event Log (`.evtx` files), the NTFS USN Change Journal (a gap-free log of file system activity), file system artifacts (prefetch, shellbags, MFT entries), and the Windows registry (LastWrite timestamps, recently-used keys). Eliminating these artifacts removes the timeline that investigators and automated detection systems rely upon to reconstruct attacker activity.

Indicator removal is typically a late-stage defense evasion action, executed after the attacker has achieved persistence or lateral movement and wants to reduce the forensic trail before exfiltration or detonation of a final payload.

---

## Windows Implementation Details (T1070)

Windows Event Log is implemented via the Windows Event Log service (`svchost.exe` hosting `wevtsvc.dll`). Event log files reside at `%SystemRoot%\System32\winevt\Logs\` and are formatted as binary `.evtx` files. The Event Log service holds exclusive locks on these files while running; direct file deletion fails with a sharing violation. Clearing a channel — the attacker's preferred approach — requires calling the `EvtClearLog` function or the `wevtutil cl <channel>` command, which causes the Event Log service to atomically truncate the `.evtx` file and write a single log-cleared event (Event ID 1102 for Security channel, Event ID 104 for System/Application). This event is the primary indicator of log clearing because the service always emits it, even if the attacker attempts to clear the Security log itself.

The NTFS USN (Update Sequence Number) Change Journal is a kernel-maintained, volume-level log of all file system operations. It is stored in `$Extend\$UsnJrnl:$J` on each NTFS volume and records every file create, write, rename, delete, and attribute change. The journal is gap-free at the kernel level and requires kernel privileges to suppress or manipulate. Attackers can delete the journal entirely (`fsutil usn deletejournal /D C:`) or manipulate the maximum journal size to force rotation. USN Journal deletion is itself logged as a file system event and requires `SeManageVolumePrivilege` (implicitly held by processes running as SYSTEM or an administrator with the right enabled).

NTFS file timestamps (`$STANDARD_INFORMATION` attribute) can be manipulated by any process that has write access to a file using the `SetFileTime` / `NtSetInformationFile(FileBasicInformation)` API. The `$FILENAME` attribute timestamps, however, are maintained by the kernel and are harder to modify from user mode — a discrepancy between `$SI` and `$FN` timestamps (known as "timestomping") is a well-documented forensic indicator of T1070.006.

Prefetch files (`%SystemRoot%\Prefetch\*.pf`) record the last eight execution times and the DLLs accessed by executables. They are created by the Windows Cache Manager when a process is first run. Deleting prefetch files removes evidence of program execution, but generating one requires a `PfDeleteFile` call via `fsutil prefetch` or direct `%SystemRoot%\Prefetch\` writes.

---

## Observable Artifacts (T1070)

- Security Event Log Event ID 1102 ("The audit log was cleared") fired from any source. This event fires unconditionally when the Security channel is cleared.
- System/Application Event Log Event ID 104 ("The event log service was stopped" or log cleared event) paired with a process that is not the Event Log service itself.
- `wevtutil.exe`, `PowerShell -Command Clear-EventLog`, or `Get-WinEvent | Remove-WinEvent` in a process command line.
- `fsutil.exe usn deletejournal` in a command line.
- `NtSetInformationFile(FileBasicInformation)` called by a non-system process to modify timestamps on recently-written malware artifacts — detectable by comparing `$SI` and `$FN` timestamps at scan time.
- Rapid deletion of many `.evtx` files or many prefetch `.pf` files from a single process in a short time window.

---

## ETW / eBPF Telemetry Signals (T1070)

### Microsoft-Windows-Security-Auditing

- **Event ID 1102**: The definitive log-clearing indicator for the Security channel. This event contains `SubjectUserName`, `SubjectDomainName`, and `SubjectLogonId`, identifying the account that cleared the log. It fires inside the Security channel itself immediately before truncation, so it may survive if the attacker clears a partial log or if a remote SIEM has already ingested it.
- **Event ID 4688** (Process Creation): `wevtutil.exe cl Security` or `cl System` in the command line is the canonical indicator. Also: `PowerShell` with `Clear-EventLog` or `Remove-EventLog`.
- **Event ID 4663** (Object Access, if auditing enabled): File access to `.evtx` files by processes other than the Event Log service (`svchost.exe` hosting `wevtsvc.dll`).

### Microsoft-Windows-Kernel-File

- **File Delete events**: The Event Log service emits ETW file-delete events when `.evtx` files are deleted while the service is stopped. Monitoring `%SystemRoot%\System32\winevt\Logs\*.evtx` for delete operations from processes other than the Event Log service provides a kernel-level log-tampering signal.
- **File Write events to Prefetch directory**: Legitimate writes come from the Cache Manager; unexpected processes writing to `%SystemRoot%\Prefetch\` indicate tampering.

### Microsoft-Windows-Kernel-Process

- **Event ID 1 (ProcessStart)**: Process creation for `wevtutil.exe`, `fsutil.exe`, `sdelete.exe`, `cipher.exe /w`, `timestomp.exe` (Metasploit artifact). The parent process context matters — these utilities launched from `cmd.exe` descended from `powershell.exe` descended from `WINWORD.EXE` is a high-confidence post-exploitation indicator.
- **Event ID 3 (ProcessStop)**: If the Event Log service (`svchost.exe -k LocalServiceNetworkRestricted`) stops unexpectedly and shortly thereafter `.evtx` files are modified, log tampering via service disruption is indicated.

### USN Journal

The USN Journal records every file system operation on NTFS volumes. For T1070 specifically:

- USN records for `.evtx` file writes or size changes from non-Event Log service processes.
- A USN record for `$Extend\$UsnJrnl` itself being deleted or truncated (indicates `fsutil usn deletejournal`).
- Timestamp changes on executable files (`USN_REASON_BASIC_INFO_CHANGE`) shortly after their creation indicate timestomping.
- Batch deletion of many files in `%SystemRoot%\Prefetch\` in under one second (physical attacker script or automated cleaner).

---

## Evasion Variants (T1070)

- **Selective log deletion**: Rather than clearing an entire channel, attackers may target specific Event IDs within a channel. The `wevtutil` tool does not support selective event deletion; this requires direct binary manipulation of the `.evtx` file format (uncommonly seen in the wild). The 1102/104 events are not generated, making detection rely on log continuity checks (gaps in Event Record IDs within a channel).
- **Log service suspension without clearing**: Stopping the Event Log service (`net stop eventlog` or `sc stop eventlog`) causes new events to be dropped. The 1102/104 events are not emitted on service stop alone, but the gap in Event Record IDs is detectable on the next service start. ETW providers that write directly (bypassing the service) still emit events; the `Microsoft-Windows-Kernel-*` providers are kernel-mode and unaffected by the user-mode Event Log service being down.
- **ETW provider disabling and session hijacking**: Discussed in T1562_impair_defenses.md. Directly disabling ETW providers suppresses telemetry at the source, leaving no log entries to remove — a more sophisticated alternative to log clearing.
- **MFT $LogFile manipulation**: The NTFS `$LogFile` transaction log records uncommitted and recent metadata changes. Clearing or corrupting `$LogFile` removes recent file operation history at the MFT level. This requires `SeManageVolumePrivilege` and direct volume access via `\\.\C:`.
- **Shadow copy deletion**: `vssadmin delete shadows /all /quiet` or `wmic shadowcopy delete` removes Volume Shadow Copy snapshots, eliminating the ability to recover previous file system states. This is commonly paired with ransomware (T1486) and post-exploitation cleanup.

---

## Detection Logic (T1070)

### Log Clearing — Primary Indicator

```
SecurityEvent 1102 OR SystemEvent 104
  → T1070.001 High (0.95) regardless of actor
```

### Wevtutil / PowerShell Log Clear

```
ProcessStart(
  (image_name = wevtutil.exe AND cmd_line MATCHES "\bcl\b|\bclear-log\b")
  OR (image_name = powershell.exe AND cmd_line MATCHES "Clear-EventLog|Remove-EventLog")
)
→ T1070.001 High (0.90)
```

### USN Journal Deletion

```
ProcessStart(
  image_name = fsutil.exe
  cmd_line MATCHES "usn.*deletejournal"
)
→ T1070 High (0.88)
```

### Timestomping

```
ETWTI SETFILEINFORMATION(FileBasicInformation)
  target_file.extension IN {.exe, .dll, .ps1, .bat, .vbs}
  AND actor.process.file.name NOT IN {explorer.exe, msiexec.exe, robocopy.exe}
  AND (new_timestamp < file_create_time OR new_timestamp mismatch $SI vs $FN)
→ T1070.006 Medium (0.70)
```

### Shadow Copy Deletion

```
ProcessStart(
  (image_name = vssadmin.exe AND cmd_line MATCHES "delete.*shadow")
  OR (image_name = wmic.exe AND cmd_line MATCHES "shadowcopy.*delete")
  OR (image_name = powershell.exe AND cmd_line MATCHES "Win32_ShadowCopy.*Delete")
)
→ T1070.004 High (0.88) — frequently co-occurring with T1486
```

---

## Sub-Techniques (T1070)

### T1070.001 — Clear Windows Event Logs

The attacker clears one or more Windows Event Log channels using `wevtutil`, PowerShell cmdlets, or the `EvtClearLog` API. Event ID 1102 (Security) or 104 (other channels) fires on each clear operation. The Security channel is the most commonly targeted because it records authentication, process creation, and privilege use events that would otherwise document the intrusion timeline.

### T1070.004 — File Deletion

Files related to attacker tools, staging directories, or dropped payloads are deleted after use. Secure deletion (overwriting with random data before deletion) prevents file carving from disk image; standard deletion leaves the file's content recoverable until the disk sectors are reused. ETW File Delete events and USN Journal records capture the deletion even when the file content is gone.

### T1070.006 — Timestomping

Modification times on malicious files are set to values matching surrounding legitimate files to evade timeline-based analysis. The `SetFileTime` API modifies the `$STANDARD_INFORMATION` attribute timestamps but not the `$FILENAME` attribute timestamps (which require a kernel call). A `$SI`/`$FN` timestamp discrepancy is detectable by any tool that reads both MFT attributes.

---

## Related Techniques (T1070)

- T1562.002 (Disable Windows Event Logging) — Suppresses log generation vs. removing existing logs
- T1486 (Ransomware) — Shadow copy deletion frequently precedes encryption
- T1003 (Credential Dumping) — Log clearing often follows LSASS access to remove Event ID 4656/4663 audit records
- T1059 (Scripting) — Most log clearing uses PowerShell or cmd.exe wrappers

---

## OCSF Mapping (T1070)

| OCSF Class | Class ID | Discriminating Fields | Technique Confidence |
|---|---|---|---|
| Process Activity | 1007 | `process.file.name = wevtutil.exe`, `process.cmd_line` matches clear command | T1070.001 High |
| File Activity | 1001 | `activity_id = Delete`, `file.path` in winevt/Logs or Prefetch, non-service actor | T1070.001/004 High |
| Security Finding | 2001 | Event ID 1102 forwarded as security finding | T1070.001 Critical |
