---
content_type: evasion
category: driver_evasion
platform: Windows
techniques: [T1068, T1014, T1195]
severity: Critical
data_sources: [ETW-CodeIntegrity, ETW-AuditAPI, ETW-Process, ETWTI]
---

# Driver Evasion Patterns

Driver-level evasion uses kernel-mode code (loaded as a Windows driver) to achieve capabilities that are impossible from user mode: bypassing PPL process protection, disabling EDR kernel callbacks, manipulating the VAD tree and EPROCESS structures directly, and bypassing HVCI protections through vulnerable signed drivers. These techniques are the most impactful and the hardest to remediate because kernel-mode code runs at the same privilege level as the OS itself.

---

## DE-001: BYOVD — Bring Your Own Vulnerable Driver

**Technique:** T1068, T1195 (supply chain — the vulnerable driver itself)

**Description:** BYOVD exploits a legitimately signed (Microsoft-approved) kernel driver that contains a known vulnerability — typically an arbitrary kernel read/write primitive exposed through an IOCTL interface. The attacker drops the vulnerable driver, loads it via `NtLoadDriver` (which succeeds because the driver is legitimately signed), then communicates with it via `DeviceIoControl` to exploit its vulnerability and execute arbitrary kernel code.

Common vulnerable drivers in the wild: `RTCore64.sys` (MSI Afterburner), `gdrv.sys` (GIGABYTE), `AsrDrv104.sys` (ASRock), `cpuz_x64.sys` (CPU-Z), `iqvw64e.sys` (Intel NIC diagnostics). These drivers expose direct physical memory read/write IOCTLs or MSR read/write capabilities.

**Why it works:** Windows Driver Signature Enforcement (DSE) requires all kernel drivers to be signed by a certificate trusted by the Microsoft Kernel-Mode Code Signing root. Vulnerable drivers meet this requirement — they are fully signed. HVCI adds the additional requirement that the driver be on the Microsoft Vulnerable Driver Blocklist (MSFT blocklist updated via Windows Update). BYOVD against an unblocklisted vulnerable driver succeeds even on HVCI-enabled systems.

**Kill chain:**

1. Drop the vulnerable `.sys` file to disk (typically `C:\Windows\System32\drivers\` or `C:\Windows\Temp\`).
2. Register it as a service (`NtLoadDriver` or `sc.exe create` + `sc.exe start`).
3. Open the driver's device (`CreateFile(\\.\<DeviceName>`)).
4. Send IOCTL requests to exploit the vulnerability (e.g., write to an arbitrary physical address to disable DSE or clear EPROCESS protection bits).
5. Load a second, unsigned malicious driver now that DSE is disabled, or execute arbitrary kernel code via the exploit.
6. Optionally: stop and delete the vulnerable driver to reduce forensic footprint.

**Detection:**

- **Microsoft-Windows-CodeIntegrity**: Event ID 3065 (CodeIntegrity blocked an unsigned kernel module) and Event ID 3066 (CodeIntegrity policy blocked a driver). Event ID 8028 fires when a driver is allowed to load by the signing policy but is on the blocklist (with enforcement mode). These events are the primary indicator of driver load activity.
- **NtLoadDriver audit**: `Microsoft-Windows-Kernel-Audit-API-Calls` provider emits an event when `NtLoadDriver` is called. The caller PID, the driver service key path, and the result code are captured.
- **Service registration**: `RegSetValue` for a new `HKLM\SYSTEM\CurrentControlSet\Services\<name>\ImagePath` pointing to a `.sys` file outside `%SystemRoot%\system32\drivers\` from a non-system process.
- **Known vulnerable driver hashes**: Matching the SHA-256 hash of the dropped `.sys` file against the Microsoft Vulnerable Driver Blocklist is a high-confidence static detection.

```
SEQUENCE within 120 seconds:
  Step 1: FileCreate(target.extension = ".sys", target.path NOT MATCHES system32\drivers\)
  Step 2: RegSetValue(KeyName MATCHES *Services*ImagePath*, DataValue = Step1.path)
  Step 3: NtLoadDriver event for that service key
→ DE-001 BYOVD High (0.88)
```

---

## DE-002: DSE Bypass (Disabling Driver Signature Enforcement)

**Technique:** T1068, T1014

**Description:** Windows enforces driver signature requirements via the `g_CiEnabled` kernel variable (or its modern equivalent in `ci.dll` — the Code Integrity module). Setting this variable to 0 from kernel code disables all driver signature checking, allowing arbitrary unsigned drivers to load. BYOVD drivers with physical memory write capability can locate and zero this variable by: (1) finding the kernel base address via `NtQuerySystemInformation(SystemModuleInformation)`, (2) scanning kernel memory for the known byte pattern around `g_CiEnabled`, (3) writing 0 to the identified address.

On HVCI-enabled systems, kernel code pages are protected by the hypervisor's second-level page tables. Writing to `g_CiEnabled` (which resides in a read-only kernel page) triggers a #GP fault; the patch cannot succeed. HVCI is the primary defense against DSE bypass.

**Detection:**

- **Physical memory write IOCTLs**: IOCTLs sent to known vulnerable driver device names for physical memory write operations (identifiable by IOCTL code patterns associated with known vulnerable drivers).
- **Subsequent unsigned driver load**: A `NtLoadDriver` call for a driver that triggers CodeIntegrity Event 3065 (blocked unsigned) immediately after a vulnerable driver IOCTL sequence indicates a DSE bypass attempt followed by unsigned driver load.
- **ETWTI behavior anomaly**: After a successful DSE bypass, the attacker may load additional kernel-mode tools. A burst of new driver loads from unexpected paths without corresponding CodeIntegrity signed-load events is a strong indicator.

---

## DE-003: Minifilter Driver Bypass

**Technique:** T1014, T1562

**Description:** Windows minifilter drivers (registered via `FltRegisterFilter`) intercept file system I/O at a configurable altitude. EDR minifilters sit at high altitude (typically 320000–329999 for antivirus, 260000–269999 for activity monitoring) and observe all file reads, writes, creates, renames, and deletes. A malicious kernel driver can:

- **Unregister the EDR's minifilter**: Call the Filter Manager's `FltUnregisterFilter` routine via its exported address. This silences the filter for all subsequent I/O. Requires knowing the EDR's filter handle, which can be obtained by enumerating registered filters via undocumented kernel structures.
- **Bypass via volume shadow / raw disk access**: Accessing file content via `\\.\PhysicalDrive0` or `\\.\Volume{guid}` bypasses the Filter Manager entirely — I/O at the volume level is not intercepted by minifilters operating on the file system level. Minifilters at the storage stack level can intercept this, but most EDR minifilters operate at the file system level.
- **Altitude manipulation**: Registering a second filter at an altitude below the EDR's filter and implementing callbacks that return `FLT_PREOP_COMPLETE` (short-circuit) for targeted I/O operations prevents those operations from reaching the EDR's filter.

**Detection:**

- **Filter unregistration events**: `Microsoft-Windows-FilterManager` provider (if available) can expose filter registration and unregistration events.
- **EDR self-monitoring**: An EDR minifilter that tracks its own callback invocations can detect when its callbacks stop firing for operations that should be intercepted (e.g., the EDR monitors a file it writes periodically; if it stops receiving Create events for its own files, its filter may have been removed).
- **CodeIntegrity events** for the driver performing the bypass.

---

## DE-004: IRP Hooking

**Technique:** T1014

**Description:** The I/O Request Packet (IRP) dispatch table of a driver can be modified to redirect specific IRP handler functions to attacker-controlled code. For example, patching the IRP_MJ_CREATE handler of the file system driver intercepts all file open operations — allowing the rootkit to return falsified results for specific file paths without going through the Filter Manager. This is an older technique that modern HVCI-enabled systems resist (the driver's code pages are read-only).

**Detection on non-HVCI systems:**

- Integrity checks of driver IRP dispatch tables at regular intervals. Each driver's `MajorFunction` table is at a fixed offset in the `DRIVER_OBJECT` structure; comparing each entry against the known-good address range for that driver's `.text` section identifies hooked entries.
- ETWTI WRITEVM events targeting kernel address ranges (driver dispatch tables reside in kernel VA space; cross-process writes there are immediately suspicious).

---

## DE-005: LSASS PPL Bypass via Driver

**Technique:** T1068, T1003.001

**Description:** LSASS runs as `PS_PROTECTED_ANTIMALWARE_LIGHT` on modern Windows. The protection level is stored in `EPROCESS.Protection` (an `EX_FAST_REF` structure containing the protection type and signer level). A kernel driver can directly clear this field, downgrading LSASS from a protected process to an unprotected one, after which any administrator-level process can open it with full access rights including `PROCESS_VM_READ`.

**Detection:**

- **ETWTI**: No direct ETWTI event exists for EPROCESS.Protection field modification (it is a pure kernel memory write). The indicator is the downgrade's consequence: an ETWTI READVM_REMOTE event targeting the now-unprotected LSASS from a non-system process that previously could not have opened it.
- **Temporal correlation**: Driver load event (CodeIntegrity) → short time gap → LSASS memory read from an unexpected process.

```
SEQUENCE within 60 seconds:
  Step 1: CodeIntegrity driver load event for a driver NOT in known_good_driver_set
  Step 2: ETWTI READVM(
    TargetPid = lsass_pid
    CallerProcess NOT IN {MsMpEng.exe, csrss.exe, lsm.exe}
  )
→ DE-005 Critical (0.95) — BYOVD-facilitated LSASS dump
```

---

## Summary: Driver Evasion Detection Chain

| Attack | Kernel Effect | Primary ETW Signal | Confidence |
|---|---|---|---|
| BYOVD load | Arbitrary kernel code | NtLoadDriver + CodeIntegrity + service registry | High |
| DSE bypass | Unsigned driver loads succeed | CodeIntegrity 3065 for subsequent load | High |
| Minifilter unregistration | EDR file events go silent | Self-monitoring gap, FilterManager events | Medium |
| IRP hooking | Driver dispatch redirected | Integrity check mismatch (non-HVCI) | Medium |
| LSASS PPL bypass | LSASS unprotected | Driver load + LSASS READVM sequence | High |
