---
content_type: mapping
category: ocsf_to_mitre
platform: Windows
---

# OCSF to MITRE ATT&CK Mapping

This document maps OCSF 1.5 event classes and their discriminating field combinations to MITRE ATT&CK techniques. Use this as a lookup table when the classification pipeline has an OCSF event and needs to identify candidate techniques before RAG retrieval and LLM classification.

> Technique descriptions reference MITRE ATT&CK® (mitre.org/attack). ATT&CK® is a registered trademark of The MITRE Corporation. Content derived from ATT&CK is used under CC BY 4.0.

---

## Process Activity — Class 1007

OCSF Process Activity covers process creation (`activity_id = 1`), process termination (`activity_id = 2`), and process access (`activity_id = 7`).

### Activity: Process Create (activity_id = 1)

| Discriminating Field Combination | MITRE Technique(s) | Confidence |
|---|---|---|
| `actor.process.file.name` IN Office app set AND `process.file.name` IN {powershell.exe, wscript.exe, cscript.exe, mshta.exe, cmd.exe} | T1566.001 + T1059 | High |
| `process.file.name` IN {mshta.exe, regsvr32.exe, rundll32.exe, wscript.exe, cscript.exe} AND `process.cmd_line` contains URL | T1218 | High |
| `process.file.name = powershell.exe` AND `process.cmd_line` matches `-[eE][nN].*[A-Za-z0-9+/=]{20,}` | T1059.001 + T1027.010 | High |
| `process.integrity_level = High` AND `actor.process.integrity_level = Medium` AND `actor.process.file.name` NOT IN {consent.exe, msiexec.exe} | T1548.002 | High |
| `process.file.name` IN {vssadmin.exe, wmic.exe} AND `process.cmd_line` matches shadow delete | T1490 + T1486 | Critical |
| `process.file.name = wevtutil.exe` AND `process.cmd_line` matches `\bcl\b` | T1070.001 | High |
| `process.file.name = reg.exe` AND `process.cmd_line` matches `save.*HKLM\\(SAM\|SYSTEM\|SECURITY)` | T1003.002 | High |
| `process.file.name = rundll32.exe` AND `process.cmd_line` matches `comsvcs.*[Mm]iniDump` | T1003.001 | Critical |
| `process.file.name = fsutil.exe` AND `process.cmd_line` matches `usn.*deletejournal` | T1070 | High |
| `process.file.name = certutil.exe` AND `process.cmd_line` matches `-urlcache\|-decode` | T1218.003 + T1105 | High |
| `process.file.name = powershell.exe` AND `process.cmd_line` matches `-[vV][eE][rR][sS].*2\|-[vV]\s*2` | T1562.006 (PS v2 downgrade) | High |
| Burst: 5+ discovery tools from same `actor.process.pid` within 60 seconds | T1082 + T1016 + T1087 | High |

### Activity: Process Access (activity_id = 7) [via Security Event 4656/4663]

| Discriminating Field Combination | MITRE Technique(s) | Confidence |
|---|---|---|
| `target_process.file.name = lsass.exe` AND `access_mask` contains PROCESS_VM_READ AND `actor.process.file.name` NOT IN EDR_set | T1003.001 | Critical |
| `target_process.file.name = lsass.exe` AND `access_mask` contains PROCESS_CREATE_PROCESS | PPID spoofing precursor (T1134) | Medium |

---

## Memory Activity — Class 10099 (Extension)

OCSF does not define a standard Memory Activity class in the base schema; ai-procwatch-mcp uses class ID 10099 as a project extension for ETWTI events.

| ETWTI Operation | Discriminating Fields | MITRE Technique(s) | Confidence |
|---|---|---|---|
| ALLOCVM_REMOTE | `target_process.pid ≠ actor.process.pid`, `protection = PAGE_EXECUTE_READWRITE` | T1055 (any sub-technique) | High |
| ALLOCVM_REMOTE | `target_process.pid ≠ actor.process.pid`, `protection = PAGE_READWRITE` | T1055 (RW→RX pattern — check for PROTECTVM follow-up) | Medium |
| WRITEVM_REMOTE | `target_process.pid ≠ actor.process.pid`, `bytes_written > 256` | T1055 (payload write) | High |
| READVM_REMOTE | `target_process.file.name = lsass.exe`, high frequency | T1003.001 | Critical |
| READVM_REMOTE | `target_process.pid ≠ actor.process.pid`, `target ≠ lsass.exe` | T1055 (reconnaissance / reflective loader) | Medium |
| PROTECTVM_REMOTE | `target_process.pid ≠ actor.process.pid`, `new_protect` becomes executable | T1055 (RW→RX flip) | High |
| PROTECTVM_LOCAL | `base_address IN ntdll_text_range`, `new_protect` becomes writable | T1562.006 (EtwEventWrite patch) | Critical |
| PROTECTVM_LOCAL | `base_address NOT IN ntdll_text_range`, oscillating RW↔RX | T1027 (Gargoyle) | High |
| MAPVIEW_REMOTE | `target_process.pid ≠ actor.process.pid`, `protect` executable | T1055 (section injection) | High |
| QUEUEAPCTHREAD_REMOTE | `target_process.pid ≠ actor.process.pid`, ApcRoutine not in loaded images | T1055.004 | High |
| SETTHREADCONTEXT_REMOTE | `target_process.pid ≠ actor.process.pid` | T1055.012 (hollowing) | High |
| ALLOCVM_LOCAL | `protection = PAGE_EXECUTE_READWRITE`, very early in process lifetime | T1027.002 (packer stub) | Medium |

---

## File Activity — Class 1001

| Activity ID | Discriminating Field Combination | MITRE Technique(s) | Confidence |
|---|---|---|---|
| Create (1) | `file.extension = .sys`, `file.path` NOT in System32\drivers, actor NOT in installer_set | T1068 / T1014 (BYOVD drop) | High |
| Create (1) | `file.path` matches Startup folder, actor NOT in installer_set | T1547.001 | Medium |
| Create (1) | `file.extension = .dll`, directory contains a known signed application exe, actor NOT in installer_set | T1574.002 | High |
| Create (1) | `file.extension IN {.zip, .7z, .rar}`, `file.path` in temp, preceded by bulk sensitive reads | T1005 staging | High |
| Write (2) | Storm: > 50 writes/5 seconds, file extensions changing | T1486 (ransomware) | Critical |
| Write (2) | Target is `.evtx` file, actor NOT in EventLog service set | T1070.001 tampering | High |
| Delete (3) | Target is `.evtx` file in winevt/Logs path | T1070.001 | High |
| Delete (3) | Bulk delete of `%SystemRoot%\Prefetch\*.pf` | T1070.004 | Medium |
| Rename (4) | Source extension ≠ target extension, many files rapidly | T1486 (encryption rename pattern) | High |
| SetInfo (8) | `info_class = FileBasicInformation`, target is executable/script, actor NOT in backup_set | T1070.006 (timestomping) | Medium |

---

## Module Activity — Class 1008

| Discriminating Field Combination | MITRE Technique(s) | Confidence |
|---|---|---|
| `module.file.name` IN known_system32_dll_set AND `module.file.path` NOT in {System32, SysWOW64, WinSxS} | T1574.001 / T1574.002 | High |
| `module.file.path` in user-writable location AND `module.file.name` = newly-created DLL | T1574.002 | High |
| No module load event for address range that is executing code (gap in image load stream) | T1055.001 (reflective load) | High |
| `module.file.path` = `.sys` driver outside System32\drivers | T1014 / T1068 (BYOVD) | High |

---

## Network Activity — Class 4001

| Discriminating Field Combination | MITRE Technique(s) | Confidence |
|---|---|---|
| `actor.process.file.name` IN LOLBin_set AND `dst_endpoint.port` IN {80, 443} AND `dst_endpoint.ip` NOT in microsoft_ranges | T1218 (LOLBin C2) | High |
| `actor.process.file.name = mshta.exe` AND any outbound TCP | T1218.005 | High |
| `actor.process.file.name = regsvr32.exe` AND outbound HTTP/HTTPS | T1218.009 (Squiblydoo) | Critical |
| DNS query from `actor.process.file.name` IN LOLBin_set | T1218 | Medium |
| High-frequency outbound connections (> 20 IPs/minute) from single process | T1041 (C2 beacon) or T1046 (scan) | Medium |
| `dst_endpoint.port = 445` from non-system process to internal IP | T1021.002 (SMB lateral movement) | Medium |
| `dst_endpoint.port = 3389` from non-system process | T1021.001 (RDP lateral movement) | Medium |

---

## Registry Value Activity — Class 201003 (Extension)

| Activity | Discriminating Field Combination | MITRE Technique(s) | Confidence |
|---|---|---|
| Set | `reg_key.path` matches Run/RunOnce ASEP pattern, actor NOT in installer_set | T1547.001 | Medium–High |
| Set | `reg_key.path` matches BootExecute, actor NOT in system | T1547 | High |
| Set | `reg_key.path` matches HKCU UAC bypass paths (ms-settings\shell\open\command, etc.) | T1548.002 | High |
| Set | `reg_key.path` matches IFEO\*\Debugger, data NOT in {vsjitdebugger, drwtsn32} | T1547 (IFEO hijack) | High |
| Set | `reg_key.path` matches Services\*\ImagePath, path in user-writable location | T1543.003 / T1568 | High |
| Set | `reg_key.path` matches AppInit_DLLs, data ≠ empty | T1574 | High |
| Set | `reg_key.path` = WDigest\UseLogonCredential, data = 1 | T1003.001 (pre-position) | High |
| Open | `reg_key.path` = HKLM\SAM, actor NOT in system services | T1003.002 | High |

---

## Security Finding — Class 2001

| Event Source | Discriminating Fields | MITRE Technique(s) | Confidence |
|---|---|---|---|
| Security Audit Event 1102 | Any occurrence | T1070.001 | Critical |
| System Event 104 | Any occurrence | T1070.001 | High |
| CodeIntegrity Event 3065 | Unsigned driver blocked | T1068 / T1014 | High |
| CodeIntegrity Event 8028 | Blocklisted driver attempted | T1068 (BYOVD) | Critical |

---

## Authentication — Class 3002

| Discriminating Field Combination | MITRE Technique(s) | Confidence |
|---|---|---|
| Event 4648 (`explicit_credentials`), `actor.process.file.name` NOT in {services.exe, lsass.exe, svchost.exe} | T1134.001 / T1134.003 | Medium–High |
| Event 4624, `logon_type = 3` (Network), unusual source IP or non-business hours | T1078 (valid accounts lateral movement) | Medium |
| Event 4625 (failed logon), rapid succession same `target_user`, multiple source IPs | T1110 (brute force) | High |

---

## Technique → Primary OCSF Classes Summary

| Technique | Primary OCSF Classes |
|---|---|
| T1055 | Memory Activity (10099) — ALLOCVM/WRITEVM/SETTHREADCONTEXT |
| T1003 | Memory Activity (10099) — READVM to lsass; Process Activity 1007 (minidump cmd) |
| T1059 | Process Activity (1007) — cmd_line analysis |
| T1218 | Process Activity (1007) — image name + cmd_line; Network Activity (4001) |
| T1547 | Registry Activity (201003) — ASEP key writes; File Activity (1001) — startup folder |
| T1548 | Registry Activity (201003) — HKCU UAC keys; Process Activity (1007) — integrity level |
| T1562 | Memory Activity (10099) — PROTECTVM on ntdll; Process Activity (1007) — wevtutil |
| T1014 | Security Finding (2001) — CodeIntegrity events; Registry Activity (201003) — Services key |
| T1068 | Security Finding (2001) — CodeIntegrity events; Process Activity (1007) — NtLoadDriver |
| T1070 | Process Activity (1007) — wevtutil/fsutil; Security Finding (2001) — Event 1102 |
| T1486 | File Activity (1001) — write storm; Process Activity (1007) — VSS deletion |
| T1574 | Module Activity (1008) — unexpected load path; File Activity (1001) — DLL create |
| T1027 | Memory Activity (10099) — packer ALLOCVM; Process Activity (1007) — -enc cmdline |
