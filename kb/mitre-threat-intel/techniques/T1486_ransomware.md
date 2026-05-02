---
technique_id: T1486
technique_name: Data Encrypted for Impact
tactic: [Impact]
platform: Windows
severity: Critical
data_sources: [ETW-File, ETW-Process, ETW-Network, ETW-Registry]
mitre_url: https://attack.mitre.org/techniques/T1486/
---

# T1486 — Data Encrypted for Impact (Ransomware)

## Description (T1486)

T1486 Data Encrypted for Impact represents adversaries encrypting files on target systems to render them inaccessible, typically for extortion. Modern ransomware operations combine multiple MITRE techniques: initial access (T1566 phishing or T1190 public-facing application exploitation), lateral movement (T1021), discovery (T1082, T1135), credential theft (T1003), privilege escalation (T1068 or T1134), and finally encryption (T1486) combined with defense evasion (T1562). The encryption phase itself is highly visible in ETW file I/O telemetry, making it one of the most detectable techniques if the sensor is running.

---

## Windows Implementation Details (T1486)

### Encryption Execution Pattern

Modern ransomware typically follows a five-stage execution pattern detectable in the ai-procwatch-mcp genome:

**Stage 1 — Enumeration**: Ransomware recursively enumerates the filesystem using `FindFirstFile` / `FindNextFile` (Win32) or `NtQueryDirectoryFile` (native). This generates a high-rate burst of ETW Kernel-File `IRP_MJ_DIRECTORY_CONTROL` events. The characteristic pattern is: a single process calling `NtQueryDirectoryFile` on hundreds of directories in rapid succession, often starting from user profile directories (`C:\Users\`) or mapped network shares.

**Stage 2 — Shadow Copy Deletion**: Before beginning encryption, most ransomware families delete Volume Shadow Copies to prevent easy recovery. Common methods:
- `vssadmin.exe delete shadows /all /quiet` — spawned as a child process
- `wmic.exe shadowcopy delete` — WMI-based deletion
- `PowerShell.exe Get-WmiObject Win32_ShadowCopy | Remove-WmiObject`
- COM-based VSS deletion via `IVssCoordinator` directly (no child process)

VSS deletion via child process is detectable as a process creation event. COM-based VSS deletion appears as WMI activity and IPC connections to the VSS service.

**Stage 3 — Encryption Loop**: The ransomware opens each target file, reads its content, encrypts it (typically AES-256 or ChaCha20), and writes the ciphertext back. This generates a characteristic IRP_MJ_READ + IRP_MJ_WRITE flood. Each file operation involves:
- `NtCreateFile` (open for read/write, GENERIC_READ | GENERIC_WRITE)
- `NtReadFile` — read original content
- Encryption in process memory (no ETW signal)
- `NtWriteFile` — write encrypted content
- `NtSetInformationFile(FileRenameInformation)` or `NtCreateFile` with new extension — rename to encrypted extension (e.g., `.locked`, `.enc`, `.WNCRY`)

**Stage 4 — Ransom Note Drop**: Write `README.txt` or `HOW_TO_DECRYPT.html` to each directory visited.

**Stage 5 — Self-Deletion or Persistence**: Some families delete themselves; others maintain persistence for communication with C2.

### Volume Shadow Copy Deletion Details

`vssadmin.exe delete shadows /all /quiet` executes through COM interfaces to the Volume Shadow Copy Service (VSS). The VSS service exposes `IVssCoordinator` and `IVssAdmin` COM interfaces. When `vssadmin` calls these interfaces, the VSS service enumerates all shadow copies and calls `DeleteSnapshot` on each. This generates ETW Registry events (VSS stores shadow copy metadata in `HKLM\SYSTEM\CurrentControlSet\Services\VSS`) and ETW process creation events for `vssadmin.exe`.

Network Shares: Many ransomware families enumerate and encrypt network shares before or alongside local files. This produces ETW-Network events (SMB connections to the share server) combined with the ETW-File write flood pattern.

---

## Observable Artifacts (T1486)

- **High-frequency file rename events**: ETW Kernel-File events for `IRP_MJ_SET_INFORMATION (FileRenameInformation)` at a rate > 10 per second from a single process, all targeting user data directories.
- **Extension change pattern**: File renames where the original extension (`*.docx`, `*.xlsx`, `*.pdf`, `*.jpg`) is replaced with an unknown or ransomware-specific extension. This is detectable from the filename fields in ETW file rename events.
- **Write entropy increase**: Files written by the ransomware process have significantly higher entropy than the original files. While entropy analysis requires reading file content (not directly from ETW metadata), a signature of write patterns — write to same offset repeatedly, same-size writes — can indicate encryption loop behavior.
- **VSS deletion child process**: `vssadmin.exe` or `wmic.exe` spawned as a direct child of the ransomware process with shadow-delete arguments.
- **Ransom note creation**: `NtCreateFile` events creating `README.txt`, `HOW_TO_DECRYPT.html`, `_readme.txt`, or similar filenames in user directories.
- **Network enumeration preceding encryption**: SMB connections to multiple hosts on the local subnet in a short time window before the file write flood begins — indicates network share enumeration and preparation for lateral ransomware spread.

---

## ETW / eBPF Telemetry Signals (T1486)

### Microsoft-Windows-Kernel-File

This provider is the primary telemetry source for ransomware detection, as the file I/O flood is the most distinctive and unavoidable signal.

- **IRP_MJ_CREATE events**: A single process creating file handles to thousands of different files within a short window. Normal processes open a handful of files; ransomware opens every file in every directory.
- **IRP_MJ_WRITE events**: Write events to the same file handles opened above, with write sizes matching or exceeding the original file sizes.
- **IRP_MJ_SET_INFORMATION (FileRenameInformation)**: The rename event is the clearest indicator — the `FileName` field shows the new name with the ransomware extension.
- **Threshold**: A process generating > 50 IRP_MJ_WRITE + FileRename events per second against files in user data paths is a ransomware indicator with high confidence.

### Microsoft-Windows-Kernel-Process

- Child process creation of `vssadmin.exe`, `wmic.exe`, `bcdedit.exe` (for disabling recovery), `wbadmin.exe` (backup deletion) from the ransomware parent process.
- `bcdedit.exe /set {default} bootstatuspolicy ignoreallfailures` or `bcdedit.exe /set {default} recoveryenabled no` — disables Windows Recovery Environment (WinRE).

### Microsoft-Windows-Kernel-Network / eBPF Socket Events

- SMB (port 445) connections to multiple hosts in the same /24 subnet from the ransomware process, especially if these connections occur in a time-clustered burst before the file encryption phase.
- Connections to known ransomware C2 infrastructure (if CTI feeds are integrated with the genome analyzer).

---

## Detection Logic (T1486)

### Primary Ransomware Detection Rule

```
IF:
  etw_file.event_rate(IRP_MJ_SET_INFORMATION+FileRename, pid=P, window=30s) > 100
  AND rename_events.new_extension NOT IN common_extensions  [unknown/ransomware ext]
  AND rename_events.original_extension IN {docx, xlsx, pdf, jpg, png, mp4, db, ...}
THEN:
  technique = T1486, confidence = 0.93, severity = CRITICAL
```

### Shadow Copy Deletion Combined Rule

```
IF:
  process.create(image = vssadmin.exe, cmdline contains "delete shadows")
  AND process.parent = P
  AND etw_file.IRP_MJ_WRITE_rate(pid=P, window=60s) > threshold_normal * 10
THEN:
  technique = T1486 + T1490 (Inhibit System Recovery), confidence = 0.97, severity = CRITICAL
```

### Write Flood Without Rename (Overwrite Variant)

Some ransomware overwrites file content in place without renaming (to make decryption look impossible without paying). Detection relies on:

```
IF:
  etw_file.IRP_MJ_WRITE events where:
    write_count(pid=P, path_prefix=\Users\, window=60s) > 200
    AND write_size_per_file ≈ original_file_size  [full-file overwrites]
THEN:
  technique = T1486 (overwrite variant), confidence = 0.80
```

---

## OCSF Mapping (T1486)

| OCSF Class | Class ID | Discriminating Fields | Technique Confidence |
|---|---|---|---|
| File System Activity | 1001 | `activity_id = Rename`, high rate, ransomware extension in `file.name` | T1486 Critical |
| File System Activity | 1001 | `activity_id = Write`, rate > N/s from single PID on user data paths | T1486 High |
| Process Activity | 1007 | Child = `vssadmin.exe` with shadow-delete args | T1490 Critical |
