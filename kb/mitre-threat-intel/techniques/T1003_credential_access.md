---
technique_id: T1003
technique_name: OS Credential Dumping
tactic: [Credential Access]
platform: Windows
severity: Critical
data_sources: [ETWTI, ETW-Security, ETW-Process, ETW-File]
mitre_url: https://attack.mitre.org/techniques/T1003/
---

# T1003 — OS Credential Dumping

## Description (T1003)

T1003 OS Credential Dumping covers techniques that extract credential material — password hashes, Kerberos tickets, cleartext passwords, or NTLM tokens — from Windows memory or credential stores. The most impactful target is the Local Security Authority Subsystem Service (`lsass.exe`), which maintains all active authentication state on a Windows system: password hashes for all logged-on users, Kerberos Ticket Granting Tickets (TGTs), NTLM session keys, and (in legacy configurations) cleartext passwords stored by the WDigest authentication provider.

Credential material extracted from LSASS enables lateral movement via Pass-the-Hash (PTH), Pass-the-Ticket (PTT), and Overpass-the-Hash techniques without requiring the plaintext password. A single successful credential dump from a domain controller or administrative workstation can yield credentials for the entire domain.

---

## Windows Implementation Details (T1003)

LSASS (`lsass.exe`) is a protected process on modern Windows. It runs as `NT AUTHORITY\SYSTEM` and is normally granted `PROCESS_QUERY_LIMITED_INFORMATION` access by non-privileged processes. Reading its memory requires `PROCESS_VM_READ` access, which `OpenProcess` refuses to grant to non-administrator processes. Administrator processes can open LSASS with full access, subject to PPL (Protected Process Light) restrictions.

Windows 8.1 and later can run LSASS as a PPL (`ProtectionLevel = PS_PROTECTED_LIGHT`). A PPL process can only be opened by processes with equal or higher protection level. Standard EDR agents run as `PS_PROTECTED_LIGHT` (Antimalware), giving them access to LSASS even when PPL is enabled; standard administrator-level malware cannot open a PPL LSASS without a kernel exploit to remove the protection bit from the EPROCESS structure.

The three canonical LSASS dump techniques are:

**MiniDumpWriteDump**: The standard Win32 API for creating a minidump. Invoked from a custom dumper or from tools like ProcDump (`procdump.exe -ma lsass.exe`). The dump file is a self-contained memory snapshot that can be analyzed offline with Mimikatz or similar tools. Requires opening LSASS with `PROCESS_QUERY_INFORMATION | PROCESS_VM_READ`.

**Direct LSASS memory read via NtReadVirtualMemory**: Bypasses user-mode hooking on `ReadProcessMemory` by calling the native API directly. Credential parsing is done in-memory by the dumper without writing a dump file to disk.

**LSASS memory via kernel driver**: A kernel-mode driver opens LSASS by bypassing user-mode access checks and copying the process memory. This defeats user-mode ETWTI and PPL simultaneously, but requires kernel code execution.

The SAM (Security Account Manager) database at `HKLM\SAM` contains NTLM hashes for local accounts. It is locked by the SAM service while running; attackers dump it via VSS (Volume Shadow Copy), registry export after bypassing ACLs (`reg.exe save HKLM\SAM`), or by accessing the raw hive file through volume access.

DPAPI (Data Protection API) master keys, stored in `%APPDATA%\Microsoft\Protect\`, encrypt browser-saved passwords, RDP credential blobs, and application credentials. The `CryptUnprotectData` API can decrypt DPAPI blobs if called from the same user context that encrypted them; attackers running under the target user's token can silently decrypt all stored credentials.

---

## Observable Artifacts (T1003)

- A process other than `procdump.exe`, `Task Manager`, or `ProcExp` opening `lsass.exe` with `PROCESS_VM_READ | PROCESS_QUERY_INFORMATION` access.
- A process calling `MiniDumpWriteDump` with `lsass.exe` as the target.
- A `.dmp` file created in `%TEMP%`, `C:\Windows\Temp`, or any user-writable path with a size consistent with an LSASS dump (typically 50–500 MB depending on session count and configuration).
- `reg.exe save HKLM\SAM`, `reg.exe save HKLM\SYSTEM`, or `reg.exe save HKLM\SECURITY` in a command line — the three hives needed to extract local account hashes offline.
- `vssadmin create shadow /for=C:` followed by file copy from `\\?\GLOBALROOT\Device\HarddiskVolumeShadowCopy*\Windows\System32\config\SAM`.
- `comsvcs.dll` minidump: `rundll32.exe comsvcs.dll, MiniDump <lsass_pid> C:\temp\lsass.dmp full` — a LOLBin variant of MiniDumpWriteDump using a system DLL.

---

## ETW / eBPF Telemetry Signals (T1003)

### Microsoft-Windows-Threat-Intelligence (ETWTI)

ETWTI provides the highest-fidelity signals for LSASS access because it fires from kernel mode and cannot be suppressed by user-mode hooking.

- **READVM**: Fires on `NtReadVirtualMemory` calls where the target process differs from the caller. `TargetPid` field identifying `lsass.exe` is the critical condition. This event fires for every read operation — a dumper reading LSASS memory over multiple calls will generate a storm of READVM events from the same caller PID to the lsass.exe PID. The volume of READVM events (> threshold per second from a single caller to lsass.exe) distinguishes credential dumping from legitimate LSASS query operations.
- **ALLOCVM_REMOTE + WRITEVM_REMOTE targeting lsass.exe**: Less common but some reflective dumpers write a helper into LSASS's own address space.
- **OPENPROCESS_REMOTE (if ETWTI exposes handle opens)**: Some ETWTI builds expose handle acquisition events; an `OpenProcess` with VM_READ access targeting lsass.exe PID is a definitive indicator.

### Microsoft-Windows-Security-Auditing

- **Event ID 4656** (Handle Requested): When object access auditing is enabled for the LSASS process object, this event fires when any process requests a handle to lsass.exe. The `AccessMask` field reveals whether `PROCESS_VM_READ (0x0010)` was requested.
- **Event ID 4663** (Object Access): Fires on actual LSASS memory reads if file/process object auditing is configured with success auditing.
- **Event ID 4673** (Privileged Service Call): Fires when `SeDebugPrivilege` is used, which is required to open LSASS with VM_READ access. A non-system process enabling SeDebugPrivilege and then immediately accessing LSASS is a high-confidence indicator.
- **Event ID 4688** (Process Creation): `procdump.exe`, `mimikatz.exe` (by name), `lsassdump`, `nanodump`, and variants identifiable by command line patterns (`-ma lsass`, `sekurlsa::logonpasswords`, `lsadump`).

### Microsoft-Windows-Kernel-File

- **File Create**: A dump file created by a non-system process, particularly with the `.dmp` extension and a file size in the range consistent with LSASS dumps (> 10 MB, typically 50–500 MB), in a user-writable directory.
- **File Create on shadow copy path**: File reads from `\\.\HarddiskVolumeShadowCopyN\Windows\System32\config\` indicate SAM/SYSTEM hive extraction via VSS.

### Microsoft-Windows-Kernel-Process

- **Event ID 1 (ProcessStart)**: Command lines matching known dumper signatures:
  - `procdump.exe -ma lsass`
  - `taskmgr.exe` (legitimate but watch for task manager dump of LSASS initiated remotely)
  - `rundll32.exe comsvcs.dll, MiniDump <pid>`
  - `sqlwriter.exe`, `vscoordinator.exe` spawned unexpectedly (VSS LOLBin for shadow copy access)

---

## Evasion Variants (T1003)

- **Process Forking (LSASS fork)**: On Windows 10+, `NtCreateProcessEx` with the PPL parent trick can create a child of LSASS by forking it (`NtCreateProcessEx(ProcessFlags = PROCESS_CREATE_FLAGS_INHERIT_HANDLES | ..., SectionHandle = NULL)`). The forked LSASS child is not PPL and can be dumped by the attacker without directly accessing the protected parent. ETWTI still fires READVM on the fork target if the attacker reads the child's memory.
- **Comsvcs.dll minidump via WerFault**: Spawning `WerFault.exe -u -p <lsass_pid> -ip <lsass_pid> -s 65536` triggers Windows Error Reporting to generate a minidump of LSASS. WerFault.exe is a system binary with legitimate reasons to access process memory, making this harder to alert on by image name alone. The file write to a non-standard WER path is the residual indicator.
- **LSASS driver access (kernel)**: A kernel driver reads LSASS memory directly via `MmCopyMemory` or by mapping the process's physical pages. This generates no ETWTI events because ETWTI monitors user-mode API calls, not kernel-to-kernel memory access. Detection requires driver load events (T1068 indicators) as a precursor.
- **Credential material from registry via volume access**: Bypassing registry ACLs by opening the raw volume device (`\\.\PhysicalDrive0`) and parsing NTFS to locate and read the SAM hive directly. No registry API calls are made; detection relies on volume device handle opens from unexpected processes.
- **DCSync (remote credential extraction)**: Instead of dumping LSASS locally, the attacker uses a domain account with `DS-Replication-Get-Changes-All` rights to request domain controller replication of all password hashes via the MS-DRSR (Directory Replication Service Remote Protocol). No local LSASS access is needed; the replication request appears as normal AD replication traffic. Event ID 4662 with the replication GUID in the Properties field is the Active Directory-side indicator.

---

## Detection Logic (T1003)

### LSASS Memory Read Storm (ETWTI)

```
ETWTI READVM(
  TargetPid = lsass_pid
  CallerPid ≠ lsass_pid
  CallerProcess.file.name NOT IN {MsMpEng.exe, csrss.exe, lsm.exe, smss.exe}
  count > 20 within 5 seconds from same CallerPid
)
→ T1003.001 Critical (0.95)
```

### Minidump API Call

```
APICall(
  function = MiniDumpWriteDump
  target_process_name = lsass.exe
)
→ T1003.001 Critical (0.95)
```

### Registry SAM Dump

```
ProcessStart(
  image_name = reg.exe
  cmd_line MATCHES "save.*HKLM\\SAM|save.*HKLM\\SYSTEM|save.*HKLM\\SECURITY"
)
→ T1003.002 High (0.90)
```

### Comsvcs Minidump LOLBin

```
ProcessStart(
  image_name = rundll32.exe
  cmd_line MATCHES "comsvcs.*MiniDump|comsvcs.*minidump"
)
→ T1003.001 Critical (0.95) — explicit LSASS dump via LOLBin
```

### SeDebugPrivilege Enabled then LSASS Handle

```
SEQUENCE within 10 seconds:
  Step 1: Event 4673 (SeDebugPrivilege used, actor NOT IN system_procs)
  Step 2: Event 4656 (Handle request to lsass.exe with VM_READ)
→ T1003 High (0.88)
```

---

## Sub-Techniques (T1003)

### T1003.001 — LSASS Memory

The primary sub-technique. LSASS process memory contains authentication packages (msv1_0.dll for NTLM, kerberos.dll for Kerberos, wdigest.dll for WDigest) that cache credential material. The extracted memory is parsed by tools like Mimikatz to recover hashes and tickets.

### T1003.002 — Security Account Manager (SAM)

The SAM registry hive stores NTLM hashes for local accounts, encrypted with the SYSKEY from the SYSTEM hive. Both hives are required to decrypt local account hashes. The SAM is locked while Windows is running; extraction requires VSS, offline access, or reg.exe save with an administrator token.

### T1003.004 — LSA Secrets

`HKLM\SECURITY\Policy\Secrets` stores LSA secrets: service account passwords, domain machine account credentials, cached domain credentials (DCC), and VPN/dial-up credentials. Accessible with SYSTEM privileges; Mimikatz `lsadump::secrets` extracts them.

### T1003.006 — DCSync

Domain replication abuse. The attacker uses `DS-Replication-Get-Changes-All` GUID rights to pull password hashes from a domain controller as if performing normal AD replication. No local access to the DC is required; the attack can be executed from any domain-joined machine with the right permissions.

---

## Related Techniques (T1003)

- T1055 (Process Injection) — Injecting into LSASS is an alternative to dumping its memory externally
- T1068 (Exploitation for Privilege Escalation) — Kernel exploits can remove LSASS PPL protection
- T1134 (Access Token Manipulation) — Impersonating SYSTEM token enables LSASS access
- T1070.001 (Clear Windows Event Logs) — Post-dump log clearing removes the 4656/4663 audit trail

---

## OCSF Mapping (T1003)

| OCSF Class | Class ID | Discriminating Fields | Technique Confidence |
|---|---|---|---|
| Process Activity | 1007 | `process.file.name = procdump.exe OR rundll32.exe`, cmd_line matches dump pattern | T1003.001 Critical |
| Memory Activity (extension) | custom | ETWTI READVM, `target_process.file.name = lsass.exe`, read storm | T1003.001 Critical |
| File Activity | 1001 | `activity_id = Create`, `.dmp` extension, size > 10MB, user-writable path | T1003.001 High |
