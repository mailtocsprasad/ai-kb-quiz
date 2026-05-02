---
content_type: detection
category: telemetry_map
platform: Windows
---

# ETW Telemetry Map — Provider → Event → Technique → OCSF

This document maps each instrumented ETW provider to its key events, the MITRE ATT&CK technique each event is most relevant to detecting, and the OCSF class that normalizes the event. Use this map to determine which providers must be subscribed to in order to achieve detection coverage for a given technique.

> Technique descriptions reference MITRE ATT&CK® (mitre.org/attack). ATT&CK® is a registered trademark of The MITRE Corporation. Content derived from ATT&CK is used under CC BY 4.0.

---

## Microsoft-Windows-Kernel-Process

**GUID:** `{22FB2CD6-0E7B-422B-A0C7-2FAD1FD0E716}`
**Session type:** Kernel (kernel logger session, not real-time session)
**Access:** Requires `SeSystemProfilePrivilege` for kernel session, or real-time session via GUID subscription

| Event ID | Event Name | Key Fields | Primary Techniques | OCSF Class |
|---|---|---|---|---|
| 1 | ProcessStart | ProcessId, ParentProcessId, ImageFileName, CommandLine, TokenElevationType, IntegrityLevel | T1059, T1218, T1548, T1574, T1547 | Process Activity (1007) |
| 2 | ProcessStop | ProcessId, ExitCode | All (process termination tracking) | Process Activity (1007) |
| 3 | ThreadStart | ProcessId, ThreadId, StartAddress, Win32StartAddress | T1055.003, T1055.004 (cross-process thread) | Thread Activity |
| 4 | ThreadStop | ProcessId, ThreadId | Thread tracking | Thread Activity |
| 5 | ImageLoad | ProcessId, ImageBase, ImageSize, ImageFileName | T1574, T1027.002 (DLL from unexpected path) | Module Activity (1008) |
| 6 | ImageUnload | ProcessId, ImageBase | Module tracking | Module Activity (1008) |

**Notes:**
- `TokenElevationType = 2` (Full) with medium-integrity parent = UAC bypass signal (T1548).
- `Win32StartAddress` pointing outside any loaded image = injection signal (T1055).
- `CommandLine` requires process command line auditing to be enabled (see `Microsoft-Windows-Kernel-Audit-API-Calls` or Security Event 4688 as alternative).

---

## Microsoft-Windows-Threat-Intelligence (ETWTI)

**GUID:** `{F4E1897C-BB5D-5668-F1D8-040F4D8DD344}`
**Session type:** Real-time (restricted consumer — requires PPL ANTIMALWARE_LIGHT)
**Access:** Only EDR agents running at the appropriate PPL signer level can subscribe

| Event ID / Name | Key Fields | Primary Techniques | OCSF Class |
|---|---|---|---|
| ALLOCVM_REMOTE | CallerPid, TargetPid, BaseAddress, RegionSize, AllocationType, Protect | T1055 (all sub-techniques) | Memory Activity |
| ALLOCVM_LOCAL | CallerPid, BaseAddress, Protect | T1027.002 (packer stub) | Memory Activity |
| FREEVM_REMOTE | CallerPid, TargetPid, BaseAddress | Injection cleanup tracking | Memory Activity |
| WRITEVM_REMOTE | CallerPid, TargetPid, BaseAddress, BytesWritten | T1055.003, T1055.001 | Memory Activity |
| READVM_REMOTE | CallerPid, TargetPid, BaseAddress, BytesRequested | T1003.001 (LSASS reads) | Memory Activity |
| PROTECTVM_REMOTE | CallerPid, TargetPid, BaseAddress, OldProtect, NewProtect | T1055, T1027 (RW→RX flip) | Memory Activity |
| PROTECTVM_LOCAL | CallerPid, BaseAddress, OldProtect, NewProtect | T1562.006 (EtwEventWrite patch), T1027 | Memory Activity |
| MAPVIEW_REMOTE | CallerPid, TargetPid, BaseAddress, Size, Protect, SectionType | T1055 (section injection) | Memory Activity |
| QUEUEAPCTHREAD_REMOTE | CallerPid, TargetPid, TargetTid, ApcRoutine | T1055.004 (APC injection) | Thread Activity |
| SETTHREADCONTEXT_REMOTE | CallerPid, TargetPid, TargetTid | T1055.012 (hollowing), T1055.003 | Thread Activity |

**Notes:**
- All REMOTE events: `TargetPid ≠ CallerPid` is inherent to the event name; these only fire for cross-process operations.
- READVM_REMOTE with TargetPid = lsass.exe PID and CallerPid not in {csrss, smss, lsm} = T1003.001 Critical.
- PROTECTVM_LOCAL with BaseAddress in ntdll.dll .text range = EtwEventWrite patch (T1562.006) Critical.

---

## Microsoft-Windows-Kernel-File

**GUID:** `{EDD08927-9CC4-4E65-B970-C2560FB5C521}`
**Session type:** Kernel logger session

| Event Name | Key Fields | Primary Techniques | OCSF Class |
|---|---|---|---|
| FileCreate | ProcessId, OpenPath, CreateOptions, FileAttributes | T1574.002 (DLL drop), T1547.001 (startup folder) | File Activity (1001) |
| FileWrite | ProcessId, IrpPtr, FileObject, Offset, IOSize | T1486 (ransomware write flood), T1070.004 | File Activity (1001) |
| FileDelete | ProcessId, OpenPath | T1070.004 (file deletion), T1486 (VSS deletion staging) | File Activity (1001) |
| FileRename | ProcessId, OpenPath, InfoClass | T1070.006 (timestomping), T1574 (DLL rename) | File Activity (1001) |
| FileSetInfo | ProcessId, FileObject, InfoClass | T1070.006 (BasicInfo = timestamps) | File Activity (1001) |
| ImageLoad (via file) | ProcessId, ImageBase, ImageFileName | T1574 (DLL load path) | Module Activity (1008) |

**Notes:**
- `FileSetInfo` with `InfoClass = FileBasicInformation` (value 4) = timestamp modification (T1070.006).
- USN Journal is a complementary gap-free source; ETW-File events may be dropped under high I/O load, but USN is kernel-maintained and drop-resistant.

---

## Microsoft-Windows-Kernel-Network

**GUID:** `{7DD42A49-5329-4832-8DFD-43D979153A88}`
**Session type:** Kernel logger session

| Event Name | Key Fields | Primary Techniques | OCSF Class |
|---|---|---|---|
| TcpConnect | ProcessId, DstAddr, DstPort, SrcAddr, SrcPort | T1218 (LOLBin network), T1041 (C2) | Network Activity (4001) |
| TcpAccept | ProcessId, LocalAddr, LocalPort, RemoteAddr, RemotePort | T1021 (lateral movement, RDP/SMB) | Network Activity (4001) |
| TcpDisconnect | ProcessId, LocalAddr, RemoteAddr | Session tracking | Network Activity (4001) |
| UdpSendMsg | ProcessId, DstAddr, DstPort, BytesSent | T1041, DNS exfiltration | Network Activity (4001) |
| UdpRecvMsg | ProcessId, SrcAddr, SrcPort, BytesRecvd | C2 beacon receive | Network Activity (4001) |
| DnsQuery (via eBPF or DNS client) | ProcessId, QueryName, QueryType | T1218 (LOLBin DNS), C2 DGA detection | DNS Activity |

**Notes:**
- `ProcessId` + `DstPort = 443` + `DstAddr NOT IN microsoft_ranges` from scripting engines = T1218/C2 High.
- DNS queries from `mshta.exe`, `regsvr32.exe`, `wscript.exe` = LOLBin network activity (T1218).

---

## Microsoft-Windows-Kernel-Registry

**GUID:** `{70EB4F03-C1DE-4F73-A051-33D13D5413BD}`
**Session type:** Kernel logger session

| Event Name | Key Fields | Primary Techniques | OCSF Class |
|---|---|---|---|
| RegSetValue | ProcessId, KeyName, ValueName, Type, DataSize, DataValue | T1547 (ASEP), T1548.002 (UAC bypass HKCU), T1574 | Registry Activity (201003) |
| RegCreateKey | ProcessId, KeyName | T1547 (new service key), T1574 | Registry Activity (201003) |
| RegDeleteKey | ProcessId, KeyName | T1070 (anti-forensics), T1547 (one-time runonce cleanup) | Registry Activity (201003) |
| RegDeleteValue | ProcessId, KeyName, ValueName | T1070 (ASEP cleanup) | Registry Activity (201003) |
| RegOpenKey | ProcessId, KeyName | T1082 (software inventory reads), T1003 (SAM access) | Registry Activity (201003) |

**Notes:**
- `RegSetValue` on `HKCU\Software\Classes\*\shell\open\command` + medium-integrity actor = T1548.002 Critical.
- `RegOpenKey` on `HKLM\SAM` from non-system process = T1003.002 High.

---

## Microsoft-Windows-Security-Auditing

**GUID:** `{54849625-5478-4994-A5BA-3E3B0328C30D}`
**Session type:** Security channel (requires security audit policy configuration)

| Event ID | Event Name | Primary Techniques | OCSF Class |
|---|---|---|---|
| 4624 | Successful Logon | T1078 (valid accounts), lateral movement | Authentication (3002) |
| 4625 | Failed Logon | Brute force (T1110) | Authentication (3002) |
| 4648 | Explicit Credential Logon | T1134.003 (MakeToken), T1078 | Authentication (3002) |
| 4656 | Handle Requested | T1003.001 (LSASS handle), T1012 (registry handle) | Security Finding (2001) |
| 4663 | Object Access | T1003 (file/process read), T1070 | File Activity (1001) |
| 4673 | Privileged Service Called | T1134 (SeDebugPrivilege), T1548 (SeImpersonatePrivilege) | Process Activity (1007) |
| 4688 | Process Creation | T1059, T1218, T1548 | Process Activity (1007) |
| 4697 | Service Installed | T1543.003, T1547.010 (driver service) | Process Activity (1007) |
| 4698 | Scheduled Task Created | T1053.005 (Scheduled Task) | Scheduled Job Activity |
| 1102 | Audit Log Cleared | T1070.001 | Security Finding (2001) |
| 104 | Event Log Cleared | T1070.001 | Security Finding (2001) |

---

## Microsoft-Windows-PowerShell

**GUID:** `{A0C1853B-5C40-4B15-8766-3CF1C58F985A}`
**Session type:** Real-time subscription

| Event ID | Event Name | Key Fields | Primary Techniques | OCSF Class |
|---|---|---|---|---|
| 400 | Engine Lifecycle Start | EngineVersion, HostApplication | T1059.001 (v2.0 downgrade) | Process Activity (1007) |
| 403 | Engine Lifecycle Stop | EngineVersion | Correlation baseline | Process Activity (1007) |
| 4100 | Error Record | ScriptName, ErrorRecord | Obfuscation failures | Security Finding |
| 4103 | Module Logging | CommandName, CommandType, ScriptName, Payload | T1059.001, T1027.010 | Process Activity (1007) |
| 4104 | Script Block Logging | ScriptBlockText, ScriptBlockId, MessageNumber | T1059.001, T1027.010, T1562 | Process Activity (1007) |

**Notes:**
- Event 4104 with `ScriptBlockText` containing: `iex`, `Invoke-Expression`, `FromBase64String`, `-bxor`, `[char[]]`, `net.webclient`, `downloadstring` = T1059.001 + T1027.010.
- `EngineVersion = 2.0` in Event 400 = PS v2 downgrade bypass attempt.

---

## Microsoft-Windows-CodeIntegrity

**GUID:** `{4EE76BD8-3CF4-44A0-A0AC-3937643E37A3}`
**Session type:** Real-time subscription

| Event ID | Event Name | Primary Techniques | OCSF Class |
|---|---|---|---|
| 3065 | Unsigned kernel module blocked | T1068, T1014 (BYOVD unsigned payload) | Security Finding (2001) |
| 3066 | Driver blocked by policy | T1068, T1014 | Security Finding (2001) |
| 3076 | Driver load allowed but not in good-known list | T1068 (BYOVD precursor) | Module Activity (1008) |
| 8028 | Driver on blocklist — enforcement mode | DE-001 BYOVD blocklisted driver | Security Finding (2001) |

---

## Microsoft-Windows-Kernel-Audit-API-Calls

**GUID:** `{E02A841C-75A3-4FA7-AFC8-AE09CF9B7F23}`
**Session type:** Real-time subscription

| Event Name | Key Fields | Primary Techniques | OCSF Class |
|---|---|---|---|
| NtLoadDriver | CallerPid, DriverServiceName, Result | T1068, T1014 (driver load) | Process Activity (1007) |
| NtSetSystemInformation | CallerPid, SystemInformationClass | Kernel information manipulation | Security Finding |

---

## Windows eBPF — ebpfapi.dll Socket Events

**Source:** Windows eBPF for Windows (`ebpfapi.dll`), hook programs on `EBPF_ATTACH_TYPE_CGROUP_SOCK_OPS` and socket programs

| Event Type | Key Fields | Primary Techniques | OCSF Class |
|---|---|---|---|
| BIND | ProcessId, LocalAddr, LocalPort, Protocol | T1071 (C2 listener), T1014 (hidden port) | Network Activity (4001) |
| CONNECT | ProcessId, RemoteAddr, RemotePort, Protocol | T1041, T1218 (LOLBin connect) | Network Activity (4001) |
| ACCEPT | ProcessId, LocalPort, RemoteAddr | T1021 (lateral movement accept) | Network Activity (4001) |

**Notes:**
- eBPF socket events provide process-attributed network telemetry independent of ETW-Kernel-Network, useful for cross-validation.
- A process with no expected network activity (e.g., `calc.exe`) making a TCP CONNECT is an immediate anomaly.

---

## Coverage Matrix — Technique to Required Providers

| Technique | Required Providers (minimum for High confidence) |
|---|---|
| T1055 (Injection) | ETWTI (ALLOCVM_REMOTE, WRITEVM_REMOTE, MAPVIEW_REMOTE, SETTHREADCONTEXT_REMOTE) |
| T1003 (Cred Dump) | ETWTI (READVM_REMOTE to lsass), Security-Auditing (4656, 4673) |
| T1059.001 (PowerShell) | PowerShell (4104), Kernel-Process (1 for cmd line) |
| T1547 (Persistence) | Kernel-Registry (RegSetValue), Kernel-File (startup folder) |
| T1548.002 (UAC Bypass) | Kernel-Registry (HKCU bypass keys), Kernel-Process (elevation type) |
| T1562 (Impair Defenses) | ETWTI (PROTECTVM_LOCAL on ntdll), Kernel-Process (session stop) |
| T1014 (Rootkit) | CodeIntegrity (driver load), Kernel-Audit-API (NtLoadDriver) |
| T1068 (BYOVD) | CodeIntegrity (3076, 8028), Kernel-Audit-API (NtLoadDriver), Kernel-Registry |
| T1218 (LOLBins) | Kernel-Process (ProcessStart + cmdline), Kernel-Network (TcpConnect) |
| T1070 (Log Clearing) | Security-Auditing (1102, 104), Kernel-Process (wevtutil cmdline) |
| T1486 (Ransomware) | Kernel-File (write storm), Kernel-Process (vssadmin cmdline) |
| T1574 (DLL Hijack) | Kernel-File (ImageLoad from unexpected path), Kernel-File (DLL create) |
