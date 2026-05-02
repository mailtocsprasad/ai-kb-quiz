---
technique_id: T1082
technique_name: System Information Discovery / Data from Local System
tactic: [Discovery, Collection]
platform: Windows
severity: Low–Medium
data_sources: [ETW-Process, ETW-Registry, ETW-File, ETW-Network]
mitre_url: https://attack.mitre.org/techniques/T1082/
---

# T1082 / T1005 — System Information Discovery and Data from Local System

## Description (T1082 / T1005)

T1082 System Information Discovery covers enumeration of the target host's configuration: OS version, hostname, domain membership, installed software, hardware capabilities, security product presence, and user account inventory. Attackers perform this reconnaissance to adapt subsequent actions — choosing exploits that match the OS version, avoiding domains with specific security controls, or identifying the highest-value data to collect.

T1005 Data from Local System covers collection of files and data that reside on the compromised host. Unlike remote discovery, T1005 involves actively reading and staging files: documents, credentials, configuration files, source code, and database contents. These two techniques are grouped in this file because they frequently co-occur in a post-exploitation phase and share the same telemetry sources.

Discovery operations are typically low-impact individually but form a recognizable burst pattern at the start of a post-exploitation phase — a sequence of enumeration commands executed within a short time window from a single attacker-controlled process.

---

## Windows Implementation Details (T1082)

Windows exposes system information through multiple APIs:

- `GetComputerName`, `GetComputerNameEx`, `DnsGetHostByName` — hostname and DNS suffix
- `NetGetJoinInformation` / `NetWkstaGetInfo` — domain join status
- `GetVersionEx`, `RtlGetVersion`, `VerifyVersionInfo` — OS version and build number
- `NtQuerySystemInformation` — extensive system information including loaded modules, process list, handle counts, CPU topology
- `EnumProcesses` / `CreateToolhelp32Snapshot` — process enumeration
- `RegOpenKeyEx(HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall)` — installed software list
- `WMI (Win32_OperatingSystem, Win32_ComputerSystem, Win32_LogicalDisk)` — broad system inventory via WMI queries
- `NetUserEnum`, `NetLocalGroupGetMembers` — user and group enumeration

LOLBins commonly used for discovery: `systeminfo.exe`, `net.exe`, `whoami.exe`, `ipconfig.exe`, `nltest.exe`, `qwinsta.exe`, `tasklist.exe`, `sc.exe query`, `wmic.exe`.

For T1005, the Windows file system APIs — `FindFirstFile` / `FindNextFile`, `CreateFile`, `ReadFile` — enable recursive directory enumeration and file reading. Attackers targeting specific data types use wildcard patterns to locate files by extension (`.docx`, `.pdf`, `.kdbx`, `.pfx`, `.config`).

---

## Observable Artifacts (T1082 / T1005)

- A burst of process creations (> 5 within 30 seconds) from the same parent process, each being a discovery utility (`systeminfo.exe`, `net.exe`, `whoami.exe`, `ipconfig.exe`, `nltest.exe`, `arp.exe`, `route.exe`, `netstat.exe`, `tasklist.exe`). This burst pattern is the key discovery indicator; individual utility executions are benign.
- `wmic.exe` or PowerShell `Get-WmiObject Win32_*` queries for OS, disk, process, or user information from a non-administrative context.
- `reg.exe query HKLM\SOFTWARE` or `reg.exe query HKCU\SOFTWARE` enumeration from a scripting engine or remote shell.
- Recursive file system enumeration (`dir /s /b *.docx`) from a cmd.exe process descended from a remote shell or scripting engine.
- Bulk file reads from `%USERPROFILE%\Documents`, `%USERPROFILE%\Desktop`, SharePoint sync folders, or database files from a process not normally associated with those file types.
- A file archive (`7z.exe a`, `zip.exe`, `compact.exe /EXE`) created in a temp directory containing staged files — data staging before exfiltration.

---

## ETW / eBPF Telemetry Signals (T1082 / T1005)

### Microsoft-Windows-Kernel-Process

- **Event ID 1 (ProcessStart)**: The burst pattern is the primary detection vehicle. Five or more of the following within 60 seconds from the same parent PID:
  ```
  systeminfo.exe, whoami.exe, net.exe, ipconfig.exe, nltest.exe,
  arp.exe, route.exe, netstat.exe, tasklist.exe, qwinsta.exe,
  wmic.exe (with OS/process/user queries), sc.exe query
  ```
  Each of these is benign in isolation; the burst is the signal.

- Execution of these utilities from unusual parents: `powershell.exe` descended from `WINWORD.EXE`, `cmd.exe` descended from `mshta.exe`, or `wmic.exe` with no interactive session parent (remote execution context).

### Microsoft-Windows-Kernel-Registry

- **RegOpenKey events** for `HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*` from a non-installer process — software inventory enumeration.
- **RegOpenKey events** for `HKLM\SYSTEM\CurrentControlSet\Services\*` — service enumeration.
- **RegOpenKey events** for `HKLM\SOFTWARE\Microsoft\Windows Defender\` or `HKLM\SOFTWARE\Symantec\` etc. — security product detection.

### Microsoft-Windows-Kernel-File

- **File Read events**: Bulk reads of user document files (`.docx`, `.xlsx`, `.pdf`, `.txt`, `.kdbx`, `.pfx`, `.config`, `.json`) by a process whose image is a scripting engine, remote access tool, or `cmd.exe`. The distinction from legitimate document access is the pattern: many files, many directories, many file types, in a short time window.
- **File Create events**: Archive files (`.zip`, `.7z`, `.rar`) or compressed blobs created in `%TEMP%`, `C:\Windows\Temp`, or user-writable paths by a process not normally associated with archiving. Data staging for exfiltration.
- **File Create in hidden or unexpected directories**: Staging data in `C:\ProgramData\`, `C:\Windows\Temp\`, or a directory named after a legitimate system component.

### Microsoft-Windows-Kernel-Network

- DNS queries from discovery tools that normally make no network calls (`nltest.exe /dclist:<domain>` makes LDAP queries; `net view \\<domain>` makes SMB/NetBIOS queries). Network activity from inherently local discovery tools indicates domain-level discovery.

---

## Evasion Variants (T1082 / T1005)

- **WMI-only discovery (no process creation)**: Performing discovery entirely through WMI from a PowerShell or COM session avoids spawning visible child processes. `Get-WmiObject`, `Invoke-WmiMethod`, and WMI CIM sessions produce no `ProcessStart` events for the discovery operations themselves. Detection relies on WMI activity auditing (Event ID 5857, 5858, 5859 from `Microsoft-Windows-WMI-Activity`) or kernel registry/file events from the WMI service process.
- **API-based enumeration (no CLI tools)**: Custom tooling calls `NtQuerySystemInformation`, `EnumProcesses`, `CreateToolhelp32Snapshot` directly rather than spawning process-enumeration utilities. No child process burst; detection relies on ETWTI API monitoring or behavior anomaly on the calling process.
- **Spread over time**: Discovery commands are spaced 5–10 minutes apart to avoid the burst detection heuristic. Each individual command is too isolated to trigger the cluster alert. Time-windowed clustering with longer windows (30 minutes) catches this, at the cost of more false positives.
- **Legitimate binary access for file discovery**: Using `explorer.exe` COM objects or `IShellFolder` to enumerate file system contents via the shell namespace rather than direct filesystem calls. The enumeration is attributed to `explorer.exe` or `svchost.exe` rather than an attacker binary.
- **NTFS raw access for file collection**: Directly reading file data via volume handle (`\\.\C:`) and parsing MFT to locate and read files, bypassing filesystem API hooks and file access auditing.

---

## Detection Logic (T1082 / T1005)

### Discovery Burst Pattern (T1082)

```
ProcessStart CLUSTER(
  image_name IN discovery_lolbin_set
  parent_pid = constant (same parent process)
  time_window = 60 seconds
  count >= 5
)
→ T1082 High (0.85)
```

Where `discovery_lolbin_set` = {systeminfo.exe, whoami.exe, net.exe, ipconfig.exe, nltest.exe, arp.exe, route.exe, netstat.exe, tasklist.exe, qwinsta.exe, wmic.exe, sc.exe, reg.exe, dsquery.exe}

### Discovery from Unusual Parent

```
ProcessStart(
  image_name IN discovery_lolbin_set
  parent.image_name IN {powershell.exe, cmd.exe, wscript.exe, cscript.exe, mshta.exe}
  parent.parent.image_name IN {WINWORD.EXE, EXCEL.EXE, OUTLOOK.EXE, mshta.exe, wscript.exe}
)
→ T1082 + T1566 High (0.90) — post-phishing discovery
```

### Bulk File Read Pattern (T1005)

```
FileRead CLUSTER(
  actor.process.file.name NOT IN {WINWORD.EXE, EXCEL.EXE, AcroRd32.exe,
                                   explorer.exe, SearchIndexer.exe}
  target.file.extension IN {.docx, .xlsx, .pdf, .kdbx, .pfx, .pem,
                             .config, .json, .sql, .mdb, .accdb}
  distinct_directories >= 3
  time_window = 120 seconds
  count >= 20
)
→ T1005 Medium (0.70)
```

### Data Staging Detection

```
SEQUENCE within 300 seconds:
  Step 1: Bulk FileRead matching T1005 pattern above
  Step 2: FileCreate(
    actor_pid = Step1.actor_pid
    target.extension IN {.zip, .7z, .rar, .tar.gz, .cab}
    target.path MATCHES "%TEMP%|C:\\Windows\\Temp|%ProgramData%"
  )
→ T1005 + Exfiltration Staging High (0.85)
```

---

## Sub-Techniques (T1082)

### T1082 — System Information Discovery

Attacker collects OS name, version, build, architecture, hostname, domain, uptime, and installed hotfixes (`systeminfo.exe`, `wmic os get caption,version`, PowerShell `Get-ComputerInfo`). This information determines which exploits, lateral movement techniques, or escalation paths are applicable.

### T1087 — Account Discovery

Enumeration of local and domain accounts, group memberships, and enabled/disabled status. `net user`, `net group`, `net localgroup`, `dsquery user`, `Get-ADUser` are the primary tools. High-value targets: Domain Admins, Enterprise Admins, service accounts with delegation.

### T1016 — System Network Configuration Discovery

`ipconfig /all`, `netstat -ano`, `arp -a`, `route print`, `nslookup` — maps the network topology, identifies DNS servers, gateways, and active connections. Reveals whether the host is on a segmented network, connected to a VPN, or has dual-homed network interfaces.

---

## Related Techniques (T1082 / T1005)

- T1059 (Scripting) — Discovery commands are usually launched via cmd.exe or PowerShell
- T1003 (Credential Dumping) — Frequently follows discovery as the next post-exploitation step
- T1041 (Exfiltration Over C2 Channel) — Data staged via T1005 is exfiltrated over the established C2
- T1070 (Indicator Removal) — Discovery leaves process and registry artifacts that attackers clear afterwards

---

## OCSF Mapping (T1082 / T1005)

| OCSF Class | Class ID | Discriminating Fields | Technique Confidence |
|---|---|---|---|
| Process Activity | 1007 | Burst of `process.file.name` from discovery_lolbin_set, same parent_pid | T1082 High |
| File Activity | 1001 | Bulk `activity_id = Read`, diverse extensions, non-document-app actor | T1005 Medium |
| File Activity | 1001 | `activity_id = Create`, archive extension, temp path, same actor as bulk reads | T1005 staging High |
| Registry Activity | 201003 | `activity_id = Open/Query`, Uninstall or Services key, non-installer actor | T1082 Low |
