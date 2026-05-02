---
content_type: detection
category: behavioral_indicators
platform: Windows
---

# Behavioral Indicators

Behavioral Indicators (BI) are multi-event patterns that, when observed in the process genome event stream, indicate specific attack techniques with a defined confidence level. Each BI encodes a sequence or cluster of ETW/eBPF events and maps to one or more MITRE ATT&CK techniques. BIs are the primary input to the ai-procwatch-mcp LLM classification pipeline.

Each BI follows this format:
- **Pattern:** event conditions using OCSF field names
- **MITRE:** technique ID(s)
- **Confidence:** High / Medium / Low
- **OCSF fields:** discriminating field references
- **False positives:** known benign generators

---

## BI-001: Office Application Spawning Encoded PowerShell

**Pattern:**
```
parent_image IN {WINWORD.EXE, EXCEL.EXE, POWERPNT.EXE, OUTLOOK.EXE, ONENOTE.EXE}
  AND child_image = powershell.exe
  AND child_cmdline MATCHES (-enc|-EncodedCommand|-e\s+[A-Za-z0-9+/=]{20,})
```
**MITRE:** T1566.001 + T1059.001 + T1027.010
**Confidence:** High
**OCSF fields:** `actor.process.file.name`, `process.file.name`, `process.cmd_line`
**False positives:** Some legitimate Office macros that run internal PS utilities; rare

---

## BI-002: Cross-Process Memory Write + Thread Creation

**Pattern:**
```
SEQUENCE (same actor_pid → same target_pid) within 30 seconds:
  ETWTI ALLOCVM_REMOTE(Protect ∈ {RWX, RW})
  ETWTI WRITEVM_REMOTE(BytesWritten > 0x100)
  ETWTI CREATE_THREAD_REMOTE OR QUEUEAPCTHREAD_REMOTE
```
**MITRE:** T1055.003, T1055.004
**Confidence:** High
**OCSF fields:** `memory.target_process.pid`, `memory.protection`, `thread.start_address`
**False positives:** Legitimate debuggers; software installers with cross-process injection (rare in signed binaries)

---

## BI-003: LSASS Memory Read Storm

**Pattern:**
```
ETWTI READVM_REMOTE(
  target_process.file.name = lsass.exe
  caller.process.file.name NOT IN {MsMpEng.exe, csrss.exe, lsm.exe, smss.exe, wininit.exe}
  count >= 10 within 5 seconds from same caller_pid
)
```
**MITRE:** T1003.001
**Confidence:** High
**OCSF fields:** `memory.target_process.pid`, `actor.process.file.name`, event count over time window
**False positives:** Crash dump tools (WerFault.exe, procdump.exe running legitimately); check caller binary hash against known-good set

---

## BI-004: Registry UAC Bypass HKCU Write + Auto-Elevating Binary

**Pattern:**
```
SEQUENCE within 60 seconds:
  RegSetValue(
    key_path MATCHES "HKCU\Software\Classes\*\shell\open\command"
               OR "HKCU\Environment\windir"
    actor.integrity_level = Medium
  )
  ProcessStart(
    image_name IN {fodhelper.exe, eventvwr.exe, sdclt.exe, wsreset.exe}
    process.integrity_level = High
    parent.integrity_level = Medium
  )
```
**MITRE:** T1548.002
**Confidence:** High
**OCSF fields:** `reg_key.path`, `reg_value.data`, `process.integrity_level`, `actor.process.integrity_level`
**False positives:** None known; this sequence has no legitimate use case

---

## BI-005: NtUnmapViewOfSection on Freshly-Created Process (Hollowing)

**Pattern:**
```
SEQUENCE within 10 seconds (same actor_pid):
  ProcessStart(new_child, CREATE_SUSPENDED flag)
  ETWTI or APICall NtUnmapViewOfSection(target = new_child_pid)
  ETWTI WRITEVM_REMOTE(target = new_child_pid, size > 0x1000)
  ETWTI SETTHREADCONTEXT_REMOTE(target = new_child_pid)
  ResumeThread(target = new_child_pid)
```
**MITRE:** T1055.012
**Confidence:** High
**OCSF fields:** `process.pid`, `actor.process.pid`, `memory.target_process.pid`
**False positives:** Some JIT-preloading frameworks; very rare; verify with PE signature at injection base

---

## BI-006: Regsvr32 Squiblydoo (Remote Scriptlet Execution)

**Pattern:**
```
ProcessStart(
  image_name = regsvr32.exe
  cmd_line MATCHES "/i:http|/i:https|/i:\\\\[UNC]"
  AND cmd_line CONTAINS "scrobj.dll"
)
```
**MITRE:** T1218.009
**Confidence:** Critical
**OCSF fields:** `process.file.name`, `process.cmd_line`
**False positives:** None; this specific argument pattern has no legitimate administrative use

---

## BI-007: WDigest Cleartext Credential Re-Enable

**Pattern:**
```
RegSetValue(
  key_path MATCHES "HKLM\SYSTEM\CurrentControlSet\Control\SecurityProviders\WDigest"
  value_name = UseLogonCredential
  data_value = 1
)
```
**MITRE:** T1003.001 (pre-positioning)
**Confidence:** High
**OCSF fields:** `reg_key.path`, `reg_value.name`, `reg_value.data`
**False positives:** Some legacy application compatibility configurations; extremely rare on modern systems

---

## BI-008: EtwEventWrite Patch (ntdll .text Modification)

**Pattern:**
```
ETWTI PROTECTVM_LOCAL(
  base_address IN ntdll_text_section_range
  new_protect ∈ {PAGE_EXECUTE_READWRITE, PAGE_READWRITE}
  caller.process.file.name NOT IN {debugger_set}
)
```
**MITRE:** T1562.006
**Confidence:** Critical
**OCSF fields:** `memory.base_address`, `memory.new_protection`, `actor.process.file.name`
**False positives:** Debuggers with write breakpoints; kernel-mode test signing environments

---

## BI-009: Ransomware Write Flood + VSS Deletion

**Pattern:**
```
SEQUENCE within 300 seconds:
  FileWrite STORM(
    actor_pid = constant
    distinct_files > 50
    file_extensions CHANGE from original to encrypted_extension
    write_rate > 10 files/second
  )
  ProcessStart(
    image_name IN {vssadmin.exe, wmic.exe, powershell.exe}
    cmd_line MATCHES "delete.*shadow|shadowcopy.*delete"
    parent_pid = actor_pid OR sibling_of actor_pid
  )
```
**MITRE:** T1486 + T1490
**Confidence:** Critical
**OCSF fields:** `file.name`, `file.path`, `file.extension`, write rate metric
**False positives:** Legitimate backup tools during a full backup run; distinguish by file extension changes

---

## BI-010: Driver Load from Unusual Path + Service Registration

**Pattern:**
```
SEQUENCE within 120 seconds:
  RegSetValue(
    key_path MATCHES "HKLM\SYSTEM\CurrentControlSet\Services\*\ImagePath"
    data_value NOT MATCHES "C:\Windows\System32\drivers\*"
    actor.process.file.name NOT IN {msiexec.exe, trustedinstaller.exe}
  )
  NtLoadDriver(service_key = matching key from above)
  CodeIntegrity Event 3076 OR 8028 OR 3065
```
**MITRE:** T1068, T1014
**Confidence:** High
**OCSF fields:** `reg_key.path`, `reg_value.data`, CodeIntegrity event type
**False positives:** Third-party security software, hardware vendor drivers during update

---

## BI-011: Discovery Burst from Post-Exploitation Context

**Pattern:**
```
ProcessStart CLUSTER(
  image_name IN {systeminfo.exe, whoami.exe, net.exe, ipconfig.exe,
                 nltest.exe, arp.exe, route.exe, netstat.exe, tasklist.exe,
                 qwinsta.exe, wmic.exe, reg.exe, dsquery.exe}
  parent_pid = constant
  parent_image IN {cmd.exe, powershell.exe, wscript.exe, cscript.exe, mshta.exe}
  count >= 5 within 60 seconds
)
```
**MITRE:** T1082, T1016, T1087
**Confidence:** High
**OCSF fields:** `process.file.name`, `actor.process.pid`, event count in time window
**False positives:** IT automation scripts; distinguish by parent being a scripting engine vs. a legitimate admin console

---

## BI-012: DLL Side-Load — Malicious DLL Placed Next to Trusted Binary

**Pattern:**
```
SEQUENCE within 300 seconds:
  FileCreate(
    target.extension = .dll
    target.directory = directory_of_known_signed_application
    actor.process.file.name NOT IN {msiexec.exe, <app_installer>}
  )
  ImageLoad(
    dll_path = target.path from above
    hosting_process = known_signed_application
    load_path NOT MATCHES "C:\Windows\*"
  )
```
**MITRE:** T1574.002
**Confidence:** High
**OCSF fields:** `file.path`, `file.name`, `module.file.path`, `process.file.name`
**False positives:** Application self-update mechanisms that deploy DLLs alongside the host; verify DLL is unsigned or unexpectedly signed

---

## BI-013: Security Log Cleared

**Pattern:**
```
SecurityAuditEvent(EventID = 1102)
OR SystemEvent(EventID = 104)
```
**MITRE:** T1070.001
**Confidence:** Critical
**OCSF fields:** Security Finding `type_uid`, `actor.user.name`
**False positives:** Intentional administrator log maintenance; note the account and correlate with surrounding activity

---

## BI-014: Shadow Copy Deletion

**Pattern:**
```
ProcessStart(
  image_name IN {vssadmin.exe, wmic.exe}
  cmd_line MATCHES "delete.*shadow|shadowcopy.*delete"
)
OR PowerShell 4104(ScriptBlockText MATCHES "Win32_ShadowCopy.*Delete|shadow.*delete")
```
**MITRE:** T1490, T1070.004
**Confidence:** High
**OCSF fields:** `process.cmd_line`, `process.file.name`
**False positives:** System backup rotation scripts; verify no preceding ransomware write storm

---

## BI-015: APC Injection to Alertable Thread

**Pattern:**
```
ETWTI QUEUEAPCTHREAD_REMOTE(
  caller_pid ≠ target_pid
  ApcRoutine_address NOT IN any_loaded_image_range(target_process)
)
```
**MITRE:** T1055.004
**Confidence:** High
**OCSF fields:** `thread.apc_routine`, `actor.process.pid`, `process.pid`
**False positives:** Legitimate cross-process APC use is extremely rare; CLR AppDomain injection uses APC but from CLR image range

---

## BI-016: PowerShell Downgrade to Version 2

**Pattern:**
```
ProcessStart(
  image_name = powershell.exe
  cmd_line MATCHES "-[vV][eE][rR][sS].*2|-[vV]\s*2"
)
```
**MITRE:** T1562.006 (ETW bypass via PS v2)
**Confidence:** High
**OCSF fields:** `process.cmd_line`, `process.file.name`
**False positives:** Legacy script compatibility testing; rare in production environments

---

## BI-017: Comsvcs.dll LSASS Minidump (LOLBin)

**Pattern:**
```
ProcessStart(
  image_name = rundll32.exe
  cmd_line MATCHES "comsvcs.*[Mm]ini[Dd]ump|comsvcs.*MiniDump"
)
```
**MITRE:** T1003.001
**Confidence:** Critical
**OCSF fields:** `process.cmd_line`, `process.file.name`
**False positives:** None; this specific combination has no legitimate administrative purpose

---

## BI-018: Timestomping of Executable Artifact

**Pattern:**
```
FileSetInfo(
  target.extension IN {.exe, .dll, .ps1, .bat, .vbs, .sys}
  info_class = FileBasicInformation
  actor.process.file.name NOT IN {robocopy.exe, xcopy.exe, msiexec.exe, backup_agents}
  new_timestamp < file.creation_time
    OR (file.SI_timestamps ≠ file.FN_timestamps by > 2 hours)
)
```
**MITRE:** T1070.006
**Confidence:** Medium
**OCSF fields:** `file.modified_time`, `file.created_time`, `actor.process.file.name`
**False positives:** File synchronization tools, backup restore operations

---

## BI-019: Kernel Driver Vulnerability Exploitation (IOCTL to Known-Vulnerable Driver)

**Pattern:**
```
DeviceIoControl(
  device_name IN known_vulnerable_driver_device_names
  IOCTL_code IN known_exploit_codes_for_that_driver
  actor.process.integrity_level = Medium
)
FOLLOWED_BY within 60 seconds:
  ETWTI PROTECTVM in kernel range OR NtLoadDriver for unsigned driver
```
**MITRE:** T1068
**Confidence:** Critical
**OCSF fields:** Device name, IOCTL code, actor integrity level, subsequent kernel operation
**False positives:** Legitimate use of the vulnerable driver for its intended purpose (hardware management tools)

---

## BI-020: Token Impersonation to SYSTEM + Process Spawn

**Pattern:**
```
SecurityEvent 4648(
  actor.process.file.name NOT IN {services.exe, lsass.exe, svchost.exe}
  impersonated_user = SYSTEM OR impersonated_user IN domain_admin_set
)
FOLLOWED_BY within 30 seconds:
  ProcessStart(
    new_process.token.user = SYSTEM
    parent.token.user ≠ SYSTEM
  )
```
**MITRE:** T1134.001, T1134.002
**Confidence:** High
**OCSF fields:** `actor.user.uid`, `process.user.uid`, Event 4648 fields
**False positives:** Service control processes (services.exe, svchost.exe) legitimately impersonate SYSTEM; exclude these actors

---

## BI-021: Certutil Download and Decode

**Pattern:**
```
ProcessStart(
  image_name = certutil.exe
  cmd_line MATCHES "-urlcache|-decode|-decodehex|-encode"
)
FOLLOWED_BY within 60 seconds:
  FileCreate(
    actor.process.pid = certutil_pid
    target.path MATCHES "%TEMP%|%USERPROFILE%|%APPDATA%"
  )
```
**MITRE:** T1218.003, T1105 (Ingress Tool Transfer)
**Confidence:** High
**OCSF fields:** `process.cmd_line`, `file.path`
**False positives:** Certificate management scripts using decode for certificate format conversion (very rare in production)

---

## BI-022: Named Pipe Creation by Lateral Movement Tool

**Pattern:**
```
NamedPipeCreate(
  pipe_name MATCHES \\.\pipe\(msagent_|MSSE-|postex_|status_|mojo\.|chrome\..*|)
    OR pipe_name_entropy > 4.5  -- random-looking pipe name
  actor.process.file.name NOT IN {chrome.exe, firefox.exe, mojo_host.exe, system}
)
```
**MITRE:** T1021, T1090 (Proxy via named pipe)
**Confidence:** Medium
**OCSF fields:** `file.path` (pipe path), `actor.process.file.name`
**False positives:** Mojo IPC used by Chromium; filter by known legitimate pipe name prefixes

---

## BI-023: DKOM-Suspected Hidden Process

**Pattern:**
```
ETWTI_EVENT(ProcessId = X, event_type = any)
  AND NtQuerySystemInformation(SystemProcessInformation) does NOT contain PID X
  AND PID X was previously visible in process enumeration
```
**MITRE:** T1014
**Confidence:** High
**OCSF fields:** `process.pid`, internal process inventory vs. ETWTI stream
**False positives:** Race condition during process exit (transient); sustained absence for > 5 seconds is reliable

---

## BI-024: NTFS USN Journal Deletion

**Pattern:**
```
ProcessStart(
  image_name = fsutil.exe
  cmd_line MATCHES "usn.*deletejournal|usn.*deletej"
)
```
**MITRE:** T1070
**Confidence:** High
**OCSF fields:** `process.cmd_line`, `process.file.name`
**False positives:** Storage maintenance scripts in very specialized environments (disk reclamation); correlate with surrounding context

---

## BI-025: Bulk Sensitive File Staging (Pre-Exfiltration)

**Pattern:**
```
SEQUENCE within 300 seconds:
  FileRead CLUSTER(
    actor_pid = constant
    actor.process.file.name NOT IN document_app_set
    target.extension IN {.docx, .xlsx, .pdf, .kdbx, .pfx, .pem, .config, .json, .sql}
    distinct_file_count >= 20
    distinct_directory_count >= 3
  )
  FileCreate(
    actor_pid = same constant
    target.extension IN {.zip, .7z, .rar, .tar.gz}
    target.path MATCHES temp_or_userwritable_path
  )
```
**MITRE:** T1005 + exfiltration staging
**Confidence:** High
**OCSF fields:** `file.path`, `file.extension`, `actor.process.pid`, count metrics
**False positives:** Backup agents (Veeam, Acronis) — exclude by actor image name; IT audit tools

---

## BI-026: AppInit_DLLs Persistence Write

**Pattern:**
```
RegSetValue(
  key_path MATCHES "HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Windows\AppInit_DLLs"
  data_value ≠ ""
  actor.process.file.name NOT IN {trustedinstaller.exe, msiexec.exe}
)
```
**MITRE:** T1574 (DLL injection via AppInit)
**Confidence:** High
**OCSF fields:** `reg_key.path`, `reg_value.data`, `actor.process.file.name`
**False positives:** Third-party system utilities that legitimately use AppInit_DLLs (becoming increasingly rare since Windows 8 restrictions)

---

## BI-027: Reflective DLL — VAD Anomaly Detected

**Pattern:**
```
VAD_SCAN(process):
  node.VadType = VadNone
  AND node.Protection ∈ {PAGE_EXECUTE_READ, PAGE_EXECUTE_READWRITE}
  AND memory_content[0:2] = "MZ"  -- PE signature at base
  AND no LDR_DATA_TABLE_ENTRY for node.BaseAddress
  AND no Image Load callback event for node.BaseAddress
```
**MITRE:** T1055.001
**Confidence:** High
**OCSF fields:** VAD inspection results, module list cross-reference
**False positives:** Some self-loading PE loaders in legitimate tools (uncommon and typically signed)
