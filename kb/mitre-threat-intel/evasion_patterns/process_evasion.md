---
content_type: evasion
category: process_evasion
platform: Windows
techniques: [T1055, T1134, T1548, T1218]
severity: High
data_sources: [ETW-Process, ETWTI, ETW-Security]
---

# Process Evasion Patterns

Process evasion techniques manipulate the apparent identity, lineage, or behavior of a process to defeat detection rules that rely on process name, parent-child relationships, or command-line content. These techniques share the goal of making malicious activity appear to originate from a trusted process context.

---

## PE-001: PPID Spoofing (Parent Process ID Spoofing)

**Technique:** T1134, T1055 (supporting technique)

**Description:** The `CreateProcess` extended attribute `PROC_THREAD_ATTRIBUTE_PARENT_PROCESS` allows a process to specify an arbitrary existing process as its nominal parent. The created process's `EPROCESS.InheritedFromUniqueProcessId` field is set to the spoofed parent's PID, making process-tree analysis tools and EDR parent-chain rules see a false lineage.

Common use: Spawning a malicious child that appears to be a child of `explorer.exe`, `svchost.exe`, or `winlogon.exe` rather than the actual malicious parent (e.g., `wscript.exe` or `powershell.exe`). Parent-process-based detection rules (e.g., "alert if `cmd.exe` spawns from a non-shell parent") are defeated when the attacker makes `cmd.exe` appear to be a child of `explorer.exe`.

**Detection approaches:**

- **Handle correlation**: Creating a process with a spoofed parent requires opening the spoofed parent's process with `PROCESS_CREATE_PROCESS` access. The handle acquisition is detectable via ETWTI or Security Event 4656 — a process opening `explorer.exe` for `PROCESS_CREATE_PROCESS` access is unusual for non-system processes.
- **ETW process ancestry vs. handle inheritance**: The kernel records both the actual creating process (the caller of `NtCreateUserProcess`) and the nominal parent in EPROCESS. Some ETW implementations expose the actual creating PID separately from the inherited PID. Comparing `ActualCreatorPid` against `InheritedFromPid` reveals spoofing.
- **Behavioral mismatch**: A process whose nominal parent is `explorer.exe` but whose actual behavior (encoded PowerShell commands, network connections, process injection) is inconsistent with anything `explorer.exe` legitimately spawns is a strong indicator regardless of the parent PID.

**Telemetry signals:**

- `PROCESS_CREATE_PROCESS` access on a non-child process from an unusual actor (ETWTI or Event 4656).
- A process named `cmd.exe`, `powershell.exe`, or a scripting engine with `InheritedFromUniqueProcessId` pointing to `explorer.exe` but whose actual command line arguments are malicious.

---

## PE-002: Process Hollowing

**Technique:** T1055.012

**Description:** A legitimate process is created in `CREATE_SUSPENDED` state, its image is unmapped, and a malicious PE is written into its address space before the thread is resumed. The process's `SeAuditProcessCreationInfo.ImageFileName` still reflects the original binary path, so process-name-based rules see the legitimate name. Process hollowing is covered in detail in `T1055_process_injection.md`; this entry focuses on its evasion characteristics.

**Evasion achieved:** Process name allow-listing, parent-chain rules keyed on child process name, firewall rules based on process image name.

**Key detection residue that survives hollowing:**

- The VAD tree contains a private committed region at the process image base address (`VadType = VadNone`) where a mapped image (`VadType = VadImageMap`) would normally be. This is the definitive kernel-level indicator that survives even if the attacker patches all usermode enumeration APIs.
- The `NtUnmapViewOfSection` call on a freshly created process is always anomalous.
- ETWTI SETTHREADCONTEXT_REMOTE before the first thread is resumed.

---

## PE-003: Process Doppelganging

**Technique:** T1055.013 — see `T1055_013_process_doppelganging.md` for full detail.

**Summary:** Uses NTFS transacted file I/O to create an image mapping from a file that is overwritten within an uncommitted transaction. The transaction is never committed; the backing file reverts to its original content after the mapping is created. The process runs from a section backed by a "phantom" file state that no longer exists on disk. Tools that hash the on-disk image to verify process integrity find the legitimate binary; the running code is different. Detection relies on USN Journal transaction events and section-creation anomalies.

---

## PE-004: Token Impersonation for Process Identity Laundering

**Technique:** T1134.001

**Description:** A process operating under its own limited token can call `ImpersonateLoggedOnUser` or `SetThreadToken` to adopt the security context of a higher-privileged user for a thread. Subsequent process creations from this thread (`CreateProcessWithTokenW`, `CreateProcessAsUserW`) inherit the impersonated token, making the child appear to be owned by the impersonated user.

**Impact on detection:** Process-ownership-based detection rules ("alert if `powershell.exe` runs as SYSTEM when parent is a user-mode process") are defeated when the user-mode parent has successfully impersonated SYSTEM or a service account before spawning the child.

**Detection:** Token impersonation transitions are visible via Security Event 4648 (Explicit Credential Use) and ETWTI events if the SeImpersonatePrivilege use is audited. The mismatch between the parent process's primary token and the child's primary token is detectable by comparing their `TokenUser` SIDs.

---

## PE-005: Argument Obfuscation to Defeat Command-Line Detection

**Technique:** T1027, T1059

**Description:** Process command-line arguments are the primary detection surface for scripting-engine abuse. Several obfuscation techniques defeat string-matching rules applied to command lines:

- **Caret escaping** (`p^o^w^e^r^s^h^e^l^l`): `cmd.exe` strips carets before passing the string to `CreateProcess`; `powershell.exe` receives the unobfuscated name.
- **Quote insertion** (`po"wer"she"ll"`): Quotes in the middle of a binary name are stripped by `cmd.exe`.
- **Environment variable substitution**: `%COMSPEC%` → `cmd.exe`; `%systemroot%\system32\powershell.exe`. The command line stored in the process's PEB may show the unexpanded form.
- **Window minimization flags**: Flags like `-w hidden`, `-WindowStyle Hidden` hide the PowerShell window but are visible in the command line.
- **Alternate parameter separators**: PowerShell accepts `-` or `/` as parameter prefix and is case-insensitive. `-eNcodedCoMmand` is equivalent to `-EncodedCommand`.

**Detection:** ETW-Process Event ID 1 records the command line as passed to `NtCreateUserProcess` — the shell-expanded version. PowerShell Script Block Logging (Event ID 4104) captures the evaluated content after all obfuscation is resolved.

---

## PE-006: Phantom DLL Injection (Module Stomping)

**Technique:** T1055

**Description:** Instead of allocating new memory, the attacker overwrites the `.text` section of an already-loaded DLL in the target process with shellcode. The VAD entry remains `VadType = VadImageMap` with a backing file object — the legitimate DLL file. Static VAD analysis sees a legitimate image mapping; the actual content of the section is attacker shellcode.

**Detection:**

- Hash-based: Compute a hash of the in-memory `.text` section and compare against the hash of the on-disk PE. A mismatch indicates stomping. Expensive at scale but definitive.
- CFG (Control Flow Guard) anomaly: Shellcode executing from inside a mapped image region will often not have valid CFG bitmap entries for its jump targets, causing CFG violations if enforcement is enabled.
- ETWTI WRITEVM_REMOTE: Writing to the `.text` section of an existing mapped image in a remote process generates a WRITEVM_REMOTE event pointing into a VadImageMap region — unusual because legitimate cross-process writes target newly-allocated memory, not existing image sections.

---

## Summary: Evasion → Detection Pivot

| Pattern | Evades | Detection Pivot |
|---|---|---|
| PPID Spoofing | Parent-chain rules | Handle acquisition for PROCESS_CREATE_PROCESS |
| Process Hollowing | Process-name rules | VAD VadNone at image base, NtUnmapViewOfSection |
| Doppelganging | On-disk hash verification | USN transaction events, section anomaly |
| Token Impersonation | User-ownership rules | Event 4648, parent/child token SID mismatch |
| Argument Obfuscation | String-match command-line rules | ETW expanded cmd line, Script Block Logging |
| Module Stomping | VAD-based scanners | In-memory vs. on-disk section hash, CFG |
