# I/O Driver Internals — IRP Lifecycle, Minifilter Framework & WFP Callouts
> Domain: Windows I/O subsystem, minifilter drivers, WFP, kernel driver development
> Load when: Implementing file system minifilters, WFP callout drivers, IOCTL dispatch, IRP handling, or analysing driver pool allocation patterns

## Purpose & Scope
Complete reference for the Windows I/O driver model from IRP allocation through completion, the Filter Manager minifilter framework with context management, IOCTL dispatch patterns, WFP callout registration, and kernel pool allocation strategies for I/O-intensive drivers.

## Key Concepts

**IRP Structure and Lifecycle**
- `IRP` (I/O Request Packet): fixed header + variable-length stack of `IO_STACK_LOCATION` entries (one per driver in the stack).
- Key IRP fields: `IoStatus` (final status + information), `AssociatedIrp.SystemBuffer` (METHOD_BUFFERED I/O), `MdlAddress` (METHOD_DIRECT DMA), `Flags` (IRP_NOCACHE, IRP_PAGING_IO, etc.).
- `IO_STACK_LOCATION` fields: `MajorFunction`, `MinorFunction`, `Parameters` union (varies by major code), `CompletionRoutine`, `DeviceObject`, `FileObject`.

```
IRP lifecycle:
  IoAllocateIrp()              ← allocate from lookaside list
      │
  IoGetCurrentIrpStackLocation() ← get current stack slot
      │
  Driver dispatch routine      ← MajorFunction handler
      │
  IoMarkIrpPending()           ← if returning STATUS_PENDING
      │
  IoCallDriver(lower device)   ← forward down the stack
      │
  CompletionRoutine fires      ← after lower driver completes
      │
  IoCompleteRequest(irp, boost) ← signal completion, free stack
```

**Major Function Codes**

| Code | Meaning | Notes |
|------|---------|-------|
| `IRP_MJ_CREATE` | File/device open | Minifilter pre: inspect path, caller, access mask |
| `IRP_MJ_CLOSE` | Handle closed | Object reference still held |
| `IRP_MJ_READ` / `IRP_MJ_WRITE` | Data I/O | Pre: inspect buffer for exfiltration; Post: inspect written data |
| `IRP_MJ_DEVICE_CONTROL` | IOCTL from user mode | `Parameters.DeviceIoControl.IoControlCode` |
| `IRP_MJ_INTERNAL_DEVICE_CONTROL` | IOCTL from kernel | Driver-to-driver communication |
| `IRP_MJ_QUERY_INFORMATION` | File metadata query | Detect directory enumeration |
| `IRP_MJ_SET_INFORMATION` | Rename/delete/hardlink | `FileRenameInformation` — ransomware detection |
| `IRP_MJ_CLEANUP` | Last handle closed | File unlock; stream context teardown |
| `IRP_MJ_PNP` | Plug-and-play | Device arrival/removal handling |

**Minifilter Framework (FltMgr)**

Registration:
```c
const FLT_OPERATION_REGISTRATION Callbacks[] = {
    { IRP_MJ_CREATE,
      0,
      PreCreateCallback,   // FLT_PREOP_CALLBACK
      PostCreateCallback   // FLT_POSTOP_CALLBACK
    },
    { IRP_MJ_WRITE,
      0,
      PreWriteCallback,
      NULL
    },
    { IRP_MJ_OPERATION_END }
};

const FLT_REGISTRATION FilterRegistration = {
    sizeof(FLT_REGISTRATION),
    FLT_REGISTRATION_VERSION,
    0,                    // Flags
    NULL,                 // ContextRegistration — set if using contexts
    Callbacks,
    DriverUnload,
    InstanceSetup,
    InstanceQueryTeardown,
    InstanceTeardownStart,
    InstanceTeardownComplete,
};

FltRegisterFilter(DriverObject, &FilterRegistration, &gFilterHandle);
FltStartFiltering(gFilterHandle);
```

**Altitude Assignment**
- Altitude is a numeric string assigned by Microsoft that determines callback dispatch order.
- Ranges: 20000–29999 = anti-virus; 320000–329999 = FSFilter Activity Monitor.
- Multiple drivers at different altitudes: higher altitude pre-op runs first; lower altitude post-op runs first.
- Request altitude via `https://www.microsoft.com/en-us/wdsi/filesforsecurity`.

**Pre/Post Operation Return Values**

| Return Value | Meaning |
|-------------|---------|
| `FLT_PREOP_SUCCESS_WITH_CALLBACK` | Pass to next filter; request post-op callback |
| `FLT_PREOP_SUCCESS_NO_CALLBACK` | Pass to next filter; no post-op callback needed |
| `FLT_PREOP_COMPLETE` | Complete IRP now; skip all lower drivers |
| `FLT_PREOP_PENDING` | Pend the operation; call `FltCompletePendedPreOperation` later |
| `FLT_POSTOP_FINISHED_PROCESSING` | Post-op complete |
| `FLT_POSTOP_MORE_PROCESSING_REQUIRED` | Pend post-op to worker thread (required if allocating at DPC level) |

**Context Management**
```c
// Register context types:
const FLT_CONTEXT_REGISTRATION Contexts[] = {
    { FLT_STREAM_CONTEXT,   0, NULL, sizeof(MY_STREAM_CTX), 'xrtS' },
    { FLT_STREAMHANDLE_CONTEXT, 0, NULL, sizeof(MY_SH_CTX), 'xhSx' },
    { FLT_CONTEXT_END }
};

// Attach context to stream:
MY_STREAM_CTX* ctx;
FltAllocateContext(gFilter, FLT_STREAM_CONTEXT, sizeof(MY_STREAM_CTX), PagedPool, &ctx);
FltSetStreamContext(FltObjects->Instance, FltObjects->FileObject,
                   FLT_SET_CONTEXT_KEEP_IF_EXISTS, ctx, NULL);
FltReleaseContext(ctx);

// Retrieve:
FltGetStreamContext(FltObjects->Instance, FltObjects->FileObject, &ctx);
// ... use ctx ...
FltReleaseContext(ctx);
```

**Filter Manager Communication Ports**
```c
// Server (driver) side:
UNICODE_STRING portName = RTL_CONSTANT_STRING(L"\\MyEDRPort");
FltBuildDefaultSecurityDescriptor(&sd, FLT_PORT_ALL_ACCESS);
FltCreateCommunicationPort(gFilter, &gServerPort, &oa,
                           NULL, ConnectNotify, DisconnectNotify,
                           MessageNotify, 1 /*max connections*/);

// Client (user mode) side:
FilterConnectCommunicationPort(L"\\MyEDRPort", 0, NULL, 0, NULL, &hPort);
FilterSendMessage(hPort, &request, sizeof(request), &reply, sizeof(reply), &bytesReturned);
```

**IOCTL Transfer Types**

| Method | Buffer Location | Use Case |
|--------|----------------|---------|
| `METHOD_BUFFERED` | `Irp->AssociatedIrp.SystemBuffer` | Small request/response; kernel copies |
| `METHOD_IN_DIRECT` | `Irp->MdlAddress` | Large input; user buffer pinned by MDL |
| `METHOD_OUT_DIRECT` | `Irp->MdlAddress` | Large output; user buffer pinned by MDL |
| `METHOD_NEITHER` | Raw user pointers — dangerous | Only for same-privilege drivers; validate carefully |

IOCTL code encoding: `CTL_CODE(DeviceType, Function, Method, Access)` — e.g. `CTL_CODE(FILE_DEVICE_UNKNOWN, 0x800, METHOD_BUFFERED, FILE_ANY_ACCESS)`.

**Pool Allocation Patterns for I/O Drivers**
```c
// Single allocation:
PVOID buf = ExAllocatePool2(POOL_FLAG_NON_PAGED_NX, size, 'rEDR');
if (!buf) return STATUS_INSUFFICIENT_RESOURCES;
// ...
ExFreePoolWithTag(buf, 'rEDR');

// Lookaside list for fixed-size hot-path allocations:
LOOKASIDE_LIST_EX g_EventList;
ExInitializeLookasideListEx(&g_EventList, NULL, NULL,
                            NonPagedPoolNx, 0, sizeof(MY_EVENT), 'vEDR', 0);
MY_EVENT* ev = ExAllocateFromLookasideListEx(&g_EventList);
// ... use ev ...
ExFreeToLookasideListEx(&g_EventList, ev);
ExDeleteLookasideListEx(&g_EventList); // in DriverUnload
```

**WFP Callout Registration**
```c
FWPS_CALLOUT callout = {
    .calloutKey        = MY_CALLOUT_GUID,
    .classifyFn        = ClassifyFn,
    .notifyFn          = NotifyFn,
    .flowDeleteFn      = FlowDeleteFn,
};
FwpsCalloutRegister(deviceObject, &callout, &g_CalloutId);

// FWPM layer add (requires FwpmEngineOpen handle):
FWPM_CALLOUT fwpmCallout = {
    .calloutKey  = MY_CALLOUT_GUID,
    .displayData = { L"EDR Callout", L"Connection monitor" },
    .applicableLayer = FWPM_LAYER_ALE_AUTH_CONNECT_V4,
};
FwpmCalloutAdd(engineHandle, &fwpmCallout, NULL, NULL);

// ClassifyFn fires at ALE_AUTH_CONNECT_V4 for every outbound connect:
void ClassifyFn(const FWPS_INCOMING_VALUES* inFixedValues, ...,
                FWPS_CLASSIFY_OUT* classifyOut) {
    UINT32 remoteIp  = inFixedValues->incomingValue[FWPS_FIELD_ALE_AUTH_CONNECT_V4_IP_REMOTE_ADDRESS].value.uint32;
    UINT16 remotePort = inFixedValues->incomingValue[FWPS_FIELD_ALE_AUTH_CONNECT_V4_IP_REMOTE_PORT].value.uint16;
    // Block:
    classifyOut->actionType = FWP_ACTION_BLOCK;
    classifyOut->rights &= ~FWPS_RIGHT_ACTION_WRITE;
}
```

## Heuristics & Design Rules
- Always check `FLT_IS_IRP_OPERATION(Data)` before accessing IRP fields in pre/post-op — not all filter data has an associated IRP.
- Use `FLT_POSTOP_MORE_PROCESSING_REQUIRED` + `FltDoCompletionProcessingWhenSafe` when post-op needs to allocate memory or acquire resources — avoids deadlock at DPC level.
- Attach `FLT_STREAM_CONTEXT` at `IRP_MJ_CREATE` post-op (not pre-op) — only post-op has a valid file object with an assigned stream.
- Use `METHOD_BUFFERED` for IOCTL unless payload exceeds 64 KB — the kernel-copy overhead is acceptable and avoids MDL complexity.
- Always call `FltObjectDereference` after `FltGetVolumeFromInstance` — FltMgr increments refcount on retrieval.

## Critical Warnings / Anti-Patterns
- Never complete an IRP with `IoCompleteRequest` from a minifilter callback — use `FltCompletePendedPreOperation` or return `FLT_PREOP_COMPLETE` with `Data->IoStatus` set.
- Avoid acquiring a mutex in a pre-op callback while also acquiring it in the file system's own path — altitude ordering can cause priority inversion.
- `METHOD_NEITHER` IOCTLs access raw user-mode pointers — always probe with `ProbeForRead`/`ProbeForWrite` inside a `__try/__except` block.
- Do not store IRP stack location pointers after `IoCallDriver` returns — the stack may have been freed.
- WFP `FwpsCalloutRegister` must be called after `IoCreateDevice` — the callout is associated with the device object's IRQL.

## Cross-References
- See also: `kernel-primitives-overview.md` — pool allocation and IRQL constraints underlying IRP dispatch
- See also: `windows-internals.md` — minifilter and WFP architecture overview
- See also: `edr-design-reference.md` — RAII patterns for IRP context and filter objects
- See also: `boot-virtualization-overview.md` — HVCI impact on driver code integrity and pool allocation
