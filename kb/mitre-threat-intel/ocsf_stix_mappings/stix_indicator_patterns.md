---
content_type: mapping
category: stix_indicators
platform: Windows
stix_version: "2.1"
---

# STIX 2.1 Indicator Patterns

This document provides STIX 2.1 indicator pattern expressions for the behavioral indicators documented in this knowledge base. Each STIX indicator pattern can be used to match against OCSF-normalized genome events or serialized STIX observable objects. Patterns follow the STIX Patterning Language specification.

STIX indicators here represent behavioral patterns (sequences and combinations of observables), not static IOCs (file hashes, IPs). They are intended for use with STIX-aware detection platforms and TAXII feeds.

---

## Process Injection Indicators (T1055)

### STIX-IND-001: Remote Process Memory Allocation with Execute Permission

Matches ETWTI ALLOCVM_REMOTE events where the target process differs from the caller and the allocated region is executable.

```
[process:pid != process:parent_ref.pid
 AND x-etwti:operation = 'ALLOCVM_REMOTE'
 AND x-etwti:target_pid != x-etwti:caller_pid
 AND x-etwti:protect MATCHES '.*EXECUTE.*']
```

**Technique:** T1055
**Confidence:** Medium (single event; High when combined with WRITEVM_REMOTE)

---

### STIX-IND-002: Classic Injection Sequence (Alloc + Write + Thread)

Matches the full CreateRemoteThread injection chain as a time-windowed sequence.

```
([x-etwti:operation = 'ALLOCVM_REMOTE'
  AND x-etwti:caller_pid = X
  AND x-etwti:target_pid = Y]
 FOLLOWEDBY [x-etwti:operation = 'WRITEVM_REMOTE'
             AND x-etwti:caller_pid = X
             AND x-etwti:target_pid = Y]
 FOLLOWEDBY [x-etwti:operation = 'QUEUEAPCTHREAD_REMOTE'
             OR x-etwti:operation = 'SETTHREADCONTEXT_REMOTE'
             AND x-etwti:caller_pid = X
             AND x-etwti:target_pid = Y])
WITHIN 30 SECONDS
```

**Technique:** T1055.003, T1055.004
**Confidence:** High

---

### STIX-IND-003: Section-Based Injection

Matches section map injection (avoids WriteProcessMemory).

```
[x-etwti:operation = 'MAPVIEW_REMOTE'
 AND x-etwti:caller_pid != x-etwti:target_pid
 AND x-etwti:protect MATCHES '.*EXECUTE.*'
 AND NOT (process:name = 'clr.dll' OR process:name = 'v8.dll')]
```

**Technique:** T1055 (section injection variant)
**Confidence:** High

---

### STIX-IND-004: Process Hollowing Sequence

```
([process:command_line CONTAINS 'CREATE_SUSPENDED'
  OR x-windows-api:function_name = 'CreateProcess']
 FOLLOWEDBY [x-windows-api:function_name = 'NtUnmapViewOfSection'
             AND x-windows-api:target_pid = Y]
 FOLLOWEDBY [x-etwti:operation = 'WRITEVM_REMOTE'
             AND x-etwti:target_pid = Y]
 FOLLOWEDBY [x-etwti:operation = 'SETTHREADCONTEXT_REMOTE'
             AND x-etwti:target_pid = Y])
WITHIN 10 SECONDS
```

**Technique:** T1055.012
**Confidence:** High

---

## Credential Dumping Indicators (T1003)

### STIX-IND-005: LSASS Memory Read Storm

```
[x-etwti:operation = 'READVM_REMOTE'
 AND x-process:name = 'lsass.exe'
 AND NOT (process:name IN ('MsMpEng.exe', 'csrss.exe', 'lsm.exe', 'smss.exe', 'wininit.exe'))]
 COUNT WITHIN 5 SECONDS > 10
```

**Technique:** T1003.001
**Confidence:** Critical

---

### STIX-IND-006: Comsvcs.dll LSASS Minidump

```
[process:name = 'rundll32.exe'
 AND process:command_line MATCHES '(?i)comsvcs.*minidump|comsvcs.*MiniDump']
```

**Technique:** T1003.001
**Confidence:** Critical

---

### STIX-IND-007: SAM Registry Hive Dump

```
[process:name = 'reg.exe'
 AND process:command_line MATCHES '(?i)save.*(HKLM\\\\SAM|HKLM\\\\SYSTEM|HKLM\\\\SECURITY)']
```

**Technique:** T1003.002
**Confidence:** High

---

## Persistence Indicators (T1547)

### STIX-IND-008: Run Key Persistence Write

```
[windows-registry-key:key MATCHES '(?i).*CurrentVersion\\\\Run(Once)?$'
 AND windows-registry-key:values[*].name != ''
 AND NOT (process:name IN ('msiexec.exe', 'TrustedInstaller.exe', 'svchost.exe'))]
```

**Technique:** T1547.001
**Confidence:** Medium (High if actor process in user-writable path)

---

### STIX-IND-009: IFEO Debugger Shim

```
[windows-registry-key:key MATCHES '(?i).*Image File Execution Options\\\\.*\\\\Debugger$'
 AND windows-registry-key:values[*].data NOT MATCHES '(?i)vsjitdebugger|drwtsn32']
```

**Technique:** T1547 (IFEO hijack)
**Confidence:** High

---

## Defense Evasion / UAC Bypass (T1548, T1562)

### STIX-IND-010: UAC Bypass HKCU Registry Write

```
[windows-registry-key:key MATCHES '(?i)HKCU.*Software\\\\Classes\\\\(ms-settings|Folder|exefile)\\\\shell\\\\open\\\\command$'
 AND process:x_integrity_level = 'Medium']
```

**Technique:** T1548.002
**Confidence:** High

---

### STIX-IND-011: EtwEventWrite Patch (ntdll .text Modification)

```
[x-etwti:operation = 'PROTECTVM_LOCAL'
 AND x-etwti:base_address WITHIN x-module:name = 'ntdll.dll' text_section_range
 AND x-etwti:new_protect MATCHES '.*(READWRITE|EXECUTE_READWRITE).*'
 AND NOT (process:name IN ('windbg.exe', 'x64dbg.exe', 'ollydbg.exe'))]
```

**Technique:** T1562.006
**Confidence:** Critical

---

### STIX-IND-012: PowerShell Version 2 Downgrade

```
[process:name = 'powershell.exe'
 AND process:command_line MATCHES '(?i)-[vV][eE]{0,3}[rR]{0,1}[sS]{0,1}[iI]{0,1}[oO]{0,1}[nN]{0,1}\\s*2']
```

**Technique:** T1562.006 (ETW bypass via PS v2)
**Confidence:** High

---

## LOLBin Execution (T1218)

### STIX-IND-013: Regsvr32 Remote Scriptlet (Squiblydoo)

```
[process:name = 'regsvr32.exe'
 AND process:command_line MATCHES '(?i)/i:(http|https|\\\\\\\\)'
 AND process:command_line CONTAINS 'scrobj.dll']
```

**Technique:** T1218.009
**Confidence:** Critical

---

### STIX-IND-014: Mshta Remote Execution

```
[process:name = 'mshta.exe'
 AND (process:command_line MATCHES '(?i)https?://'
      OR process:command_line MATCHES '(?i)vbscript:|javascript:')]
```

**Technique:** T1218.005
**Confidence:** High

---

### STIX-IND-015: LOLBin Network Connection

```
[process:name IN ('mshta.exe', 'regsvr32.exe', 'wscript.exe', 'cscript.exe', 'bitsadmin.exe', 'certutil.exe')
 AND network-traffic:dst_port IN (80, 443, 8080, 8443)
 AND NOT (network-traffic:dst_ref.value WITHIN microsoft_cdn_ranges)]
```

**Technique:** T1218
**Confidence:** High

---

## Indicator Removal (T1070)

### STIX-IND-016: Security Log Cleared

```
[x-windows-event-log:channel = 'Security'
 AND x-windows-event-log:event_id = 1102]
```

**Technique:** T1070.001
**Confidence:** Critical

---

### STIX-IND-017: Shadow Copy Deletion

```
[(process:name = 'vssadmin.exe'
  AND process:command_line MATCHES '(?i)delete.*shadow')
 OR (process:name = 'wmic.exe'
     AND process:command_line MATCHES '(?i)shadowcopy.*delete')]
```

**Technique:** T1490 + T1070.004
**Confidence:** High

---

### STIX-IND-018: USN Journal Deletion

```
[process:name = 'fsutil.exe'
 AND process:command_line MATCHES '(?i)usn.*deletejournal']
```

**Technique:** T1070
**Confidence:** High

---

## Ransomware (T1486)

### STIX-IND-019: Ransomware File Extension Churn

```
[file:name MATCHES '.*\\..*'
 AND x-file-activity:operation = 'Rename'
 AND x-file-activity:original_extension != x-file-activity:new_extension
 AND x-file-activity:new_extension NOT IN common_document_extensions]
 COUNT WITHIN 10 SECONDS > 20
```

**Technique:** T1486
**Confidence:** High (Critical when combined with VSS deletion)

---

## Kernel / Driver Evasion (T1068, T1014)

### STIX-IND-020: BYOVD — Vulnerable Driver Load from Non-Standard Path

```
([windows-registry-key:key MATCHES '(?i).*CurrentControlSet\\\\Services\\\\.*\\\\ImagePath$'
  AND windows-registry-key:values[*].data NOT MATCHES '(?i)C:\\\\Windows\\\\System32\\\\drivers\\\\.*']
 FOLLOWEDBY [x-codesigning:event_id IN (3076, 8028, 3065)])
WITHIN 120 SECONDS
```

**Technique:** T1068 (BYOVD)
**Confidence:** High (Critical for event ID 8028)

---

### STIX-IND-021: LSASS PPL Bypass — Driver + Credential Dump Sequence

```
([x-codesigning:event_id = 3076
  AND x-codesigning:driver_path NOT MATCHES '(?i)C:\\\\Windows\\\\System32\\\\drivers\\\\.*']
 FOLLOWEDBY [x-etwti:operation = 'READVM_REMOTE'
             AND x-process:name = 'lsass.exe'
             AND NOT (process:name IN ('MsMpEng.exe', 'csrss.exe', 'lsm.exe'))])
WITHIN 60 SECONDS
```

**Technique:** T1068 + T1003.001
**Confidence:** Critical

---

## DLL Hijacking (T1574)

### STIX-IND-022: DLL Placed Alongside Trusted Application

```
([file:name MATCHES '(?i).*\\.dll$'
  AND file:parent_directory_ref.path = known_trusted_application_directory
  AND NOT (process:name IN ('msiexec.exe', 'TrustedInstaller.exe'))]
 FOLLOWEDBY [x-module-load:file_path = file:path
             AND process:name = known_trusted_application_name])
WITHIN 300 SECONDS
```

**Technique:** T1574.002
**Confidence:** High

---

### STIX-IND-023: System DLL Loaded from Non-System Path

```
[x-module-load:file_name IN system32_dll_set
 AND NOT (x-module-load:file_path MATCHES '(?i)C:\\\\Windows\\\\(System32|SysWOW64|WinSxS)\\\\.*')]
```

**Technique:** T1574.001 / T1574.002
**Confidence:** High

---

## Discovery / Collection (T1082, T1005)

### STIX-IND-024: Post-Exploitation Discovery Burst

```
[process:name IN ('systeminfo.exe', 'whoami.exe', 'net.exe', 'ipconfig.exe', 'nltest.exe',
                  'arp.exe', 'route.exe', 'netstat.exe', 'tasklist.exe', 'wmic.exe')]
 COUNT BY process:parent_ref.pid WITHIN 60 SECONDS > 5
```

**Technique:** T1082 + T1016 + T1087
**Confidence:** High

---

## STIX Bundle Structure Example

A complete STIX 2.1 bundle wrapping multiple indicators from this knowledge base:

```json
{
  "type": "bundle",
  "id": "bundle--<uuid>",
  "spec_version": "2.1",
  "objects": [
    {
      "type": "indicator",
      "spec_version": "2.1",
      "id": "indicator--<uuid>",
      "created": "2026-05-01T00:00:00Z",
      "modified": "2026-05-01T00:00:00Z",
      "name": "STIX-IND-001: Remote Process Memory Allocation with Execute Permission",
      "description": "Matches ETWTI ALLOCVM_REMOTE events where the target process differs from the caller and the allocated region is executable. Associated with T1055 Process Injection.",
      "pattern": "[x-etwti:operation = 'ALLOCVM_REMOTE' AND x-etwti:target_pid != x-etwti:caller_pid AND x-etwti:protect MATCHES '.*EXECUTE.*']",
      "pattern_type": "stix",
      "valid_from": "2026-05-01T00:00:00Z",
      "kill_chain_phases": [
        {"kill_chain_name": "mitre-attack", "phase_name": "defense-evasion"},
        {"kill_chain_name": "mitre-attack", "phase_name": "privilege-escalation"}
      ],
      "labels": ["malicious-activity"],
      "confidence": 70,
      "external_references": [
        {"source_name": "mitre-attack", "external_id": "T1055", "url": "https://attack.mitre.org/techniques/T1055/"}
      ]
    }
  ]
}
```

---

## STIX Custom Extension: x-etwti

The `x-etwti` STIX custom extension object represents an ETWTI event for use in behavioral pattern expressions:

```json
{
  "type": "x-etwti",
  "spec_version": "2.1",
  "id": "x-etwti--<uuid>",
  "operation": "ALLOCVM_REMOTE",
  "caller_pid": 4821,
  "target_pid": 7234,
  "base_address": "0x1f0000000",
  "region_size": 4096,
  "protect": "PAGE_EXECUTE_READWRITE",
  "alloc_type": "MEM_COMMIT|MEM_RESERVE",
  "timestamp": "2026-05-01T14:23:12.001Z"
}
```

**Extension fields for x-etwti:**

| Field | Type | Description |
|---|---|---|
| `operation` | string | ETWTI event name (ALLOCVM_REMOTE, WRITEVM_REMOTE, etc.) |
| `caller_pid` | integer | PID of the process that performed the operation |
| `target_pid` | integer | PID of the process that was acted upon |
| `base_address` | hex-string | Base virtual address of the memory operation |
| `region_size` | integer | Size in bytes of the affected region |
| `protect` | string | Memory protection constant string |
| `bytes_transferred` | integer | For READVM/WRITEVM: bytes transferred |
| `apc_routine` | hex-string | For QUEUEAPCTHREAD: routine address |
