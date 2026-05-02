---
technique_id: T1055.013
technique_name: Process Doppelganging
tactic: [Defense Evasion, Privilege Escalation]
platform: Windows
severity: Critical
data_sources: [ETW-Process, ETW-Memory, ETW-File, USN]
mitre_url: https://attack.mitre.org/techniques/T1055/013/
---

# T1055.013 — Process Doppelganging

## Description (T1055.013)

T1055.013 Process Doppelganging exploits Windows Transactional NTFS (TxF) — a feature introduced in Windows Vista that allows file operations to be grouped into an atomic transaction, committed, or rolled back as a unit. The technique abuses TxF to write a malicious PE image to disk within a transaction, map it as an executable image section before the transaction is committed, then roll back the transaction. The result is a section object whose backing content is the malicious PE, but no persistent on-disk file ever exists — because the transaction was rolled back.

This is particularly significant for `ai-procwatch-mcp` because the project monitors the NTFS USN (Update Sequence Number) Journal. The USN Journal records file system change events, but TxF transactional writes that are rolled back do **not** produce a permanent USN Journal entry for the write. This creates a deliberate gap in the USN Journal stream that can serve as an indicator of doppelganging activity.

---

## Windows Implementation Details (T1055.013)

### Transactional NTFS (TxF) Internals

TxF is implemented as an integration between the NT Kernel Transaction Manager (KTM), the Transaction Resource Manager in NTFS, and the Common Log File System (CLFS). A transaction is created via `NtCreateTransaction`, which returns a transaction handle backed by a `TmTx` kernel object. File operations are associated with a transaction by using the `CreateFileTransacted` Win32 API (or `NtCreateFile` with a transaction handle passed via `CreateOptions` using the `FILE_OPEN_FOR_BACKUP_INTENT` trick, or more correctly via the `ObjectAttributes` transaction field in extended API versions).

When a transacted write completes, NTFS records the change in the CLFS log but does not immediately update the primary NTFS metadata structures visible to non-transacted readers. Other processes that open the same file without a transaction handle see the pre-transaction content (isolation level `READ_COMMITTED` for non-transacted readers). The file's $USN_JRNL ($J) attribute records a change reason, but when the transaction is rolled back via `NtRollbackTransaction`, NTFS undoes all changes and the USN record associated with the transacted write may not appear in the journal stream as a settled change.

### Doppelganging Execution Chain (T1055.013)

```
1. NtCreateTransaction()
        ↓ create KTM transaction handle
2. CreateFileTransacted(target_path, GENERIC_WRITE, ..., transaction_handle)
        ↓ open (or create) a file within the transaction
3. NtWriteFile(transacted_file_handle, malicious_PE_content)
        ↓ write malicious PE to transacted file — not visible to non-transacted readers
4. NtCreateSection(transacted_file_handle, SEC_IMAGE)
        ↓ create an image section backed by the transacted (not-yet-committed) file
        ↓ the section object now holds a reference to the PE content as loaded
5. NtRollbackTransaction(transaction_handle)
        ↓ NTFS reverts the file — malicious PE never persists on disk
        ↓ USN Journal does NOT record a persistent write event for this content
6. NtCreateProcess(section_handle)  [or NtCreateUserProcess with the section]
        ↓ creates a process from the section — process runs the malicious PE
        ↓ EPROCESS.ImageFileName reflects the target_path (the decoy file name)
```

The key deception is in step 4: the `NtCreateSection` with `SEC_IMAGE` causes the Memory Manager to parse the PE headers and set up the section's internal representation as a mapped image. Once the section exists as a kernel object with its own reference count, rolling back the transaction in step 5 removes the on-disk manifestation but does not destroy the section — the Memory Manager holds a reference, keeping the content alive in memory.

### USN Journal Gap — Primary Indicator for ai-procwatch-mcp

The NTFS USN Journal ($UsnJrnl:$J) records a `USN_RECORD_V2` entry for every file change: create, write, rename, delete. Under normal execution, loading a PE from disk generates at minimum a `FILE_USAGE_CREATED` or `FILE_USAGE_OPENED` reason code in the USN stream.

For doppelganging:
- The transacted write (step 3) generates an internal CLFS log entry but does NOT produce a settled `USN_RECORD_V2` entry in `$J` if the transaction is rolled back before the USN is flushed.
- The `NtCreateSection(SEC_IMAGE)` in step 4 involves opening the section — there may be a brief `FILE_USAGE_OPENED` entry.
- The rollback in step 5 causes NTFS to write a `FILE_USAGE_DELETED` entry for any newly-created transacted file, but for an overwrite of an existing file, the journal may show only the file open and close without a write event.

**Detection heuristic for USN gap**: If `ai-procwatch-mcp` observes a process creation event (via ETW Kernel-Process) for a PE image path, but the USN Journal shows no recent write or create activity for that path, and the path's last-modified time predates the genome capture window by more than a threshold (e.g., the file was not recently written), yet the process behavior anomaly score is high — this is a doppelganging indicator.

More directly: if the USN Journal shows `FILE_USAGE_OPENED` for a file but no preceding `FILE_USAGE_CREATED` or `FILE_USAGE_WRITTEN` within the transaction window, and a new process is then created from that file path, flag as potential T1055.013.

---

## Observable Artifacts (T1055.013)

- ETW Kernel-Process will emit a **process create event** for the new process, with the image path pointing to the decoy file (e.g., `\Device\HarddiskVolume3\Windows\System32\svchost.exe` or an attacker-chosen path). The process will appear to be launched from a legitimate-looking path.
- The process's **EPROCESS.Token** will reflect the integrity level of the creating process, not necessarily SYSTEM — doppelganging does not automatically grant privilege escalation unless the creating process already has elevated rights.
- The **VAD tree** of the new process will show `VadType = VadImageMap` for the primary image region, with a backing section object — but when the section's file pointer is dereferenced, the underlying file content may no longer match the running process's code (because the transaction was rolled back). This file-content-vs-memory hash mismatch is an indicator.
- No `LoadImage` ETW event from a PsSetLoadImageNotifyRoutine perspective if the process was created directly from a section rather than via the standard `CreateProcessInternalW` path. Some variants may still trigger this callback depending on the precise API used.
- **USN Journal**: Absence of expected write event for the image file path within the relevant time window.

---

## ETW / eBPF Telemetry Signals (T1055.013)

### Microsoft-Windows-Kernel-Process

- Process Create event for the doppelganged process. The `ImageFileName` field will contain the decoy path. Cross-reference this path against the USN Journal — if no recent write activity for the path, escalate confidence.
- Kernel-Process thread create event for the initial thread of the new process. `Win32StartAddress` should be the PE entry point — verify it falls within an image-backed VAD (it will, because the image section was legitimately mapped even if transactionally).

### Microsoft-Windows-Kernel-File

- File operations on the target file path around the process creation time. The sequence `CREATE → WRITE → CLEANUP → CLOSE → (no subsequent file events) → process_create_from_same_path` is the doppelganging pattern.
- The absence of a final `FLUSH_BUFFERS` or `SET_INFORMATION (FileEndOfFileInformation)` event that would accompany a normal file write is a secondary indicator.

### NTFS USN Journal (USN stream via ai-procwatch-mcp)

- Cross-reference process creation image path against USN Journal entries for the prior 60-second window.
- If the image file has `FILE_USAGE_OPENED` but no `FILE_USAGE_CREATED` or file-write reason flags, and the file's actual last-modified timestamp in NTFS metadata does not match recently observed activity: **high confidence T1055.013**.
- USN gap detection: a process image file that shows up in ETW process creation events but has **zero** recent USN records is the strongest single indicator of process doppelganging.

---

## Detection Logic (T1055.013)

### Primary Rule

```
IF:
  etw_event.type = ProcessCreate
  AND etw_event.image_path exists on filesystem
  AND usn_journal.recent_writes(image_path, window=60s) = EMPTY
  AND file.hash(image_path) ≠ process.loaded_image_hash
THEN:
  technique = T1055.013, confidence = 0.90
```

### Supporting Rules

```
IF:
  kernel_file_event.operation = CREATE on path P
  AND within 5s: ntcreatesection(file_handle_to_P, SEC_IMAGE)
  AND within 5s: ntrollbacktransaction()
  AND within 30s: process_create from path P
THEN:
  technique = T1055.013, confidence = 0.95
```

### Confidence Degradation

If the file has legitimate recent USN activity (e.g., a software installer wrote to it recently), confidence drops to Medium (0.50) because the file may have been legitimately modified. Require additional corroboration (behavioral anomalies in the new process's genome).

---

## Related Techniques (T1055.013)

- T1055.012 (Process Hollowing) — Similar goal (disguise malicious process as legitimate), but hollowing operates post-creation on an existing process; doppelganging creates a new process from a transactionally-written section
- T1070.001 (Clear Event Logs) — Often paired to remove process creation audit records after the fact
- T1106 (Native API) — Doppelganging requires native API calls (`NtCreateTransaction`, `NtCreateSection`, `NtRollbackTransaction`) not available in the standard Win32 surface
