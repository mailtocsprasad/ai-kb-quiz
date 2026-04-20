# Windows Filesystem Minifilter Driver — Design & Technical Reference

---

## Table of Contents

1. [Background — Legacy Filters vs. the Minifilter Model](#1-background)
2. [Architecture — Filter Manager and the I/O Stack](#2-architecture)
3. [Core Data Structures](#3-core-data-structures)
4. [Registration and Initialization (DriverEntry)](#4-registration-and-initialization)
5. [Altitude System](#5-altitude-system)
6. [Instance Lifecycle — Volume Attachment](#6-instance-lifecycle)
7. [Callback Mechanics — Pre and Post Operations](#7-callback-mechanics)
8. [Critical Callback Implementations](#8-critical-callback-implementations)
9. [Context Management](#9-context-management)
10. [File Name Resolution](#10-file-name-resolution)
11. [User-Mode Communication Port](#11-user-mode-communication-port)
12. [Filter-Initiated I/O](#12-filter-initiated-io)
13. [Unload, Detach, and Teardown Rules](#13-unload-detach-and-teardown-rules)
14. [Buffer Access — MDL, Neither I/O, and Buffer Swapping](#14-buffer-access)
15. [IRQL Constraints and Safe Patterns](#15-irql-constraints-and-safe-patterns)
16. [Common Pitfalls](#16-common-pitfalls)
17. [Complete Driver Skeleton](#17-complete-driver-skeleton)
18. [Debugging with WinDbg and fltmc](#18-debugging-with-windbg-and-fltmc)
19. [Build Environment Setup](#19-build-environment-setup)
20. [Support Routines Reference](#20-support-routines-reference)

---

## 1. Background

### 1.1 Why Minifilters Exist

Before minifilters, filesystem filtering required **legacy filter drivers** that inserted DEVICE_OBJECTs directly between the I/O Manager and the base filesystem. This approach had severe drawbacks:

| Problem | Detail |
|---|---|
| No dynamic unload | A legacy filter could not be unloaded while the system was running without a reboot |
| Passthrough boilerplate | Every IRP_MJ_* code had to be explicitly forwarded, even if the filter did nothing with it |
| Stack-position conflicts | Multiple filters competed for position using registry `LoadOrderGroup` — fragile and non-deterministic |
| No standardized communication | Each filter invented its own user-mode IOCTL interface |
| Reparse point complexity | Filters had to manage reparse point processing manually |

The solution is the **Filter Manager** (`FltMgr.sys`), introduced in Windows XP SP2 and mandatory from Windows Vista onwards. Filter Manager is itself a legacy filter driver, but it presents a clean, IRP-agnostic callback model to **minifilter drivers** that register with it.

### 1.2 Comparison Table

| Property | Legacy Filter Driver | Minifilter Driver |
|---|---|---|
| Dynamic load/unload | No — reboot required | Yes — `FltUnregisterFilter` |
| IRP passthrough boilerplate | Extensive — all IRP types | None — FltMgr handles passthrough |
| Ordering between filters | Registry `LoadOrderGroup` (fragile) | Altitude — deterministic and conflict-free |
| Fast I/O abstraction | Must implement `FAST_IO_DISPATCH` | FltMgr unifies Fast I/O and IRP into callbacks |
| Kernel↔User communication | Custom device object + IOCTL | Built-in communication port API |
| Context management | Manual, complex | Built-in per-volume, per-instance, per-file, per-stream |
| File name lookup | Complex, error-prone | `FltGetFileNameInformation` with caching |
| I/O generation | `ZwCreateFile` (re-entrant risk) | `FltCreateFile` (bypasses callers above) |

---

## 2. Architecture

### 2.1 Filter Manager Frame and the Filter Stack

```
  User-Mode Application
       |  CreateFile / ReadFile / WriteFile / NtQueryInformationFile
       v
  ┌─────────────────────────────────────────┐
  │            I/O Manager                  │  Creates IRP → IoCallDriver
  └─────────────────────────────────────────┘
       |
       v
  ┌─────────────────────────────────────────┐
  │   FltMgr.sys  (Legacy Filter — Frame 0) │  Converts IRP → FLT_CALLBACK_DATA
  └─────────────────────────────────────────┘
       |  Dispatches pre-callbacks in DESCENDING altitude order
       v
  ┌──────────────────────────────────────────────────────────────┐
  │  Minifilter A  (Altitude 360010 — Activity Monitor / EDR)    │
  │    PreCreate ──────────► [log / allow / block / modify]      │
  └──────────────────────────────────────────────────────────────┘
       |
       v
  ┌──────────────────────────────────────────────────────────────┐
  │  Minifilter B  (Altitude 328010 — AV / Malware Scanner)      │
  │    PreCreate ──────────► [scan / allow / block]              │
  └──────────────────────────────────────────────────────────────┘
       |
       v
  ┌──────────────────────────────────────────────────────────────┐
  │  Minifilter C  (Altitude 140010 — Transparent Encryption)    │
  │    PreCreate ──────────► [decryption setup]                  │
  └──────────────────────────────────────────────────────────────┘
       |
       v
  ┌─────────────────────────────────────────┐
  │      Base File System Driver (NTFS)     │  Processes IRP
  └─────────────────────────────────────────┘
       |  Post-callbacks in ASCENDING altitude order
       v
  Minifilter C (PostCreate) → Minifilter B (PostCreate) → Minifilter A (PostCreate)
       |
       v
  I/O Manager completes IRP → returns to user mode
```

**Key rule:** Pre-callbacks fire top-down (highest altitude first). Post-callbacks fire bottom-up (lowest altitude first). This ensures that higher-altitude security filters see the *result* of lower-altitude encryption before acting on it in post.

### 2.2 FltMgr Frames

Most systems have a single FltMgr frame (Frame 0). When a second **legacy** filter driver exists in the stack between two groups of minifilters, FltMgr loads a second frame. Minifilters with altitude above the legacy filter attach to Frame 1; those below attach to Frame 0. The `fltmc instances` command shows frame numbers in output.

### 2.3 Fast I/O vs. IRP Operations

The Windows Cache Manager uses **Fast I/O** for synchronous cached reads and writes, bypassing the normal IRP path for performance. FltMgr intercepts Fast I/O and presents it as the same `FLT_CALLBACK_DATA` structure to minifilters. Minifilters can distinguish the operation type:

```c
if (FLT_IS_FASTIO_OPERATION(Data))      { /* fast I/O — synchronous cache path */ }
if (FLT_IS_IRP_OPERATION(Data))         { /* IRP path — async or non-cached     */ }
if (FLT_IS_FS_FILTER_OPERATION(Data))   { /* legacy FsFilter notification        */ }
```

To skip fast I/O or paging I/O for a specific major function, use registration flags:

```c
{ IRP_MJ_WRITE,
  FLTFL_OPERATION_REGISTRATION_SKIP_CACHED_IO |
  FLTFL_OPERATION_REGISTRATION_SKIP_PAGING_IO,
  PreWriteCallback, PostWriteCallback }
```

---

## 3. Core Data Structures

### 3.1 FLT_REGISTRATION — Master Registration

Every minifilter populates an `FLT_REGISTRATION` and passes it to `FltRegisterFilter`. This single structure declares everything the filter needs from FltMgr.

```c
typedef struct _FLT_REGISTRATION {
    USHORT                                        Size;
    USHORT                                        Version;
    FLT_REGISTRATION_FLAGS                        Flags;
    const FLT_CONTEXT_REGISTRATION               *ContextRegistration;
    const FLT_OPERATION_REGISTRATION             *OperationRegistration;
    PFLT_FILTER_UNLOAD_CALLBACK                   FilterUnloadCallback;
    PFLT_INSTANCE_SETUP_CALLBACK                  InstanceSetupCallback;
    PFLT_INSTANCE_QUERY_TEARDOWN_CALLBACK         InstanceQueryTeardownCallback;
    PFLT_INSTANCE_TEARDOWN_CALLBACK               InstanceTeardownStartCallback;
    PFLT_INSTANCE_TEARDOWN_CALLBACK               InstanceTeardownCompleteCallback;
    PFLT_GENERATE_FILE_NAME                       GenerateFileNameCallback;
    PFLT_NORMALIZE_NAME_COMPONENT                 NormalizeNameComponentCallback;
    PFLT_NORMALIZE_CONTEXT_CLEANUP                NormalizeContextCleanupCallback;
    PFLT_TRANSACTION_NOTIFICATION_CALLBACK        TransactionNotificationCallback;
    PFLT_NORMALIZE_NAME_COMPONENT_EX              NormalizeNameComponentExCallback;
#if FLT_MGR_WIN8
    PFLT_SECTION_CONFLICT_NOTIFICATION_CALLBACK   SectionNotificationCallback;
#endif
} FLT_REGISTRATION, *PFLT_REGISTRATION;
```

| Field | Required? | Notes |
|---|---|---|
| `Size` | Yes | `sizeof(FLT_REGISTRATION)` — may vary by target Windows version |
| `Version` | Yes | Always `FLT_REGISTRATION_VERSION` — never use a raw number |
| `Flags` | No | `0`, or `FLTFL_REGISTRATION_DO_NOT_SUPPORT_SERVICE_STOP`, `FLTFL_REGISTRATION_SUPPORT_NPFS_MSFS`, `FLTFL_REGISTRATION_SUPPORT_DAX_VOLUME` (Win10 1607+) |
| `ContextRegistration` | Conditional | Array of `FLT_CONTEXT_REGISTRATION`, terminated by `FLT_CONTEXT_END`. `NULL` if no contexts |
| `OperationRegistration` | Yes | Array of `FLT_OPERATION_REGISTRATION`, terminated by `{ IRP_MJ_OPERATION_END }` |
| `FilterUnloadCallback` | Recommended | Must call `FltUnregisterFilter` inside. If `NULL`, driver cannot be unloaded dynamically |
| `InstanceSetupCallback` | Recommended | Return `STATUS_SUCCESS` to attach, `STATUS_FLT_DO_NOT_ATTACH` to skip |
| `InstanceQueryTeardownCallback` | No | Return `STATUS_FLT_DO_NOT_DETACH` to refuse explicit detach. If `NULL`, detach is always allowed |
| `InstanceTeardownStart/Complete` | No | Paired teardown callbacks. Start: complete pending I/O. Complete: final cleanup |
| `GenerateFileNameCallback` | Rare | Used by name-virtualizing filters (e.g. encryption). Most filters set `NULL` |
| `TransactionNotificationCallback` | No | Receive KTM (TxF) transaction notifications |

> **WARNING:** Do NOT set `DriverObject->DriverUnload` after `FltRegisterFilter`. FltMgr takes ownership of that callback. Setting it before is silently overwritten; setting it after corrupts the unload path.

### 3.2 FLT_OPERATION_REGISTRATION — Per-Operation Callback Declaration

```c
typedef struct _FLT_OPERATION_REGISTRATION {
    UCHAR                             MajorFunction;
    FLT_OPERATION_REGISTRATION_FLAGS  Flags;
    PFLT_PRE_OPERATION_CALLBACK       PreOperation;
    PFLT_POST_OPERATION_CALLBACK      PostOperation;
    PVOID                             Reserved1;  // must be NULL
} FLT_OPERATION_REGISTRATION, *PFLT_OPERATION_REGISTRATION;

// Example array (MUST end with IRP_MJ_OPERATION_END sentinel):
const FLT_OPERATION_REGISTRATION g_Callbacks[] = {
    { IRP_MJ_CREATE,
      0,
      PreCreate, PostCreate },
    { IRP_MJ_READ,
      FLTFL_OPERATION_REGISTRATION_SKIP_PAGING_IO,
      PreRead, PostRead },
    { IRP_MJ_WRITE,
      FLTFL_OPERATION_REGISTRATION_SKIP_PAGING_IO |
      FLTFL_OPERATION_REGISTRATION_SKIP_CACHED_IO,
      PreWrite, NULL },
    { IRP_MJ_SET_INFORMATION,
      0,
      PreSetInfo, NULL },
    { IRP_MJ_CLEANUP,
      0,
      NULL, PostCleanup },
    { IRP_MJ_OPERATION_END }   // REQUIRED terminator — missing this causes a bugcheck
};
```

| Registration Flag | Effect |
|---|---|
| `FLTFL_OPERATION_REGISTRATION_SKIP_CACHED_IO` | Skip Fast I/O (cached) operations. Useful for write monitoring where only non-cached writes matter |
| `FLTFL_OPERATION_REGISTRATION_SKIP_PAGING_IO` | Skip paging I/O. **Critical for avoiding deadlocks** — paging I/O cannot safely call `FltGetFileNameInformation` |
| `FLTFL_OPERATION_REGISTRATION_SKIP_NON_DASD_IO` | Skip non-Direct Access Storage Device I/O. Rarely used |

### 3.3 FLT_CALLBACK_DATA — The Central I/O Operation Descriptor

`FLT_CALLBACK_DATA` is passed to every pre and post callback. It is analogous to an IRP in the legacy model — it carries everything about the current I/O operation.

```c
typedef struct _FLT_CALLBACK_DATA {
    FLT_CALLBACK_DATA_FLAGS          Flags;
    PETHREAD CONST                   Thread;         // requesting thread
    PFLT_IO_PARAMETER_BLOCK CONST    Iopb;           // operation parameters (changeable)
    IO_STATUS_BLOCK                  IoStatus;       // result
    struct _FLT_TAG_DATA_BUFFER     *TagData;        // valid only for CREATE post with reparse
    union {
        struct {
            LIST_ENTRY   QueueLinks;                 // used when pending the operation
            PVOID        QueueContext[2];
        };
        PVOID FilterContext[4];                      // four PVOID slots for per-callback driver use
    };
    KPROCESSOR_MODE                  RequestorMode;  // UserMode or KernelMode
} FLT_CALLBACK_DATA, *PFLT_CALLBACK_DATA;
```

| Member | Description |
|---|---|
| `Flags` | Bitmask: `FLTFL_CALLBACK_DATA_IRP_OPERATION`, `_FAST_IO_OPERATION`, `_POST_OPERATION`, `_DIRTY` (modified params), `_GENERATED_IO` (from another minifilter), `_DRAINING_IO` (post during teardown) |
| `Thread` | `PETHREAD` of requestor. Use `FltGetRequestorProcess`/`FltGetRequestorProcessId` — do NOT dereference directly |
| `Iopb` | Pointer to `FLT_IO_PARAMETER_BLOCK` — all changeable parameters. Call `FltSetCallbackDataDirty` after modifying |
| `IoStatus` | In pre-callback: set `Status` and return `FLT_PREOP_COMPLETE` to short-circuit the I/O. In post-callback: the final result from the filesystem |
| `FilterContext[4]` | Four opaque PVOIDs for driver use within a single callback invocation. NOT persisted — use file/stream contexts for state across callbacks |
| `RequestorMode` | `UserMode` or `KernelMode`. Most security filters skip kernel-mode callers to avoid blocking their own re-entrant I/O |

### 3.4 FLT_IO_PARAMETER_BLOCK — Operation Parameters

```c
typedef struct _FLT_IO_PARAMETER_BLOCK {
    ULONG           IrpFlags;         // IRP_* flags
    UCHAR           MajorFunction;    // IRP_MJ_* — may NOT be changed by minifilters
    UCHAR           MinorFunction;    // IRP_MN_* (relevant for PnP, DirectoryControl)
    UCHAR           OperationFlags;   // SL_* flags from IO_STACK_LOCATION.Flags
    UCHAR           Reserved;
    PFILE_OBJECT    TargetFileObject; // the file being operated on (changeable)
    PFLT_INSTANCE   TargetInstance;   // this filter's instance (changeable — only across volumes)
    FLT_PARAMETERS  Parameters;       // union of major-function-specific data
} FLT_IO_PARAMETER_BLOCK, *PFLT_IO_PARAMETER_BLOCK;
```

`FLT_PARAMETERS` is a union mirroring `IO_STACK_LOCATION.Parameters`. Key fields per operation:

| Operation | Key `Parameters.Xxx` Fields |
|---|---|
| `IRP_MJ_CREATE` | `Create.SecurityContext->DesiredAccess`, `Create.Options` (low 24 bits = CreateOptions like `FILE_DELETE_ON_CLOSE`; high 8 bits = CreateDisposition), `Create.FileAttributes`, `Create.ShareAccess` |
| `IRP_MJ_READ` | `Read.Length`, `Read.ByteOffset`, `Read.ReadBuffer` (Neither I/O), `Read.MdlAddress` (Direct I/O) |
| `IRP_MJ_WRITE` | `Write.Length`, `Write.ByteOffset`, `Write.WriteBuffer`, `Write.MdlAddress` |
| `IRP_MJ_SET_INFORMATION` | `SetFileInformation.FileInformationClass` (`FileDispositionInformation`, `FileRenameInformation`, `FileEndOfFileInformation`, …), `SetFileInformation.InfoBuffer`, `SetFileInformation.ParentOfTarget` |
| `IRP_MJ_QUERY_INFORMATION` | `QueryFileInformation.FileInformationClass`, `QueryFileInformation.InfoBuffer`, `QueryFileInformation.Length` |
| `IRP_MJ_DIRECTORY_CONTROL` | `DirectoryControl.QueryDirectory.FileInformationClass`, `DirectoryControl.QueryDirectory.DirectoryBuffer`, `DirectoryControl.QueryDirectory.Length` |

> **Rule:** Minifilters may change any field in `FLT_IO_PARAMETER_BLOCK` **except `MajorFunction`** in pre-callbacks. After changing any field, call `FltSetCallbackDataDirty(Data)`. **You may NOT change `TargetInstance` to another instance on the same volume** — this would bypass filters sitting between the two altitudes.

### 3.5 FLT_RELATED_OBJECTS — Opaque Object Handles

```c
typedef struct _FLT_RELATED_OBJECTS {
    USHORT CONST            Size;
    USHORT CONST            TransactionContext;
    PFLT_FILTER  CONST      Filter;      // opaque handle to the registered filter
    PFLT_VOLUME  CONST      Volume;      // opaque handle to the volume being filtered
    PFLT_INSTANCE CONST     Instance;    // opaque handle to this filter's volume instance
    PFILE_OBJECT CONST      FileObject;  // same as Iopb->TargetFileObject
    PKTRANSACTION CONST     Transaction; // KTM transaction (if TxF is active, else NULL)
} FLT_RELATED_OBJECTS, *PFLT_RELATED_OBJECTS;

// These handles are required by most FltXxx APIs:
FltGetFileContext(FltObjects->Instance, FltObjects->FileObject, ...);
FltAllocateContext(FltObjects->Filter, FLT_FILE_CONTEXT, ...);
FltGetVolumeProperties(FltObjects->Volume, ...);
FltIsDirectory(FltObjects->FileObject, FltObjects->Instance, ...);
```

---

## 4. Registration and Initialization

### 4.1 DriverEntry Sequence

The order of operations in `DriverEntry` is critical:

```
1. Write altitude/instance registry keys (or use INF during installation)
2. FltRegisterFilter      → registers callbacks, receives PFLT_FILTER handle
3. CreateCommPort         → optional, but must happen before FltStartFiltering
4. FltStartFiltering      → arms all callbacks; triggers InstanceSetupCallback
                            for all existing volumes
```

If any step fails, **unwind in reverse order** before returning the error.

### 4.2 FltRegisterFilter and FltStartFiltering

```c
NTSTATUS FltRegisterFilter(
    _In_     PDRIVER_OBJECT          Driver,
    _In_     const FLT_REGISTRATION *Registration,
    _Outptr_ PFLT_FILTER            *ReturnedFilter);

NTSTATUS FltStartFiltering(_In_ PFLT_FILTER Filter);
```

`FltRegisterFilter` validates the `FLT_REGISTRATION` structure and allocates an internal FltMgr filter object. It does **not** arm callbacks yet — the filter is not attached to any volumes.

`FltStartFiltering` arms all callbacks and calls `InstanceSetupCallback` for every volume currently mounted on the system. Call this **last** in `DriverEntry`.

### 4.3 Unload Callback

```c
NTSTATUS FilterUnload(FLT_FILTER_UNLOAD_FLAGS Flags) {
    // 1. Close communication port first (drains any pending messages)
    if (g_ServerPort) FltCloseCommunicationPort(g_ServerPort);
    // 2. Unregister — also detaches all instances
    FltUnregisterFilter(g_Filter);
    return STATUS_SUCCESS;
}
```

> **Rule:** Always close the server communication port handle **before** calling `FltUnregisterFilter`. Failure to do so can cause a system hang during unload.

---

## 5. Altitude System

### 5.1 What Altitude Is

An altitude is an infinite-precision decimal string (e.g., `"360010"`) that defines a minifilter's position in the filter stack. The higher the numeric value, the higher the filter sits. Altitudes enforce deterministic ordering regardless of when individual drivers load.

**Two purposes:**
1. Enforce required relative ordering (e.g., AV above encryption, so AV scans plaintext)
2. Provide a fixed test matrix — exactly one well-defined configuration to test

### 5.2 Altitude Ranges

| Range | Load Order Group | Typical Use |
|---|---|---|
| 420000–429999 | Filter | Highest — generic top-level |
| 400000–409999 | FSFilter Top | Umbrella/audit filters |
| 360000–389999 | FSFilter Activity Monitor | EDR telemetry, audit logging, DLP monitoring |
| 320000–329999 | FSFilter Anti-Virus | Real-time AV scanning |
| 280000–289999 | FSFilter Continuous Backup | Backup / journaling |
| 260000–269999 | FSFilter Content Screener | DLP content inspection |
| 140000–149999 | FSFilter Encryption | Transparent encryption (BitLocker-style) |
| 80000–89999 | FSFilter Security Enhancer | Security policy enforcement |
| 40000–49999 | FSFilter Bottom | Lowest position |

> For a commercially released minifilter, request an official altitude from Microsoft at `fsfcomm@microsoft.com`. Use altitudes in the 300000–389999 range only for development testing.

### 5.3 Registry Structure

The following registry structure is required. It can be set programmatically from `DriverEntry` or via an INF file at installation:

```
HKLM\System\CurrentControlSet\Services\<DriverName>\
    Instances\
        DefaultInstance = "<DriverName>DefaultInstance"   (REG_SZ)
        <DriverName>DefaultInstance\
            Altitude = "360010"    (REG_SZ — your assigned altitude)
            Flags    = 0           (REG_DWORD)
```

**Flags values:**
- `0` — automatic + manual attachments (most common)
- `1` — skip automatic attachment; require explicit `FilterAttach` call
- `2` — skip manual attachment; only auto-attach on volume mount

**INF file equivalent:**

```ini
[MyFilter.Instances]
DefaultInstance = MyFilter Instance

[MyFilter Instance]
Altitude = 360010
Flags    = 0x0
```

---

## 6. Instance Lifecycle — Volume Attachment

A minifilter does not filter I/O globally. It filters I/O on specific volumes through **instances** — one instance per (filter, volume, altitude) combination. A filter can have multiple instances on the same volume at different altitudes.

### 6.1 InstanceSetupCallback — Choosing Which Volumes to Attach

Called by FltMgr whenever a volume becomes available. Return `STATUS_SUCCESS` to attach; return `STATUS_FLT_DO_NOT_ATTACH` to refuse.

```c
NTSTATUS InstanceSetupCallback(
    _In_ PCFLT_RELATED_OBJECTS         FltObjects,
    _In_ FLT_INSTANCE_SETUP_FLAGS      Flags,
    _In_ DEVICE_TYPE                   VolumeDeviceType,
    _In_ FLT_FILESYSTEM_TYPE           VolumeFilesystemType)
{
    UNREFERENCED_PARAMETER(Flags);

    // Skip network file systems
    if (VolumeDeviceType == FILE_DEVICE_NETWORK_FILE_SYSTEM)
        return STATUS_FLT_DO_NOT_ATTACH;

    // Only attach to NTFS (for alternate stream support)
    if (VolumeFilesystemType != FLT_FSTYPE_NTFS)
        return STATUS_FLT_DO_NOT_ATTACH;

    // Query volume properties if needed
    FLT_VOLUME_PROPERTIES volProps;
    ULONG returnedLen;
    FltGetVolumeProperties(FltObjects->Volume,
                           &volProps, sizeof(volProps), &returnedLen);

    return STATUS_SUCCESS;  // attach to this volume
}
```

**Setup flags:**
- `FLTFL_INSTANCE_SETUP_AUTOMATIC_ATTACHMENT` — triggered by `FltStartFiltering` for existing volumes
- `FLTFL_INSTANCE_SETUP_MANUAL_ATTACHMENT` — explicit `FilterAttach` / `FltAttachVolume` call
- `FLTFL_INSTANCE_SETUP_NEWLY_MOUNTED_VOLUME` — brand-new volume mount

**FLT_FILESYSTEM_TYPE values:**

| Constant | Filesystem |
|---|---|
| `FLT_FSTYPE_NTFS` | NTFS — standard local disk |
| `FLT_FSTYPE_FAT` | FAT12/FAT16/FAT32 |
| `FLT_FSTYPE_EXFAT` | exFAT |
| `FLT_FSTYPE_REFS` | ReFS |
| `FLT_FSTYPE_NPFS` | Named Pipe FS (requires `FLTFL_REGISTRATION_SUPPORT_NPFS_MSFS`) |
| `FLT_FSTYPE_MSFS` | Mailslot FS |
| `FLT_FSTYPE_MUP` | Multiple UNC Provider |
| `FLT_FSTYPE_NFS` | Network File System |
| `FLT_FSTYPE_RAW` | Unformatted volume |

> **Note:** If no `InstanceSetupCallback` is registered, FltMgr treats it as if `STATUS_SUCCESS` was returned for every volume.

### 6.2 InstanceQueryTeardown — Refusing Detach

Called only for manual detach requests (`FilterDetach` / `FltDetachVolume`). If `NULL`, manual detach is not supported, but volume dismounts and minifilter unloads still proceed.

```c
NTSTATUS InstanceQueryTeardown(
    PCFLT_RELATED_OBJECTS FltObjects,
    FLT_INSTANCE_QUERY_TEARDOWN_FLAGS Flags)
{
    // Return STATUS_FLT_DO_NOT_DETACH to refuse a manual detach request.
    // Cannot refuse if system is shutting down or driver is being unloaded.
    return STATUS_SUCCESS;  // allow detach
}
```

### 6.3 InstanceTeardownStart and InstanceTeardownComplete

These two paired callbacks are always called when an instance is being destroyed, regardless of reason (manual detach, volume dismount, driver unload).

```c
// Teardown flags passed to both callbacks:
// FLTFL_INSTANCE_TEARDOWN_MANUAL              — FilterDetach or FltDetachVolume
// FLTFL_INSTANCE_TEARDOWN_FILTER_UNLOAD       — minifilter unloading (could have been refused)
// FLTFL_INSTANCE_TEARDOWN_MANDATORY_FILTER_UNLOAD — unload that cannot be refused
// FLTFL_INSTANCE_TEARDOWN_VOLUME_DISMOUNT     — volume being dismounted
// FLTFL_INSTANCE_TEARDOWN_INTERNAL_ERROR      — error during instance setup

VOID InstanceTeardownStart(
    PCFLT_RELATED_OBJECTS FltObjects,
    FLT_INSTANCE_TEARDOWN_FLAGS Flags)
{
    // MUST: resume/complete all pended pre and post operations
    // MUST: guarantee no new operations will be pended
    // MAY: close opened files, cancel filter-initiated I/O, stop queuing work items
}

VOID InstanceTeardownComplete(
    PCFLT_RELATED_OBJECTS FltObjects,
    FLT_INSTANCE_TEARDOWN_FLAGS Flags)
{
    // Called after ALL operation callbacks have drained for this instance.
    // MUST: close any files still open on this instance.
    // Final cleanup of instance context.
    PFLT_CONTEXT instCtx;
    if (NT_SUCCESS(FltGetInstanceContext(FltObjects->Instance,
                   (PFLT_CONTEXT*)&instCtx))) {
        FltDeleteContext(instCtx);
        FltReleaseContext(instCtx);
    }
}
```

> **Note:** Neither teardown callback has a return value — they cannot be failed. FltMgr guarantees they are called at `PASSIVE_LEVEL`.

---

## 7. Callback Mechanics — Pre and Post Operations

### 7.1 Pre-Operation Callback

All pre-operation callbacks share one prototype:

```c
FLT_PREOP_CALLBACK_STATUS PreOperation(
    _Inout_   PFLT_CALLBACK_DATA      Data,
    _In_      PCFLT_RELATED_OBJECTS   FltObjects,
    _Outptr_  PVOID                  *CompletionContext);  // passed to PostOperation
```

Return values and their effects:

| Return Value | Effect |
|---|---|
| `FLT_PREOP_SUCCESS_NO_CALLBACK` | Allow operation to continue. Post callback will NOT be called for this operation. Use this when you're done and don't need the result. |
| `FLT_PREOP_SUCCESS_WITH_CALLBACK` | Allow operation to continue. Post callback WILL be called. `CompletionContext` is passed through to post. |
| `FLT_PREOP_COMPLETE` | Complete the operation **here**. Set `Data->IoStatus.Status` before returning. Lower filters and the file system are NOT called. Post callback NOT called. |
| `FLT_PREOP_PENDING` | Pend the operation. FltMgr suspends it. Driver MUST later call `FltCompletePendedPreOperation` to resume. No `IoMarkIrpPending` needed — FltMgr handles that. |
| `FLT_PREOP_SYNCHRONIZE` | Like `SUCCESS_WITH_CALLBACK` but FltMgr guarantees post callback runs on the **same thread** at IRQL ≤ `APC_LEVEL`. Useful when post needs `PASSIVE_LEVEL` APIs. **Has performance cost.** Not valid for IRP_MJ_CREATE (creates are automatically synchronized). |
| `FLT_PREOP_DISALLOW_FASTIO` | Only valid for Fast I/O operations. Tells FltMgr to fail the fast I/O path, forcing an IRP-based retry. |

### 7.2 Post-Operation Callback

```c
FLT_POSTOP_CALLBACK_STATUS PostOperation(
    _Inout_ PFLT_CALLBACK_DATA      Data,
    _In_    PCFLT_RELATED_OBJECTS   FltObjects,
    _In_    PVOID                   CompletionContext,   // from pre callback
    _In_    FLT_POST_OPERATION_FLAGS Flags);
// Flags: FLTFL_POST_OPERATION_DRAINING — instance being torn down
```

Return values:

| Return Value | Effect |
|---|---|
| `FLT_POSTOP_FINISHED_PROCESSING` | Processing complete; return control to whoever initiated the I/O. |
| `FLT_POSTOP_MORE_PROCESSING_REQUIRED` | Minifilter is NOT done. Driver must later call `FltCompletePendedPostOperation` inside a work item. |

Post callbacks are called at IRQL ≤ `DISPATCH_LEVEL` in an arbitrary thread, **except** for `IRP_MJ_CREATE` post which is always `PASSIVE_LEVEL` on the original thread.

**At `DISPATCH_LEVEL`, you CANNOT:**
- Access paged memory or paged pool
- Call `KeWaitForSingleObject`, acquire `FAST_MUTEX`, `ERESOURCE`, events, or semaphores
- Call `FltGetFileNameInformation`, `FltGetStreamContext`, or `FltSetStreamContext`

**At `DISPATCH_LEVEL`, you CAN:**
- Call `FltReleaseContext`, `KeSetEvent`, `KeAcquireSpinLock`

### 7.3 Handling DISPATCH_LEVEL in Post-Callbacks

**Option 1: `FltDoCompletionProcessingWhenSafe`**

Runs `SafePostCallback` on a worker thread at `APC_LEVEL` if currently at `DISPATCH_LEVEL`. Limitations: NOT safe for `IRP_MJ_READ/WRITE/FLUSH` (deadlock risk). IRP operations only.

```c
FLT_POSTOP_CALLBACK_STATUS PostCallback(
    PFLT_CALLBACK_DATA Data, PCFLT_RELATED_OBJECTS Flt,
    PVOID Ctx, FLT_POST_OPERATION_FLAGS Flags)
{
    // Always check draining first
    if (Flags & FLTFL_POST_OPERATION_DRAINING)
        return FLT_POSTOP_FINISHED_PROCESSING;

    if (!FLT_IS_IRP_OPERATION(Data))
        return FLT_POSTOP_FINISHED_PROCESSING;

    FLT_POSTOP_CALLBACK_STATUS cbStatus;
    if (!NT_SUCCESS(FltDoCompletionProcessingWhenSafe(
            Data, Flt, Ctx, Flags, SafePostCallback, &cbStatus)))
        return FLT_POSTOP_FINISHED_PROCESSING;

    return cbStatus;
}
```

**Option 2: `FltQueueDeferredIoWorkItem`**

Return `FLT_POSTOP_MORE_PROCESSING_REQUIRED`, then call `FltCompletePendedPostOperation` inside the work item. Runs at `PASSIVE_LEVEL`.

### 7.4 Operations Supporting Pre and Post Callbacks

All `IRP_MJ_CREATE` through `IRP_MJ_PNP`, plus:
- `IRP_MJ_FAST_IO_CHECK_IF_POSSIBLE`
- `IRP_MJ_NETWORK_QUERY_OPEN`
- `IRP_MJ_MDL_READ` / `IRP_MJ_MDL_READ_COMPLETE`
- `IRP_MJ_PREPARE_MDL_WRITE` / `IRP_MJ_MDL_WRITE_COMPLETE`
- `IRP_MJ_VOLUME_MOUNT` / `IRP_MJ_VOLUME_DISMOUNT`
- `IRP_MJ_ACQUIRE_FOR_SECTION_SYNCHRONIZATION` / `IRP_MJ_RELEASE_FOR_SECTION_SYNCHRONIZATION`
- `IRP_MJ_ACQUIRE_FOR_MOD_WRITE` / `IRP_MJ_RELEASE_FOR_MOD_WRITE`
- `IRP_MJ_ACQUIRE_FOR_CC_FLUSH` / `IRP_MJ_RELEASE_FOR_CC_FLUSH`

---

## 8. Critical Callback Implementations

### 8.1 IRP_MJ_CREATE — The Most Important Callback

Every file and directory open/create triggers `IRP_MJ_CREATE`. Pre-create is the primary control point: block access, gather context about who opened what, and set up per-file tracking.

```c
FLT_PREOP_CALLBACK_STATUS PreCreate(
    PFLT_CALLBACK_DATA Data,
    PCFLT_RELATED_OBJECTS FltObjects,
    PVOID *CompletionContext)
{
    // 1. Always allow kernel-mode callers through to avoid blocking
    //    FltMgr and other kernel drivers from functioning
    if (Data->RequestorMode == KernelMode)
        return FLT_PREOP_SUCCESS_NO_CALLBACK;

    const auto& params = Data->Iopb->Parameters.Create;

    // 2. Decode create options — CreateDisposition in high 8 bits
    ULONG createOptions = params.Options & 0x00FFFFFF;
    ULONG createDisp    = (params.Options >> 24) & 0xFF;

    // 3. Inspect specific create flags
    bool deleteOnClose = (createOptions & FILE_DELETE_ON_CLOSE) != 0;
    bool isDirectory   = (createOptions & FILE_DIRECTORY_FILE)  != 0;

    // 4. Inspect desired access
    ACCESS_MASK access  = params.SecurityContext->DesiredAccess;
    bool wantsWrite     = (access & (FILE_WRITE_DATA | FILE_APPEND_DATA)) != 0;
    bool wantsExecute   = (access & FILE_EXECUTE) != 0;

    // 5. FILE_OBJECT->FileName is safe ONLY in pre-create
    PUNICODE_STRING rawName = &FltObjects->FileObject->FileName;
    // For normalized full path, use FltGetFileNameInformation instead

    // 6. Get requestor process info
    PEPROCESS process = FltGetRequestorProcess(Data);
    ULONG_PTR pid     = (ULONG_PTR)FltGetRequestorProcessId(Data);

    // 7. Block based on policy
    if (ShouldBlockAccess(rawName, process)) {
        Data->IoStatus.Status      = STATUS_ACCESS_DENIED;
        Data->IoStatus.Information = 0;
        return FLT_PREOP_COMPLETE;  // lower filters and FS never see this I/O
    }

    // 8. Request post-create callback if we need the result
    if (wantsWrite && !isDirectory) {
        *CompletionContext = (PVOID)(ULONG_PTR)pid;  // pass PID to post
        return FLT_PREOP_SUCCESS_WITH_CALLBACK;
    }

    return FLT_PREOP_SUCCESS_NO_CALLBACK;
}

// Post-create: check result before allocating tracking state
FLT_POSTOP_CALLBACK_STATUS PostCreate(
    PFLT_CALLBACK_DATA Data,
    PCFLT_RELATED_OBJECTS FltObjects,
    PVOID CompletionContext,
    FLT_POST_OPERATION_FLAGS Flags)
{
    if (Flags & FLTFL_POST_OPERATION_DRAINING)
        return FLT_POSTOP_FINISHED_PROCESSING;

    // Only proceed if file was actually opened
    if (!NT_SUCCESS(Data->IoStatus.Status))
        return FLT_POSTOP_FINISHED_PROCESSING;

    // Data->IoStatus.Information values:
    //   FILE_CREATED, FILE_OPENED, FILE_OVERWRITTEN,
    //   FILE_SUPERSEDED, FILE_EXISTS, FILE_DOES_NOT_EXIST

    // Post-create is ALWAYS at PASSIVE_LEVEL on the original thread
    // — safe for all DDIs including context allocation
    // ...allocate and set stream context here...
    return FLT_POSTOP_FINISHED_PROCESSING;
}
```

### 8.2 IRP_MJ_SET_INFORMATION — Rename and Delete Detection

```c
FLT_PREOP_CALLBACK_STATUS PreSetInformation(
    PFLT_CALLBACK_DATA Data,
    PCFLT_RELATED_OBJECTS FltObjects,
    PVOID *Ctx)
{
    if (Data->RequestorMode == KernelMode)
        return FLT_PREOP_SUCCESS_NO_CALLBACK;

    const auto& params = Data->Iopb->Parameters.SetFileInformation;

    switch (params.FileInformationClass) {

    // ── Delete detection ────────────────────────────────────────────
    case FileDispositionInformation: {
        auto* info = (FILE_DISPOSITION_INFORMATION*)params.InfoBuffer;
        if (info->DeleteFile) {
            PFLT_FILE_NAME_INFORMATION nameInfo = nullptr;
            if (NT_SUCCESS(FltGetFileNameInformation(Data,
                    FLT_FILE_NAME_NORMALIZED | FLT_FILE_NAME_QUERY_DEFAULT,
                    &nameInfo))) {
                FltParseFileNameInformation(nameInfo);
                // Log deletion event: nameInfo->Name, requestor PID
                FltReleaseFileNameInformation(nameInfo);
            }
        }
        break;
    }
    case FileDispositionInformationEx: {     // Windows 10 1607+
        auto* info = (FILE_DISPOSITION_INFORMATION_EX*)params.InfoBuffer;
        if (info->Flags & FILE_DISPOSITION_FLAG_DELETE) {
            // Handle delete-on-close for Win10+
        }
        break;
    }

    // ── Rename detection ────────────────────────────────────────────
    case FileRenameInformation:
    case FileRenameInformationEx: {
        auto* info = (FILE_RENAME_INFORMATION*)params.InfoBuffer;
        // info->FileName     = new name (wide chars)
        // info->FileNameLength = byte length of new name
        // info->ReplaceIfExists = TRUE to overwrite target
        // info->RootDirectory   = optional handle for relative rename
        UNICODE_STRING newName;
        newName.Buffer         = info->FileName;
        newName.Length         = (USHORT)info->FileNameLength;
        newName.MaximumLength  = newName.Length;
        KdPrint(("Rename to: %wZ\n", &newName));
        break;
    }

    // ── End-of-file (truncate / extend) ─────────────────────────────
    case FileEndOfFileInformation: {
        auto* info = (FILE_END_OF_FILE_INFORMATION*)params.InfoBuffer;
        KdPrint(("EOF set to: %lld\n", info->EndOfFile.QuadPart));
        break;
    }
    }
    return FLT_PREOP_SUCCESS_NO_CALLBACK;
}
```

### 8.3 IRP_MJ_READ / IRP_MJ_WRITE — Buffer Access

Accessing the data buffer depends on the I/O method. Always check for an MDL first (Direct I/O), then fall back to the raw buffer pointer.

```c
FLT_PREOP_CALLBACK_STATUS PreWrite(
    PFLT_CALLBACK_DATA Data,
    PCFLT_RELATED_OBJECTS FltObjects,
    PVOID *Ctx)
{
    if (Data->RequestorMode == KernelMode)
        return FLT_PREOP_SUCCESS_NO_CALLBACK;

    // Skip paging I/O — NEVER call FltGetFileNameInformation during paging I/O
    if (FlagOn(Data->Iopb->IrpFlags, IRP_PAGING_IO | IRP_SYNCHRONOUS_PAGING_IO))
        return FLT_PREOP_SUCCESS_NO_CALLBACK;

    const auto& params = Data->Iopb->Parameters.Write;
    ULONG  length = params.Length;
    PVOID  buffer = nullptr;

    // Direct I/O (MDL present) — always valid at any IRQL
    if (params.MdlAddress) {
        buffer = MmGetSystemAddressForMdlSafe(params.MdlAddress, NormalPagePriority);
    }
    // Neither I/O (no MDL) — user-mode VA, requires PASSIVE_LEVEL + __try/__except
    if (!buffer) {
        __try {
            buffer = params.WriteBuffer;
        } __except (EXCEPTION_EXECUTE_HANDLER) {
            buffer = nullptr;
        }
    }

    if (!buffer || length == 0)
        return FLT_PREOP_SUCCESS_NO_CALLBACK;

    LARGE_INTEGER offset = params.ByteOffset;
    // Use buffer for DLP scanning, encryption, etc.
    return FLT_PREOP_SUCCESS_NO_CALLBACK;
}
```

> **WARNING:** Do NOT access `Write.WriteBuffer` (Neither I/O) at `DISPATCH_LEVEL`. It is a user-mode virtual address requiring the correct process context and page fault handling. Always use `MmGetSystemAddressForMdlSafe` when MDL is present.

### 8.4 IRP_MJ_CLEANUP vs. IRP_MJ_CLOSE — When to Release Resources

| Aspect | `IRP_MJ_CLEANUP` | `IRP_MJ_CLOSE` |
|---|---|---|
| Triggered when | Last handle to the file is closed (`CloseHandle`) — FILE_OBJECT still has references | FILE_OBJECT reference count reaches zero |
| File data valid? | Yes — name queryable, contexts accessible | No — name may be invalid, contexts being torn down |
| Best use | Release driver-allocated stream/file contexts, flush local metadata, log final access telemetry | Final FILE_OBJECT cleanup (rarely needed) |
| IRQL guarantee | `PASSIVE_LEVEL` | `PASSIVE_LEVEL` |

> **Rule:** `IRP_MJ_CLEANUP` and `IRP_MJ_CLOSE` must **never be failed** by a minifilter. Completing with a failure status in `IoStatus` is illegal for these operations. They may be pended, passed through, or completed with `STATUS_SUCCESS` only.

---

## 9. Context Management

Contexts are reference-counted pieces of driver-private data attached to file system objects. FltMgr manages their lifetime and calls the minifilter's cleanup callback before freeing them.

### 9.1 Context Types

| Context Type | Constant | Attached To / Lifetime |
|---|---|---|
| Volume | `FLT_VOLUME_CONTEXT` | One per mounted volume. Use `NonPagedPool` (accessed at any IRQL) |
| Instance | `FLT_INSTANCE_CONTEXT` | One per filter instance (one per volume). Lives until instance teardown |
| File | `FLT_FILE_CONTEXT` | One per file (all streams combined). Lives until last FILE_OBJECT to that file is closed |
| Stream | `FLT_STREAM_CONTEXT` | One per file stream (NTFS supports multiple per file). FAT treats same as file context |
| StreamHandle | `FLT_STREAMHANDLE_CONTEXT` | One per FILE_OBJECT — per open handle. Most granular state |
| Transaction | `FLT_TRANSACTION_CONTEXT` | One per KTM transaction on NTFS |
| Section | `FLT_SECTION_CONTEXT` | One per memory-mapped section (Windows 8+) |

### 9.2 FLT_CONTEXT_REGISTRATION

```c
typedef struct _FLT_CONTEXT_REGISTRATION {
    FLT_CONTEXT_TYPE                ContextType;                // e.g. FLT_FILE_CONTEXT
    FLT_CONTEXT_REGISTRATION_FLAGS  Flags;                      // 0 for most uses
    PFLT_CONTEXT_CLEANUP_CALLBACK   ContextCleanupCallback;     // fires before free
    SIZE_T                          Size;                        // sizeof(MyContext) or FLT_VARIABLE_SIZED_CONTEXTS
    ULONG                           PoolTag;                     // e.g. 'xCtF'
    PFLT_CONTEXT_ALLOCATE_CALLBACK  ContextAllocateCallback;    // NULL = FltMgr allocates
    PFLT_CONTEXT_FREE_CALLBACK      ContextFreeCallback;        // NULL = FltMgr frees
    PVOID                           Reserved1;
} FLT_CONTEXT_REGISTRATION, *PFLT_CONTEXT_REGISTRATION;

// Example: per-file scan tracking context
typedef struct _FILE_CTX {
    FAST_MUTEX     Lock;
    BOOLEAN        Scanned;
    BOOLEAN        IsMalicious;
    LARGE_INTEGER  LastScanTime;
} FILE_CTX, *PFILE_CTX;

VOID FileContextCleanup(PFLT_CONTEXT Ctx, FLT_CONTEXT_TYPE Type) {
    // Called by FltMgr when refcount reaches 0.
    // Free any embedded resources — NOT the context struct itself (FltMgr does that).
    UNREFERENCED_PARAMETER(Type);
}

const FLT_CONTEXT_REGISTRATION g_ContextReg[] = {
    { FLT_FILE_CONTEXT, 0, FileContextCleanup, sizeof(FILE_CTX), 'xtFC', NULL, NULL, NULL },
    { FLT_CONTEXT_END }  // REQUIRED terminator
};
```

### 9.3 Context Lifecycle — Allocate, Set, Get, Release, Delete

```c
// ── Step 1: Allocate ────────────────────────────────────────────────
FILE_CTX* ctx = nullptr;
NTSTATUS status = FltAllocateContext(
    FltObjects->Filter,        // filter handle (from FLT_RELATED_OBJECTS)
    FLT_FILE_CONTEXT,          // context type
    sizeof(FILE_CTX),          // must match FLT_CONTEXT_REGISTRATION.Size
    PagedPool,                 // use NonPagedPool for volume contexts
    (PFLT_CONTEXT*)&ctx);
// Allocated memory is NOT zeroed — initialize all fields explicitly.
// After FltAllocateContext: refcount = 1

// ── Step 2: Initialize ──────────────────────────────────────────────
ctx->Scanned     = FALSE;
ctx->IsMalicious = FALSE;
ExInitializeFastMutex(&ctx->Lock);

// ── Step 3: Attach to file object ───────────────────────────────────
PFLT_CONTEXT oldCtx = nullptr;
status = FltSetFileContext(
    FltObjects->Instance,
    FltObjects->FileObject,
    FLT_SET_CONTEXT_KEEP_IF_EXISTS,  // or FLT_SET_CONTEXT_REPLACE_IF_EXISTS
    ctx,                             // new context
    &oldCtx);                        // receives replaced context (may be NULL)

if (oldCtx) FltReleaseContext(oldCtx);  // release the replaced context

// ── Step 4: Release our allocation reference ────────────────────────
// After FltSetContext: refcount = 2 (allocation ref + set ref).
// Release our allocation reference — FltMgr holds the "set" reference.
FltReleaseContext(ctx);  // refcount back to 1
// Do NOT dereference ctx after this release.

// ── Step 5: Get context in a later callback ──────────────────────────
FILE_CTX* retrievedCtx = nullptr;
status = FltGetFileContext(
    FltObjects->Instance,
    FltObjects->FileObject,
    (PFLT_CONTEXT*)&retrievedCtx);
// FltGet increments refcount — MUST release after use.
if (NT_SUCCESS(status) && retrievedCtx) {
    ExAcquireFastMutex(&retrievedCtx->Lock);
    // ... use context ...
    ExReleaseFastMutex(&retrievedCtx->Lock);
    FltReleaseContext(retrievedCtx);  // decrement refcount
}

// ── Step 6: Delete context explicitly (e.g., in IRP_MJ_CLEANUP) ─────
FltDeleteContext(ctx);  // marks for deletion; freed when refcount = 0
```

### 9.4 Set Operations

| Operation | Behavior |
|---|---|
| `FLT_SET_CONTEXT_KEEP_IF_EXISTS` | Set only if no existing context. Returns error and existing context via `OldContext` if one exists. Caller must release both the old and new contexts. |
| `FLT_SET_CONTEXT_REPLACE_IF_EXISTS` | Always set, replacing any existing context. Returns old context via `OldContext`. Caller must release old context; if `OldContext` is `NULL`, FltMgr releases it automatically. |

### 9.5 Bulk Context Retrieval

```c
// Get multiple contexts in one call — more efficient than individual calls:
FLT_RELATED_CONTEXTS relCtxs;
FltGetContexts(FltObjects,
               FLT_FILE_CONTEXT | FLT_INSTANCE_CONTEXT,  // DesiredContexts
               &relCtxs);

// Use relCtxs.FileContext, relCtxs.InstanceContext...

FltReleaseContexts(&relCtxs);  // release all in one call
```

### 9.6 Context Retrieval Restrictions

> Contexts **cannot be retrieved at DPC level**. If a context is needed in a post-operation callback that may run at `DISPATCH_LEVEL`, retrieve it in the pre-operation callback and pass it through `CompletionContext`.

> **Reference count discipline:** `FltAllocateContext` = +1. `FltSetXxxContext` = +1. `FltGetXxxContext` = +1. Every +1 must be balanced with `FltReleaseContext`. Contexts with refcount > 0 when the driver unloads will prevent unloading and cause Driver Verifier violations.

---

## 10. File Name Resolution

### 10.1 Why FILE_OBJECT->FileName Is Unreliable

`FILE_OBJECT->FileName` is **only** guaranteed to be populated and accurate during an `IRP_MJ_CREATE` **pre-operation callback**. In all other contexts it may be empty, stale, relative (not a full path), or in device form.

**Never use `FILE_OBJECT->FileName` outside of `IRP_MJ_CREATE` pre-callbacks.** Use `FltGetFileNameInformation` everywhere else.

### 10.2 FLT_FILE_NAME_INFORMATION Structure

```c
typedef struct _FLT_FILE_NAME_INFORMATION {
    USHORT                   Size;
    FLT_FILE_NAME_PARSED_FLAGS NamesParsed;    // which fields have been parsed
    FLT_FILE_NAME_OPTIONS    Format;
    UNICODE_STRING           Name;             // full path (device form)
    UNICODE_STRING           Volume;           // e.g. \Device\HarddiskVolume3
    UNICODE_STRING           Share;            // UNC share (empty for local files)
    UNICODE_STRING           Extension;        // e.g. txt  (no dot)
    UNICODE_STRING           Stream;           // NTFS alternate stream (e.g. :mystream)
    UNICODE_STRING           FinalComponent;   // e.g. myfile.txt
    UNICODE_STRING           ParentDir;        // e.g. \mydir1\mydir2\  (trailing backslash)
} FLT_FILE_NAME_INFORMATION, *PFLT_FILE_NAME_INFORMATION;

// Breakdown for \Device\HarddiskVolume3\mydir\myfile.txt:stream1:
// Name          = \Device\HarddiskVolume3\mydir\myfile.txt:stream1
// Volume        = \Device\HarddiskVolume3
// Share         = (empty — local file)
// ParentDir     = \mydir\
// FinalComponent= myfile.txt:stream1
// Extension     = txt
// Stream        = :stream1
```

### 10.3 Name Format and Query Options

| Flag | Description |
|---|---|
| `FLT_FILE_NAME_NORMALIZED` | Full path with resolved symbolic links and junctions. All short (8.3) names expanded to long form. Required for `FltParseFileNameInformation` to work. |
| `FLT_FILE_NAME_OPENED` | The name as it was opened — may be relative or contain short names. Faster but less reliable. |
| `FLT_FILE_NAME_SHORT` | 8.3 short name of the final component only. Rarely needed. |
| `FLT_FILE_NAME_QUERY_DEFAULT` | Check FltMgr's name cache first, then query the filesystem. Best for most uses. |
| `FLT_FILE_NAME_QUERY_CACHE_ONLY` | Only check cache; fail with `STATUS_FLT_NAME_CACHE_MISS` if not found. Use during paging I/O. |
| `FLT_FILE_NAME_QUERY_FILESYSTEM_ONLY` | Always query filesystem; bypass cache. Accurate but slower. |
| `FLT_FILE_NAME_ALLOW_QUERY_ON_REPARSE` | Allow name query even when file object has a pending reparse point. |

### 10.4 Correct Usage Pattern

```c
PFLT_FILE_NAME_INFORMATION nameInfo = nullptr;

NTSTATUS status = FltGetFileNameInformation(
    Data,
    FLT_FILE_NAME_NORMALIZED | FLT_FILE_NAME_QUERY_DEFAULT,
    &nameInfo);

if (NT_SUCCESS(status)) {
    // Parse to populate Extension, ParentDir, FinalComponent etc.
    // (Name, Volume, and Share are always populated by FltGet)
    status = FltParseFileNameInformation(nameInfo);
    if (NT_SUCCESS(status)) {
        KdPrint(("File: %wZ  Ext: %wZ\n",
                  &nameInfo->Name, &nameInfo->Extension));
    }
    FltReleaseFileNameInformation(nameInfo);  // MUST always release
}
```

### 10.5 When Can You Call FltGetFileNameInformation?

| Callback Context | Restriction |
|---|---|
| `IRP_MJ_CREATE` pre | Safe. `FILE_OBJECT->FileName` also available here. |
| `IRP_MJ_CREATE` post | Safe — always `PASSIVE_LEVEL`. |
| `IRP_MJ_READ/WRITE` pre (non-paging) | Safe at `PASSIVE_LEVEL`. |
| Paging I/O (`IrpFlags & IRP_PAGING_IO`) | **DEADLOCK** — must use `QUERY_CACHE_ONLY` or skip entirely |
| Post callback at `DISPATCH_LEVEL` | **IRQL violation** — defer to worker thread first |
| `IRP_MJ_CLEANUP` | Safe — `PASSIVE_LEVEL` guaranteed |

### 10.6 Additional Name APIs

```c
// Destination name for rename / hardlink creation operations:
// Use during IRP_MJ_SET_INFORMATION pre with FileRenameInformation or FileLinkInformation
NTSTATUS FltGetDestinationFileNameInformation(
    IN PFLT_INSTANCE              Instance,
    IN PFILE_OBJECT               FileObject,
    IN HANDLE                     RootDirectory OPTIONAL,
    IN PWSTR                      FileName,
    IN ULONG                      FileNameLength,
    IN FLT_FILE_NAME_OPTIONS      NameOptions,
    OUT PFLT_FILE_NAME_INFORMATION *FileNameInformation);

// Name tunneling — detect when a cached name is invalidated by a rename:
// Call in post-callback for CREATE / rename after getting normalized name in pre
NTSTATUS FltGetTunneledName(
    IN PFLT_CALLBACK_DATA          CallbackData,
    IN PFLT_FILE_NAME_INFORMATION  FileNameInformation,
    OUT PFLT_FILE_NAME_INFORMATION *RetTunneledFileNameInformation);
```

### 10.7 C++ RAII Wrapper

```cpp
struct FilterFileNameInformation {
    FilterFileNameInformation(PFLT_CALLBACK_DATA data,
        FLT_FILE_NAME_OPTIONS opts =
            FLT_FILE_NAME_NORMALIZED | FLT_FILE_NAME_QUERY_DEFAULT)
    {
        _status = FltGetFileNameInformation(data, opts, &_info);
        if (!NT_SUCCESS(_status)) _info = nullptr;
    }
    ~FilterFileNameInformation() {
        if (_info) FltReleaseFileNameInformation(_info);
    }
    NTSTATUS Parse() { return _info ? FltParseFileNameInformation(_info) : _status; }
    bool     IsValid() const                       { return _info != nullptr; }
    PFLT_FILE_NAME_INFORMATION operator->() const  { return _info; }
    explicit operator bool() const                  { return IsValid(); }
    FilterFileNameInformation(const FilterFileNameInformation&) = delete;
    FilterFileNameInformation& operator=(const FilterFileNameInformation&) = delete;
private:
    PFLT_FILE_NAME_INFORMATION _info   = nullptr;
    NTSTATUS                   _status = STATUS_SUCCESS;
};

// Usage:
FilterFileNameInformation nameInfo(Data);
if (nameInfo && NT_SUCCESS(nameInfo.Parse())) {
    KdPrint(("Extension: %wZ\n", &nameInfo->Extension));
}
```

---

## 11. User-Mode Communication Port

### 11.1 Architecture Overview

Minifilters communicate with user-mode services through FltMgr's built-in communication port mechanism. This is preferred over custom IOCTL device objects — it integrates with FltMgr's lifetime management and provides bidirectional structured message passing.

```
  Kernel (minifilter)                     User-Mode Service
  ──────────────────────                  ─────────────────────
  FltCreateCommunicationPort()            FilterConnectCommunicationPort()
         │                                          │
         │◄──── ConnectNotifyCallback ──────────────┤
         │                                          │
         │  FltSendMessage(kernel→user) ───────────►│  FilterGetMessage()
         │  (with reply wait)                        │  FilterReplyMessage()
         │◄──────────────────────── reply ───────────┤
         │
         │◄──── MessageNotifyCallback (user→kernel) ─┤  FilterSendMessage()
         │
         │──── DisconnectNotifyCallback ─────────────┤  CloseHandle(port)
```

### 11.2 Kernel-Side Port Creation

```c
PFLT_PORT g_ServerPort = nullptr;
PFLT_PORT g_ClientPort = nullptr;

NTSTATUS ConnectNotify(
    PFLT_PORT  ClientPort,
    PVOID      ServerPortCookie,
    PVOID      ConnectionContext,
    ULONG      SizeOfContext,
    PVOID     *ConnectionPortCookie)
{
    g_ClientPort = ClientPort;
    *ConnectionPortCookie = nullptr;  // per-connection context
    return STATUS_SUCCESS;
}

VOID DisconnectNotify(PVOID ConnectionCookie) {
    FltCloseClientPort(g_Filter, &g_ClientPort);
    g_ClientPort = nullptr;
}

NTSTATUS MessageNotify(
    PVOID  PortCookie,
    PVOID  InputBuffer,    ULONG InputBufferLength,
    PVOID  OutputBuffer,   ULONG OutputBufferLength,
    PULONG ReturnOutputBufferLength)
{
    // Process command from user mode (policy update, configuration, etc.)
    *ReturnOutputBufferLength = 0;
    return STATUS_SUCCESS;
}

NTSTATUS CreateCommPort() {
    PSECURITY_DESCRIPTOR sd;
    NTSTATUS status = FltBuildDefaultSecurityDescriptor(&sd, FLT_PORT_ALL_ACCESS);
    if (!NT_SUCCESS(status)) return status;

    UNICODE_STRING portName = RTL_CONSTANT_STRING(L"\\MyFilterPort");
    OBJECT_ATTRIBUTES oa;
    InitializeObjectAttributes(&oa, &portName,
        OBJ_KERNEL_HANDLE | OBJ_CASE_INSENSITIVE, nullptr, sd);

    status = FltCreateCommunicationPort(
        g_Filter,
        &g_ServerPort,
        &oa,
        nullptr,           // server port cookie
        ConnectNotify,
        DisconnectNotify,
        MessageNotify,
        1);                // MaxConnections: 1 for single-client scanner

    FltFreeSecurityDescriptor(sd);
    return status;
}
```

> **Rules:** `MaxConnections` must be greater than 0. Always call `ZwClose` (or `FltCloseCommunicationPort`) on the server port handle in the `FilterUnload` callback. Minifilters must close the server port before `FltUnregisterFilter` to avoid hangs.

### 11.3 Shared Message Structures (Kernel + User)

These structures must be shared between the kernel driver and user-mode service via a common header file.

```c
// Shared with user-mode — use in MyFilterPublic.h
typedef struct _SCAN_REQUEST {
    FILTER_MESSAGE_HEADER   Header;     // MUST be first field
    WCHAR   FilePath[512];
    HANDLE  ProcessId;
    ULONG   CreateOptions;
    ULONG   AccessMask;
} SCAN_REQUEST, *PSCAN_REQUEST;

typedef struct _SCAN_REPLY {
    FILTER_REPLY_HEADER  Header;        // MUST be first field
    BOOLEAN              Allow;         // TRUE = allow, FALSE = block
    ULONG                ThreatId;      // 0 if no threat
} SCAN_REPLY, *PSCAN_REPLY;
```

### 11.4 Kernel: Send Message and Wait for Reply

```c
NTSTATUS SendScanRequest(
    PFLT_CALLBACK_DATA    Data,
    PCFLT_RELATED_OBJECTS FltObjects,
    PBOOLEAN              AllowAccess)
{
    *AllowAccess = TRUE;               // default to allow
    if (!g_ClientPort) return STATUS_SUCCESS;

    SCAN_REQUEST  req   = {};
    SCAN_REPLY    reply = {};
    ULONG         replyLen = sizeof(SCAN_REPLY);

    RtlCopyMemory(req.FilePath,
        FltObjects->FileObject->FileName.Buffer,
        min(FltObjects->FileObject->FileName.Length,
            sizeof(req.FilePath) - sizeof(WCHAR)));
    req.ProcessId = FltGetRequestorProcessId(Data);

    LARGE_INTEGER timeout;
    timeout.QuadPart = -10000LL * 3000;  // 3-second relative timeout

    NTSTATUS status = FltSendMessage(
        g_Filter,
        &g_ClientPort,
        (PUCHAR)&req + sizeof(FILTER_MESSAGE_HEADER),  // payload only
        sizeof(req)   - sizeof(FILTER_MESSAGE_HEADER),
        &reply,
        &replyLen,
        &timeout);

    if (NT_SUCCESS(status))
        *AllowAccess = reply.Allow;

    return status;
}
```

### 11.5 User Mode: Connect and Process Messages

```c
// User-mode scanner service (link with FltLib.lib, include fltuser.h)
HANDLE hPort;
FilterConnectCommunicationPort(
    L"\\MyFilterPort",
    0, nullptr, 0, nullptr, &hPort);

// Receive loop:
SCAN_REQUEST req;
DWORD bytesReturned;
while (TRUE) {
    FilterGetMessage(hPort, &req.Header, sizeof(req), nullptr);

    // Scan the file...
    BOOL allow = !IsMalicious(req.FilePath);

    SCAN_REPLY reply = {};
    reply.Header.Status    = STATUS_SUCCESS;
    reply.Header.MessageId = req.Header.MessageId;  // MUST echo the message ID
    reply.Allow            = allow;

    FilterReplyMessage(hPort, &reply.Header, sizeof(reply));
}
```

> **Performance note:** For high-throughput systems, the blocking `FltSendMessage` scan-per-file pattern can bottleneck on busy servers. An alternative is to post telemetry events into a shared memory ring buffer from kernel mode, signal an event, and have user mode drain it independently without ever blocking file I/O.

---

## 12. Filter-Initiated I/O

### 12.1 Why Not ZwCreateFile?

`ZwCreateFile` inside a minifilter callback sends the IRP to the **top of the filter stack**, where the calling minifilter will **re-intercept its own request** — causing infinite recursion, deadlocks, or stack overflow.

`FltCreateFile` sends the IRP to the next instance **below** the caller, bypassing all higher-altitude minifilters. Always use `FltCreateFile` (and its variants) for file I/O from within callbacks.

### 12.2 FltCreateFile / FltCreateFileEx

```c
NTSTATUS FltCreateFile(
    _In_     PFLT_FILTER             Filter,
    _In_opt_ PFLT_INSTANCE           Instance,    // always pass your own instance
    _Out_    PHANDLE                 FileHandle,
    _In_     ACCESS_MASK             DesiredAccess,
    _In_     POBJECT_ATTRIBUTES      ObjectAttributes,
    _Out_    PIO_STATUS_BLOCK        IoStatusBlock,
    _In_opt_ PLARGE_INTEGER          AllocationSize,
    _In_     ULONG                   FileAttributes,
    _In_     ULONG                   ShareAccess,
    _In_     ULONG                   CreateDisposition,
    _In_     ULONG                   CreateOptions,
    _In_opt_ PVOID                   EaBuffer,
    _In_     ULONG                   EaLength,
    _In_     ULONG                   Flags);

// Critical Flags:
// IO_IGNORE_SHARE_ACCESS_CHECK  — bypass share mode on an already-open file
// IO_NO_PARAMETER_CHECKING      — skip parameter validation (trusted kernel caller)
// IO_OPEN_TARGET_DIRECTORY      — open the parent directory
```

> **Note:** The `FileHandle` returned by `FltCreateFile` can be used with all `Zw*` calls. If `Instance` is non-NULL, FltMgr guarantees all future I/O on this handle is only seen by instances below `Instance`.

### 12.3 FltReadFile / FltWriteFile

```c
// Use FILE_OBJECT pointer for performance (vs. going through the handle table)
NTSTATUS FltReadFile(
    _In_     PFLT_INSTANCE   InitiatingInstance,
    _In_     PFILE_OBJECT    FileObject,
    _In_opt_ PLARGE_INTEGER  ByteOffset,     // NULL = current file position
    _In_     ULONG           Length,
    _Out_    PVOID           Buffer,
    _In_     FLT_IO_OPERATION_FLAGS Flags,   // FLTFL_IO_OPERATION_NON_RECURSIVE
    _Out_opt_ PULONG          BytesRead,
    _In_opt_ PFLT_COMPLETED_ASYNC_IO_CALLBACK Callback,
    _In_opt_ PVOID           CallbackContext);

NTSTATUS FltWriteFile(
    _In_     PFLT_INSTANCE   InitiatingInstance,
    _In_     PFILE_OBJECT    FileObject,
    _In_opt_ PLARGE_INTEGER  ByteOffset,
    _In_     ULONG           Length,
    _In_     PVOID           Buffer,
    _In_     FLT_IO_OPERATION_FLAGS Flags,
    _Out_opt_ PULONG          BytesWritten,
    _In_opt_ PFLT_COMPLETED_ASYNC_IO_CALLBACK Callback,
    _In_opt_ PVOID           CallbackContext);
```

> **IMPORTANT:** Do not use `FltReadFile`/`FltWriteFile` on handles created by `FltCreateFile`. For handles from `FltCreateFile`, use the normal `Zw*` APIs — they are automatically routed to the correct instance relative to `InitiatingInstance`.

### 12.4 Low-Level I/O (FltAllocateCallbackData)

For complete control over the I/O packet:

```c
PFLT_CALLBACK_DATA callbackData = nullptr;
FltAllocateCallbackData(Instance, FileObject, &callbackData);

// Fill in the I/O parameters...
callbackData->Iopb->MajorFunction = IRP_MJ_READ;
callbackData->Iopb->Parameters.Read.Length = bufferLen;
// ...

// Execute synchronously:
FltPerformSynchronousIo(callbackData);

// Or asynchronously:
FltPerformAsynchronousIo(callbackData, CompletionCallback, CallbackContext);

// Always free when done:
FltFreeCallbackData(callbackData);
```

---

## 13. Unload, Detach, and Teardown Rules

### 13.1 Minifilter Detach

A minifilter instance can be detached from a volume via:
- `FltDetachVolume` (kernel mode)
- `FilterDetach` (user mode)
- Volume dismount
- Minifilter unload

When an instance is detached with outstanding I/O, the minifilter's post-operation callbacks are called with `FLTFL_POST_OPERATION_DRAINING` set. Minifilters must return `FLT_POSTOP_FINISHED_PROCESSING` immediately when draining — **no deferred processing is allowed**.

When an instance is detached, FltMgr calls the context cleanup routines for all contexts associated with files, streams, and stream handles on that instance.

### 13.2 Minifilter Unload

Unloading (`FltUnregisterFilter`) is the most common path during system shutdown or driver update. It implies detaching all instances.

A minifilter can prevent voluntary unload by returning a failure status from `FilterUnloadCallback`. However, if `FLT_FILTER_UNLOAD_FLAGS` has `FLTFL_FILTER_UNLOAD_MANDATORY` set, the unload cannot be refused.

### 13.3 Unload Sequence

```
1. FilterUnloadCallback called
2. Close server communication port (FltCloseCommunicationPort)
   → Drains pending messages, calls DisconnectNotifyCallback
3. FltUnregisterFilter called
   → Calls InstanceQueryTeardown for each instance (if registered)
   → Calls InstanceTeardownStart for each instance
   → Waits for all pending I/O to drain
   → Calls InstanceTeardownComplete for each instance
   → Frees all contexts associated with each instance
   → Frees the filter object
```

---

## 14. Buffer Access

### 14.1 Three I/O Methods

| Method | Source | Access Pattern |
|---|---|---|
| Buffered I/O | System allocates kernel buffer; `FLTFL_CALLBACK_DATA_SYSTEM_BUFFER` is set | Always accessible at any IRQL from kernel address space |
| Direct I/O | MDL present in `Read/Write.MdlAddress` | Access via `MmGetSystemAddressForMdlSafe` — always valid at any IRQL |
| Neither I/O | Raw user-mode VA in `Read/Write.ReadBuffer` / `Write.WriteBuffer` | Only valid in the requestor's process context at `PASSIVE_LEVEL`; must use `__try/__except` |

### 14.2 Buffer Access Helper

```c
// FltDecodeParameters — fast lookup of buffer/MDL/length for common operations:
NTSTATUS FltDecodeParameters(
    IN PFLT_CALLBACK_DATA  CallbackData,
    OUT PMDL              **MdlAddressPointer OPTIONAL,
    OUT PVOID             **Buffer OPTIONAL,
    OUT PULONG             *Length OPTIONAL,
    OUT LOCK_OPERATION     *DesiredAccess OPTIONAL);
// Returns STATUS_INVALID_PARAMETER for operations where buffers are not applicable.

// Lock a user-mode buffer safely:
// FltLockUserBuffer acquires the pages with the correct access for the operation
// and sets the MdlAddress field in the operation-specific parameter portion.
NTSTATUS FltLockUserBuffer(IN PFLT_CALLBACK_DATA CallbackData);
```

### 14.3 Buffer Swapping (Encryption Use Case)

When a minifilter needs to substitute a different buffer for an operation (e.g., transparently encrypting write data):

**Rules:**
1. Must supply a post-callback (buffer is automatically restored by FltMgr).
2. If `FLTFL_CALLBACK_DATA_SYSTEM_BUFFER` was set, the new buffer **must** be from non-paged memory.
3. If the original was not system-buffered, the new buffer must meet the device's Direct I/O requirements.
4. If supplanting a non-paged buffer when `SYSTEM_BUFFER` is NOT set, build an MDL via `MmBuildMdlForNonPagedPool`.
5. When switching buffer, also switch the MDL (keep them in sync). MDL may be NULL subject to Direct I/O rules.
6. Do **NOT** free the old buffer or MDL.
7. Do **NOT** try to restore the old buffer/MDL in the post-callback — FltMgr does this automatically.
8. **DO** free the buffer you allocated in the post-callback. FltMgr automatically frees the swapped MDL unless `FltRetainSwappedBufferMdl` is called.
9. Use `FltGetSwappedBufferMdl` in post-callback to access the MDL that a lower filter/filesystem may have created for your swapped buffer.

---

## 15. IRQL Constraints and Safe Patterns

### 15.1 IRQL Summary

| Callback | IRQL |
|---|---|
| `InstanceSetupCallback` | `PASSIVE_LEVEL` |
| `InstanceTeardownStart/Complete` | `PASSIVE_LEVEL` |
| Pre-operation callback | Depends on operation. `PASSIVE_LEVEL` for most. `APC_LEVEL` or higher for paging I/O. |
| Post-operation callback | Up to `DISPATCH_LEVEL` — EXCEPT `IRP_MJ_CREATE` post (always `PASSIVE_LEVEL`) |
| `FilterUnloadCallback` | `PASSIVE_LEVEL` |
| Context cleanup callback | `PASSIVE_LEVEL` |

### 15.2 What Requires PASSIVE_LEVEL

- `FltGetFileNameInformation`
- `FltAllocateContext`, `FltSetXxxContext`, `FltGetXxxContext`
- `ExAcquireFastMutex`, `KeWaitForSingleObject`
- `ExAllocatePoolWithTag` (`PagedPool`)
- Opening files, querying volume properties

### 15.3 Paging I/O — Handle With Extreme Care

```c
FLT_PREOP_CALLBACK_STATUS PreRead(
    PFLT_CALLBACK_DATA Data, PCFLT_RELATED_OBJECTS FltObjects, PVOID *Ctx)
{
    // Check for paging I/O before ANYTHING else
    if (FLT_IS_IRP_OPERATION(Data) &&
        FlagOn(Data->Iopb->IrpFlags, IRP_PAGING_IO | IRP_SYNCHRONOUS_PAGING_IO))
        return FLT_PREOP_SUCCESS_NO_CALLBACK;

    // Safe to proceed with name query and context operations from here
    FilterFileNameInformation nameInfo(Data);
    // ...
    return FLT_PREOP_SUCCESS_NO_CALLBACK;
}
```

---

## 16. Common Pitfalls

| Mistake | Consequence | Fix |
|---|---|---|
| `FltGetFileNameInformation` during paging I/O | **Deadlock** — system hangs | Check `IRP_PAGING_IO` flag and return early |
| `FltGetFileNameInformation` in post callback at `DISPATCH_LEVEL` | `IRQL_NOT_LESS_OR_EQUAL` bugcheck | Use `FltDoCompletionProcessingWhenSafe` first |
| Using `FILE_OBJECT->FileName` outside `IRP_MJ_CREATE` pre | Empty or stale path — wrong file name | Always use `FltGetFileNameInformation` in other callbacks |
| `FltAllocateContext` without balancing `FltReleaseContext` | Context leak; driver cannot unload | Release count = Allocate + all Get calls; use RAII wrapper |
| `ZwCreateFile` from minifilter callback | Reentrancy — filter intercepts its own I/O | Use `FltCreateFile` with `Instance` parameter |
| Setting `DriverUnload` after `FltRegisterFilter` | Corrupted unload path | Only set `FilterUnloadCallback` in `FLT_REGISTRATION` |
| Not checking `FLTFL_POST_OPERATION_DRAINING` | `FltDoCompletionProcessingWhenSafe` called during draining — bugcheck | Check flag at start of every post callback; return immediately |
| Allocating context in pre-callback without checking `IoStatus` in post | Context for failed opens is never cleaned up | In post-create, check `NT_SUCCESS(Data->IoStatus.Status)` before using context |
| Missing `IRP_MJ_OPERATION_END` terminator in `FLT_OPERATION_REGISTRATION` | Bugcheck at registration or runtime | Always end the callback array with `{ IRP_MJ_OPERATION_END }` |
| Missing `FLT_CONTEXT_END` terminator | Bugcheck at registration | Always end the context array with `{ FLT_CONTEXT_END }` |
| Failing `IRP_MJ_CLEANUP` or `IRP_MJ_CLOSE` | System instability — these must succeed | Never return a failure status for CLEANUP or CLOSE |
| Changing `TargetInstance` to another instance on the same volume | Bypasses filters between altitudes — illegal | Only redirect to instances on a **different** volume |
| Accessing `Write.WriteBuffer` (Neither I/O) at `DISPATCH_LEVEL` | Access violation or data corruption | Use MDL + `MmGetSystemAddressForMdlSafe`; wrap Neither I/O in `__try/__except` |
| Not closing server port before `FltUnregisterFilter` | System hang during unload | Always call `FltCloseCommunicationPort` first in `FilterUnload` |
| Not calling `FltSetCallbackDataDirty` after modifying `Iopb` | Changes silently ignored — unpredictable failures | Call `FltSetCallbackDataDirty(Data)` after any `Iopb` modification |

---

## 17. Complete Driver Skeleton

### 17.1 File and Project Structure

```
MyFilter\
  Driver.cpp        — DriverEntry, global state
  MiniFilter.cpp    — FLT_REGISTRATION, all minifilter callbacks
  Context.h/cpp     — FLT_CONTEXT_REGISTRATION, context type definitions, helpers
  CommPort.h/cpp    — FltCreateCommunicationPort, message structures, send/receive
  FileOps.cpp       — FltCreateFile, FltReadFile helper wrappers
  MyFilter.inf      — INF for altitude/instance registry entries
  MyFilterPublic.h  — SHARED with user-mode: FILTER_MESSAGE_HEADER structs, codes

  // Kernel driver:  #include <fltKernel.h>  (brings in ntifs.h, wdm.h)
  //                 Link: FltMgr.lib
  // User-mode tool: #include <fltuser.h>
  //                 Link: FltLib.lib
```

### 17.2 Complete DriverEntry and Registration

```c
#include <fltKernel.h>
#pragma warning(disable: 4100)

#define DRIVER_TAG   'tliF'

// ── Forward declarations ─────────────────────────────────────────────
NTSTATUS DriverEntry(PDRIVER_OBJECT, PUNICODE_STRING);
NTSTATUS FilterUnload(FLT_FILTER_UNLOAD_FLAGS);
NTSTATUS InstanceSetup(PCFLT_RELATED_OBJECTS, FLT_INSTANCE_SETUP_FLAGS,
                       DEVICE_TYPE, FLT_FILESYSTEM_TYPE);
NTSTATUS InstanceQueryTeardown(PCFLT_RELATED_OBJECTS,
                               FLT_INSTANCE_QUERY_TEARDOWN_FLAGS);
VOID     InstanceTeardownStart(PCFLT_RELATED_OBJECTS,
                               FLT_INSTANCE_TEARDOWN_FLAGS);
VOID     InstanceTeardownComplete(PCFLT_RELATED_OBJECTS,
                                  FLT_INSTANCE_TEARDOWN_FLAGS);
FLT_PREOP_CALLBACK_STATUS  PreCreate(PFLT_CALLBACK_DATA,
                                     PCFLT_RELATED_OBJECTS, PVOID*);
FLT_POSTOP_CALLBACK_STATUS PostCreate(PFLT_CALLBACK_DATA,
                                      PCFLT_RELATED_OBJECTS, PVOID,
                                      FLT_POST_OPERATION_FLAGS);
FLT_PREOP_CALLBACK_STATUS  PreSetInfo(PFLT_CALLBACK_DATA,
                                      PCFLT_RELATED_OBJECTS, PVOID*);
FLT_POSTOP_CALLBACK_STATUS PostCleanup(PFLT_CALLBACK_DATA,
                                       PCFLT_RELATED_OBJECTS, PVOID,
                                       FLT_POST_OPERATION_FLAGS);

// ── Global state ──────────────────────────────────────────────────────
PFLT_FILTER g_Filter  = nullptr;
PFLT_PORT   g_SrvPort = nullptr;
PFLT_PORT   g_CliPort = nullptr;

// ── Context registration ──────────────────────────────────────────────
const FLT_CONTEXT_REGISTRATION g_ContextReg[] = {
    { FLT_FILE_CONTEXT, 0, nullptr, sizeof(FILE_CTX),
      DRIVER_TAG, nullptr, nullptr, nullptr },
    { FLT_CONTEXT_END }
};

// ── Operation callbacks ───────────────────────────────────────────────
const FLT_OPERATION_REGISTRATION g_Callbacks[] = {
    { IRP_MJ_CREATE,
      0,
      PreCreate, PostCreate },
    { IRP_MJ_SET_INFORMATION,
      0,
      PreSetInfo, nullptr },
    { IRP_MJ_CLEANUP,
      0,
      nullptr, PostCleanup },
    { IRP_MJ_WRITE,
      FLTFL_OPERATION_REGISTRATION_SKIP_PAGING_IO,
      PreWrite, nullptr },
    { IRP_MJ_OPERATION_END }  // REQUIRED
};

// ── Master registration ───────────────────────────────────────────────
const FLT_REGISTRATION g_Registration = {
    sizeof(FLT_REGISTRATION),
    FLT_REGISTRATION_VERSION,
    0,
    g_ContextReg,
    g_Callbacks,
    FilterUnload,
    InstanceSetup,
    InstanceQueryTeardown,
    InstanceTeardownStart,
    InstanceTeardownComplete,
};

// ── DriverEntry ───────────────────────────────────────────────────────
extern "C" NTSTATUS
DriverEntry(PDRIVER_OBJECT DriverObject, PUNICODE_STRING RegistryPath)
{
    NTSTATUS status;

    // 1. Write altitude/instance registry values
    status = WriteAltitudeRegistryValues(DriverObject, RegistryPath);
    if (!NT_SUCCESS(status)) return status;

    // 2. Register with FltMgr (does NOT start filtering yet)
    status = FltRegisterFilter(DriverObject, &g_Registration, &g_Filter);
    if (!NT_SUCCESS(status)) return status;

    // 3. Create communication port
    status = CreateCommPort(g_Filter, &g_SrvPort);
    if (!NT_SUCCESS(status)) {
        FltUnregisterFilter(g_Filter);
        return status;
    }

    // 4. Start filtering — arms all callbacks, triggers InstanceSetup
    //    for all existing volumes. Call LAST.
    status = FltStartFiltering(g_Filter);
    if (!NT_SUCCESS(status)) {
        FltCloseCommunicationPort(g_SrvPort);
        FltUnregisterFilter(g_Filter);
    }
    return status;
}

// ── Unload ────────────────────────────────────────────────────────────
NTSTATUS FilterUnload(FLT_FILTER_UNLOAD_FLAGS Flags) {
    if (g_SrvPort) FltCloseCommunicationPort(g_SrvPort);
    FltUnregisterFilter(g_Filter);
    return STATUS_SUCCESS;
}
```

---

## 18. Debugging with WinDbg and fltmc

### 18.1 WinDbg Commands

```
// List all loaded minifilters and their altitudes:
!fltkd.filters

// Detailed info for a specific filter (callbacks, contexts, instances):
!fltkd.filter <PFLT_FILTER address>

// Show all instances of a specific filter across volumes:
!fltkd.instances <PFLT_FILTER address>

// Show pending I/O requests in the Filter Manager:
!fltkd.irpctrl

// Dump the FLT_CALLBACK_DATA structure:
dt fltmgr!_FLT_CALLBACK_DATA <address>

// Dump FLT_IO_PARAMETER_BLOCK (I/O parameters):
dt fltmgr!_FLT_IO_PARAMETER_BLOCK <address>

// Dump FLT_RELATED_OBJECTS (filter/volume/instance handles):
dt fltmgr!_FLT_RELATED_OBJECTS <address>

// Enumerate all contexts attached to a FILE_OBJECT:
!fltkd.fileobj <PFILE_OBJECT address>

// Show communication port state and connections:
!fltkd.ports

// Show all filter contexts in the system:
!fltkd.cbdq

// Break on all minifilter callbacks for a specific filter:
bp fltmgr!FltpPassThroughFastIo
```

### 18.2 fltmc — User-Mode Diagnostic Tool (Requires Elevation)

```cmd
:: List all loaded minifilters with their altitudes:
fltmc

:: Per-filter instance details (altitude, flags, volume):
fltmc instances

:: Show all volumes and their filesystem types:
fltmc volumes

:: Manually attach a minifilter to a volume for testing:
fltmc attach <driverletter>: <filtername>

:: Manually detach a minifilter instance:
fltmc detach <driverletter>: <filtername>

:: Load a minifilter driver:
fltmc load <filtername>

:: Unload a minifilter driver:
fltmc unload <filtername>
```

### 18.3 Driver Verifier Settings

Enable these checks for minifilter development:

```cmd
:: Enable standard + I/O verification for your driver:
verifier /flags 0x209BB /driver MyFilter.sys

:: Enable pool tracking to catch context leaks:
verifier /flags 0x20001B /driver MyFilter.sys

:: Check for IRQL violations and spin lock issues:
verifier /flags 0x000B /driver MyFilter.sys
```

---

## 19. Build Environment Setup

### 19.1 Required Components

- **Windows Driver Kit (WDK)** — matching your target OS version
- **Visual Studio** — 2019 or 2022 (with C++ desktop workload + WDK integration)
- **Windows SDK** — matching WDK version

### 19.2 Project Configuration

```xml
<!-- In your .vcxproj — key properties for a minifilter: -->
<ConfigurationType>Driver</ConfigurationType>
<PlatformToolset>WindowsKernelModeDriver10.0</PlatformToolset>

<!-- Required includes: fltKernel.h (kernel), fltuser.h (user-mode tool) -->
<!-- Required libraries: FltMgr.lib (kernel), FltLib.lib (user-mode) -->
```

### 19.3 INF File for Installation

```ini
[Version]
Signature   = "$Windows NT$"
Class       = "ActivityMonitor"
ClassGuid   = {b86dff51-a31e-4bac-b3cf-e8cfe75c9fc2}
Provider    = %ProviderString%
DriverVer   = 04/20/2025,1.0.0.0
CatalogFile = MyFilter.cat

[DestinationDirs]
DefaultDestDir          = 12
MyFilter.DriverFiles    = 12

[DefaultInstall]
CopyFiles = MyFilter.DriverFiles

[DefaultInstall.Services]
AddService = MyFilter,,MyFilter.Service

[DefaultUninstall]
DelFiles   = MyFilter.DriverFiles

[DefaultUninstall.Services]
DelService = MyFilter

[MyFilter.Service]
DisplayName   = %ServiceDescription%
Description   = %ServiceDescription%
ServiceBinary = %12%\MyFilter.sys
ServiceType   = 2   ; SERVICE_FILE_SYSTEM_DRIVER
StartType     = 3   ; SERVICE_DEMAND_START
ErrorControl  = 1   ; SERVICE_ERROR_NORMAL
LoadOrderGroup = "FSFilter Activity Monitor"
AddReg         = MyFilter.AddRegistry

[MyFilter.AddRegistry]
HKR,,"SupportedFeatures",0x00010001,0x3
HKR,"Instances","DefaultInstance",0x00000000,%DefaultInstance%
HKR,"Instances\"%DefaultInstance%,"Altitude",0x00000000,%DefaultAltitude%
HKR,"Instances\"%DefaultInstance%,"Flags",0x00010001,%Flags%

[MyFilter.DriverFiles]
MyFilter.sys

[Strings]
ProviderString     = "MyCompany"
ServiceDescription = "My Filesystem Minifilter"
DefaultInstance    = "MyFilter Instance"
DefaultAltitude    = "360010"
Flags              = "0x0"
```

---

## 20. Support Routines Reference

### 20.1 Object Translation

```c
FltGetFilterFromName(FilterName, &Filter)
FltGetVolumeFromName(VolumeName, &Volume)
FltGetVolumeInstanceFromName(Filter, VolumeName, AltitudeStr, &Instance)
FltGetVolumeFromInstance(Instance, &Volume)
FltGetFilterFromInstance(Instance, &Filter)
FltGetVolumeFromDeviceObject(DeviceObject, &Volume)
FltGetDeviceObject(Volume, &DeviceObject)
FltGetDiskDeviceObject(Volume, &DiskDeviceObject)
```

### 20.2 Volume and Instance Information

```c
FltGetVolumeProperties(Volume, Properties, PropertySize, LengthReturned)
FltIsVolumeWritable(FltObject, IsWritable)
FltQueryVolumeInformation(Instance, IoStatusBlock, FsInformationClass, Buffer, Length)
FltSetVolumeInformation(Instance, IoStatusBlock, FsInformationClass, Buffer, Length)
FltGetInstanceInformation(Instance, InformationClass, Buffer, BufferSize, BytesReturned)
FltGetFilterInformation(Filter, InformationClass, Buffer, BufferSize, BytesReturned)
```

### 20.3 Enumeration

```c
FltEnumerateFilters(FilterList, FilterListSize, NumberFiltersReturned)
FltEnumerateVolumes(Filter, VolumeList, VolumeListSize, NumberVolumesReturned)
FltEnumerateInstances(Volume, Filter, InstanceList, InstanceListSize, NumberInstancesReturned)
FltEnumerateFilterInformation(Index, InformationClass, Buffer, BufferSize, BytesReturned)
FltEnumerateInstanceInformationByFilter(Filter, Index, InformationClass, Buffer, BytesReturned)
FltEnumerateInstanceInformationByVolume(Volume, Index, InformationClass, Buffer, BytesReturned)
FltEnumerateVolumeInformation(Filter, Index, InformationClass, Buffer, BufferSize, BytesReturned)
```

### 20.4 Process Information

```c
FltGetRequestorProcess(CallbackData)     // returns PEPROCESS
FltGetRequestorProcessId(CallbackData)   // returns HANDLE (cast to ULONG_PTR for PID)
FltIsDirectory(FileObject, Instance, IsDirectory)
```

### 20.5 Oplock Support

```c
FltInitializeOplock(&Oplock)
FltUninitializeOplock(&Oplock)
FltOplockFsctrl(&Oplock, CallbackData, OpenCount)
FltCheckOplock(&Oplock, CallbackData, Context, WaitCompletionRoutine, PrePostCallbackDataRoutine)
FltOplockIsFastIoPossible(&Oplock)
FltCurrentBatchOplock(&Oplock)
```

### 20.6 Directory Change Notification

```c
FltNotifyFilterChangeDirectory(
    NotifySync, NotifyList, FsContext, FullDirectoryName,
    WatchTree, IgnoreBuffer, CompletionFilter,
    NotifyCallbackData, TraverseCallback, SubjectContext,
    FilterCallback)
```

### 20.7 Queuing Support

```c
// Allocate a deferred work item for post-callback deferral:
FltAllocateDeferredIoWorkItem()
FltFreeDeferredIoWorkItem(WorkItem)
FltQueueDeferredIoWorkItem(WorkItem, Data, WorkerRoutine, QueueType, Context)

// Generic work queue (not I/O-specific):
FltAllocateGenericWorkItem()
FltFreeGenericWorkItem(WorkItem)
FltQueueGenericWorkItem(WorkItem, Filter, WorkerRoutine, QueueType, Context)
```

---

*API signatures and struct definitions are from the public Windows Driver Kit (WDK) headers and Microsoft Docs (docs.microsoft.com). All code examples are original.*
