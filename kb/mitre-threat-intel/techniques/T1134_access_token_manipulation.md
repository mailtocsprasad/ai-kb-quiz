---
technique_id: T1134
technique_name: Access Token Manipulation
tactic: [Defense Evasion, Privilege Escalation]
platform: Windows
severity: High
data_sources: [ETW-Security, ETW-Process, ETWTI]
mitre_url: https://attack.mitre.org/techniques/T1134/
---

# T1134 — Access Token Manipulation

## Description (T1134)

T1134 Access Token Manipulation covers adversary techniques that alter the access token associated with a process or thread to change the security context under which code executes. Windows access tokens are kernel objects that carry the identity and privileges attached to a running process or thread. By manipulating tokens — through theft, duplication, impersonation, or creation — an attacker can execute code as a different user account, elevate from medium to high integrity, or acquire SYSTEM-level privileges without exploiting a kernel vulnerability.

The Windows Security Reference Monitor (SRM) performs every access check by evaluating the calling thread's effective token against the target object's security descriptor. A thread's effective token is the impersonation token if one is set, or the parent process's primary token otherwise. Controlling the token means controlling what operations are permitted.

---

## Windows Implementation Details (T1134)

### Token Structure

An access token is represented in kernel memory by a `TOKEN` structure allocated from nonpaged pool. The primary token for a process is referenced by `EPROCESS.Token`, stored as an `EX_FAST_REF` pointer (the low 3 bits encode a reference count hint; the actual pointer is obtained by masking `& ~0x7`). Thread-level impersonation tokens are stored in `ETHREAD.ClientSecurity`, a `PS_CLIENT_SECURITY_CONTEXT` structure that holds both the impersonation token pointer and the impersonation level.

Key fields in the TOKEN structure relevant to T1134:

- **UserAndGroups**: Array of `SID_AND_ATTRIBUTES` entries. The first entry is always the user's primary SID. Subsequent entries are group SIDs with attribute flags (`SE_GROUP_ENABLED`, `SE_GROUP_USE_FOR_DENY_ONLY`).
- **Privileges**: `SEP_TOKEN_PRIVILEGES` structure containing a `Present` bitmask, `Enabled` bitmask, and `EnabledByDefault` bitmask. Each bit corresponds to a system privilege (`SeDebugPrivilege`, `SeImpersonatePrivilege`, `SeAssignPrimaryTokenPrivilege`, etc.).
- **IntegrityLevelIndex**: Points to a mandatory integrity label SID (`S-1-16-x`) that determines the token's integrity level. SYSTEM tokens carry `S-1-16-16384` (System integrity).
- **AuthenticationId**: A `LUID` that uniquely identifies the logon session. All tokens belonging to the same interactive logon share the same `AuthenticationId`; a new logon session gets a fresh LUID.
- **TokenType**: `TokenPrimary` (attached to a process) or `TokenImpersonation` (thread-level; carries an impersonation level field of `SecurityAnonymous`, `SecurityIdentification`, `SecurityImpersonation`, or `SecurityDelegation`).

### Token Acquisition Flow

To steal or duplicate a token from another process, an attacker needs a handle to that process (or directly to the target token):

1. `OpenProcess(PROCESS_QUERY_INFORMATION, target_pid)` — opens the target process to query its token.
2. `OpenProcessToken(process_handle, TOKEN_DUPLICATE | TOKEN_QUERY)` — opens the primary token of the target process.
3. `DuplicateTokenEx(source_token, MAXIMUM_ALLOWED, NULL, SecurityImpersonation, TokenImpersonation, &new_token)` — creates a new impersonation token derived from the source.
4. `SetThreadToken(NULL, new_token)` or `ImpersonateLoggedOnUser(new_token)` — installs the impersonation token on the current thread.

From this point, all access checks performed against the current thread use the impersonation token, giving the thread the security context of the stolen identity.

---

## Observable Artifacts (T1134)

- An `OpenProcess` call with `PROCESS_QUERY_INFORMATION` access to a high-privilege process (SYSTEM, LSA, TrustedInstaller) from a medium-integrity process.
- Token duplication events: `NtDuplicateToken` or `DuplicateTokenEx` calls where the source token belongs to a process with higher privilege.
- `SetThreadToken` or `NtSetInformationThread(ThreadImpersonationToken)` calls that change a thread's effective identity.
- Security audit event 4624 (Logon) with `LogonType = 9 (NewCredentials)` or `LogonType = 5 (Service)` appearing without a preceding interactive authentication — signals synthetic logon from token manipulation.
- Security audit event 4648 (Logon using explicit credentials) from non-expected processes.
- Security audit event 4672 (Special privileges assigned to new logon) when a process acquires a token bearing `SeDebugPrivilege` or `SeTcbPrivilege`.

---

## ETW / eBPF Telemetry Signals (T1134)

### Microsoft-Windows-Security-Auditing

- **Event 4624** (Account Logon): Generated when a new logon session is created. Fields: `LogonType`, `SubjectUserName`, `TargetUserName`, `LogonProcessName`, `IpAddress`. Unusual `LogonProcessName` values (anything other than `User32`, `Advapi`, `NtLmSsp`, `Kerberos`, `Negotiate`) indicate synthetic logon from token manipulation or `LsaLogonUser`.
- **Event 4648** (Logon with explicit credentials): Fires when a program uses explicit credentials to create a new security context. `SubjectProcessName` being an attacker tool (non-system binary) is the key discriminator.
- **Event 4656** (Handle request to an object): When the target object is a Process with `PROCESS_QUERY_INFORMATION` rights, and the subject is not a security tool, this is a token-acquisition precursor.
- **Event 4703** (Token Right adjusted): Fires when privileges are enabled/disabled on a token. An attacker enabling `SeDebugPrivilege` (privilege ID 20) on a token that did not have it enabled is a high-confidence T1134 indicator.

### Microsoft-Windows-Kernel-Process

- Thread creation events where the creating thread has an impersonation token with higher privilege than the process's primary token. The discrepancy between the process token's integrity level and the thread's effective token is captured in ETHREAD.ClientSecurity.
- `Win32StartAddress` of threads created after a token manipulation: if they begin execution in an injected or non-module-backed region, T1055 + T1134 combination is indicated.

### Microsoft-Windows-Threat-Intelligence (ETWTI)

- ETWTI does not emit a dedicated token-manipulation event, but ALLOCVM_REMOTE and WRITEVM_REMOTE events on lsass.exe (when credential theft is combined with token manipulation) provide corroborating signals.

---

## Sub-Techniques (T1134)

### T1134.001 — Token Impersonation / Theft (T1134)

T1134.001 covers stealing a token from an existing process and impersonating it at the thread level. This is the most common variant and is widely used by post-exploitation frameworks (Cobalt Strike's `steal_token`, Meterpreter's `getsystem`, etc.).

Common targets for token theft: `winlogon.exe` (SYSTEM, runs with SeTcbPrivilege), `lsass.exe` (SYSTEM, TCB), `services.exe` (SYSTEM), named pipe server impersonation (see below).

**Named pipe impersonation**: An attacker creates a named pipe server, coerces a SYSTEM-level service to connect to it (by placing a pipe with a name the service expects, exploiting a UNC path, or using a service-specific coercion technique), and calls `ImpersonateNamedPipeClient` on the connected client. This yields an impersonation token at the connecting client's integrity level without any `OpenProcess` call — making it harder to detect via process-handle auditing alone. Detection: named pipe creation by a non-system process followed immediately by `ImpersonateNamedPipeClient`, with the creating process subsequently exhibiting SYSTEM-level behavior.

### T1134.002 — Create Process with Token (T1134)

T1134.002 uses the stolen or duplicated primary token to launch a new process with a different security context via `CreateProcessWithTokenW` or `CreateProcessAsUserW`. The new process inherits the token as its primary token.

Detection: Security audit event 4688 (Process creation) where the creator's integrity level is lower than the new process's integrity level, and there is no corresponding elevation prompt event (Event 4703 or UAC-related audit).

### T1134.003 — Make and Impersonate Token (T1134)

T1134.003 uses `LogonUser` or `LsaLogonUser` to create a new logon session from known credentials (username + password or NTLM hash in pass-the-hash scenarios), then uses the resulting primary token to impersonate or create processes. This variant generates a new logon session (new `AuthenticationId` LUID in the token), unlike impersonation of an existing token which reuses the source token's `AuthenticationId`.

Detection: `LogonUser` calls with `LOGON32_LOGON_NEW_CREDENTIALS` (type 9) from processes that are not authentication services, followed by `CreateProcessWithTokenW`. Security event 4624 with LogonType 9 + unique `AuthenticationId` not previously seen in the system.

### T1548 / T1548.002 — UAC Bypass (T1134 adjacent)

UAC (User Account Control) bypass techniques use COM object elevation, registry hijacking, or auto-elevation of system binaries to obtain a high-integrity process token from a medium-integrity context without triggering the UAC consent dialog. While technically a separate technique (T1548.002), it often precedes T1134 token theft in an attack chain.

Common UAC bypass patterns detected by ai-procwatch-mcp:
- Registry write to `HKCU\Software\Classes\<progid>\shell\open\command` followed by execution of a COM auto-elevation binary (e.g., `fodhelper.exe`, `eventvwr.exe`).
- Writing a DLL to a directory searched before `System32` and launching an auto-elevated process that loads it (DLL hijacking + UAC bypass combination).

Detection: ETW Registry event `SetValue` on `HKCU\Software\Classes\ms-settings\shell\open\command` or similar COM hijack keys, followed within 10 seconds by a high-integrity child process creation from `fodhelper.exe` or similar auto-elevation binary.

---

## Detection Logic (T1134)

### High-Confidence Token Theft Sequence

```
OpenProcess(PROCESS_QUERY_INFORMATION, pid_of_system_process)
  → OpenProcessToken(process_handle, TOKEN_DUPLICATE)
  → DuplicateTokenEx(source_token, ..., SecurityImpersonation, TokenImpersonation)
  → SetThreadToken(NULL, new_token) OR ImpersonateLoggedOnUser(new_token)
```

If the source token belongs to a SYSTEM-integrity process and the calling process is at medium integrity: confidence T1134.001 = **High (0.90+)**.

### Named Pipe Coercion Pattern

```
CreateNamedPipe(pipename, PIPE_ACCESS_DUPLEX | PIPE_READMODE_BYTE, ...)
  → [target service connects to pipe within 30s]
  → ImpersonateNamedPipeClient(pipe_handle)
  → CreateProcessWithTokenW(...) OR SetThreadToken(...)
```

Confidence T1134.001 = **High (0.85)**.

---

## OCSF Mapping (T1134)

| OCSF Class | Class ID | Discriminating Fields | Technique Confidence |
|---|---|---|---|
| User Activity | 3001 | `activity_id = Impersonate`, `user.type = SYSTEM`, `actor.process.integrity_level < target.integrity_level` | T1134.001 High |
| Process Activity | 1007 | `activity_id = Launch`, `process.user.uid = SYSTEM`, `actor.process.user.uid ≠ SYSTEM` | T1134.002 High |
