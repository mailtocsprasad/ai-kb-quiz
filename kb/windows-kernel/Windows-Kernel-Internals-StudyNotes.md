# Windows Kernel Internals — Study Notes
## Kernel Objects, Data Structures, and WinDbg Commands

> **Independent study notes** on Windows kernel internals, compiled for personal learning and professional reference.
>
> **Sources:** All structure layouts are observable from Microsoft's public debug symbols
> (Microsoft Symbol Server — `srv*https://msdl.microsoft.com/download/symbols`).
> All WinDbg commands are documented in
> [Microsoft's WinDbg reference](https://learn.microsoft.com/en-us/windows-hardware/drivers/debugger/).
> Conceptual background draws on publicly available Microsoft documentation:
> [Windows Driver Kit (WDK)](https://learn.microsoft.com/en-us/windows-hardware/drivers/),
> [learn.microsoft.com/windows-hardware](https://learn.microsoft.com/en-us/windows-hardware/),
> and the Windows SDK headers (`ntdef.h`, `wdm.h`, `ntifs.h`).
>
> Structure field names and offsets are verifiable by running `dt nt!_STRUCTURENAME` in
> WinDbg with public symbols loaded against any matching Windows build.
>
> **License:** These notes are released under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).
> You are free to share and adapt with attribution.

---

## Table of Contents

1. [WinDbg Debugger Basics](#1-windbg-debugger-basics)
2. [Object Manager and Kernel Objects](#2-object-manager-and-kernel-objects)
3. [Process Internals — EPROCESS / KPROCESS / PEB](#3-process-internals--eprocess--kprocess--peb)
4. [Thread Internals — ETHREAD / KTHREAD / TEB](#4-thread-internals--ethread--kthread--teb)
5. [Memory Management Structures](#5-memory-management-structures)
6. [Security Structures — TOKEN / SIDs / ACLs](#6-security-structures--token--sids--acls)
7. [System Mechanisms — IRQL / IDT / DPC / APC](#7-system-mechanisms--irql--idt--dpc--apc)
8. [Synchronization Objects](#8-synchronization-objects)
9. [Handle Tables and Object Namespaces](#9-handle-tables-and-object-namespaces)
10. [Jobs and Silos](#10-jobs-and-silos)
11. [Protected Processes and PPL](#11-protected-processes-and-ppl)
12. [Scenario Reference — Quick Command Lookup](#12-scenario-reference--quick-command-lookup)

---

## 1. WinDbg Debugger Basics

### Key Debugger Pseudo-registers

| Pseudo-register | Meaning |
|---|---|
| `@$pcr` | Current CPU's `_KPCR` (Processor Control Region) |
| `@$prcb` | Current CPU's `_KPRCB` extension |
| `@$proc` | Current implicit process (`_EPROCESS *`) |
| `@$thread` | Current implicit thread (`_ETHREAD *`) |
| `@$teb` | Thread Environment Block of the current user-mode thread |
| `@$peb` | Process Environment Block of the current process |

### Changing Process/Thread Context

```
; Switch to a specific process (loads user-mode symbols)
lkd> .process /r /P <eprocess_addr>

; Switch to a specific thread (and by extension its process)
lkd> .thread /p <ethread_addr>

; Or combined, loads user symbols:
lkd> .thread /p /r <ethread_addr>
```

After switching context, the implicit process and TEB are updated and user-mode commands (`!teb`, `!peb`, `lm`) work against the selected process.

### Useful Pattern: `dx` Debugger Data Model

The `dx` command exposes structured, LINQ-queryable objects:

```
; Enumerate all processes
dx @$cursession.Processes

; Enumerate processes with name filter
dx @$cursession.Processes.Where(p => p.Name == "lsass.exe")

; Walk threads of a process
dx @$cursession.Processes["notepad.exe"].Threads

; Access EPROCESS fields via DDM
dx (nt!_EPROCESS*)0xffffa...
```

### Reading MSR registers

```
lkd> rdmsr c0000101   ; GS_BASE (kernel) → KPCR address
lkd> rdmsr c0000102   ; KERNEL_GS_BASE → swapgs alternate
```

---

## 2. Object Manager and Kernel Objects

### Object Header — `_OBJECT_HEADER`

Every kernel object is preceded by `_OBJECT_HEADER`. The body of the object follows immediately after this header.

```
lkd> dt nt!_OBJECT_HEADER <addr>
   +0x000 PointerCount  : LONG64      ; total references
   +0x008 HandleCount   : LONG64      ; open handles
   +0x010 Lock          : _EX_PUSH_LOCK
   +0x018 TypeIndex     : UCHAR       ; index into ObTypeIndexTable
   +0x019 TraceFlags    : UCHAR
   +0x01a InfoMask      : UCHAR       ; optional header bitmask
   +0x01b Flags         : UCHAR
```

**InfoMask bit definitions** (optional headers preceding `_OBJECT_HEADER`):

| Bit | Optional Header | Size |
|---|---|---|
| 0x01 | `_OBJECT_HEADER_CREATOR_INFO` | CreatorUniqueProcess, ObjectListEntry |
| 0x02 | `_OBJECT_HEADER_NAME_INFO` | Name, Directory, ReferenceCount |
| 0x04 | `_OBJECT_HEADER_HANDLE_INFO` | HandleCountDatabase |
| 0x08 | `_OBJECT_HEADER_QUOTA_INFO` | PagedPoolCharge, NonPagedPoolCharge |
| 0x10 | `_OBJECT_HEADER_PROCESS_INFO` | ExclusiveProcess |
| 0x20 | `_OBJECT_HEADER_AUDIT_INFO` | SecurityDescriptor pointer |

Derive body address: `body = header_addr + sizeof(_OBJECT_HEADER)` or use `CONTAINING_RECORD` macro pattern.

**Get object header from a body pointer:**
```
lkd> !object <obj_body_addr>
Object: ffffXX Type: (ffffYY) Process
ObjectHeader: ffffZZ (new version) HandleCount: 15 PointerCount: 504

lkd> dt nt!_object_header ffffZZ
```

### Object Type — `_OBJECT_TYPE`

Every object belongs to a type. Types are stored in `nt!ObTypeIndexTable[]`.

```
lkd> dt nt!_OBJECT_TYPE <type_addr>
   +0x000 TypeList      : _LIST_ENTRY
   +0x010 Name          : _UNICODE_STRING
   +0x028 DefaultObject : Ptr64 Void
   +0x030 Index         : UCHAR        ; index in ObTypeIndexTable
   +0x068 TypeInfo      : _OBJECT_TYPE_INITIALIZER
```

```
; List all registered object types
dx Debugger.Utility.Collections.FromListEntry(*(nt!_LIST_ENTRY*)&nt!ObpObjectTypes, "nt!_OBJECT_TYPE", "TypeList")

; Or via the old method
lkd> dt nt!ObTypeIndexTable
```

### WinObj namespace — Walking the Object Directory

```
; Enumerate objects in a directory (e.g., \Device)
lkd> !object \Device

; Open named handle object
lkd> !object \GLOBAL??\C:

; Walk sessions namespace
lkd> !object \Sessions\1\BaseNamedObjects
```

### Object handle and reference counts

```
; Show open handles globally (all processes)
lkd> !handle 0 f

; Show handles of a specific process
lkd> .process /P <eprocess>
lkd> !handle 0 3   ; brief format
lkd> !handle 0 7   ; include object type

; Show details on a specific handle value
lkd> !handle <handle_value> f <eprocess>
```

---

## 3. Process Internals — EPROCESS / KPROCESS / PEB

### `_EPROCESS` (Executive Process Object)

The executive-level process object managed by the Process Manager. Contains all OS-level process information.

```
lkd> dt nt!_EPROCESS
   +0x000 Pcb              : _KPROCESS       ; kernel control block (embedded)
   +0x2d8 ProcessLock      : _EX_PUSH_LOCK
   +0x2e8 UniqueProcessId  : Ptr64 Void      ; PID
   +0x2f0 ActiveProcessLinks : _LIST_ENTRY   ; global process list
   +0x3a8 Win32Process     : Ptr64 Void      ; W32PROCESS (Win32k)
   +0x3b0 Job              : Ptr64 _EJOB
   +0x418 ObjectTable      : Ptr64 _HANDLE_TABLE
   +0x420 DebugPort        : Ptr64 Void
   +0x428 WoW64Process     : Ptr64 _EWOW64PROCESS
   +0x758 SharedCommitCharge : Uint8B
   +0x768 SharedCommitLinks : _LIST_ENTRY
```

**Key EPROCESS fields for EDR:**

| Field | Offset (x64) | Purpose |
|---|---|---|
| `Pcb` | +0x000 | Embedded `_KPROCESS` |
| `UniqueProcessId` | +0x2e8 | PID |
| `ActiveProcessLinks` | +0x2f0 | Process doubly-linked list |
| `ObjectTable` | +0x418 | Handle table pointer |
| `DebugPort` | +0x420 | Non-zero if debugged |
| `Job` | +0x3b0 | Associated job object |
| `Token` | (varies) | Primary access token (via `!process`) |
| `Protection` | varies | `_PS_PROTECTION` byte for PPL/PP |
| `SecurePid` | `Pcb+0x2d0` | Non-zero for VTL1/trustlet processes |
| `ImageFileName` | varies | 15-byte null-padded image name |

**Displaying a process:**
```
; Show all processes (brief)
lkd> !process 0 0

; Show all processes matching a name
lkd> !process 0 0 lsass.exe

; Show process with thread list
lkd> !process 0 2

; Show full details of a single process by address
lkd> !process <eprocess_addr> 7

; Display raw EPROCESS structure
lkd> dt nt!_EPROCESS <eprocess_addr>

; Walk ActiveProcessLinks manually
dx Debugger.Utility.Collections.FromListEntry(*(nt!_LIST_ENTRY*)&nt!PsActiveProcessHead, "nt!_EPROCESS", "ActiveProcessLinks")
```

### `_KPROCESS` (Kernel Process Block, embedded in `_EPROCESS`)

Holds scheduling and address-space data used directly by the kernel dispatcher.

```
lkd> dt nt!_KPROCESS
   +0x000 Header           : _DISPATCHER_HEADER  ; waitability
   +0x018 ProfileListHead  : _LIST_ENTRY
   +0x028 DirectoryTableBase : Uint8B             ; CR3 / page directory PA
   +0x030 ThreadListHead   : _LIST_ENTRY
   +0x040 ProcessLock      : Uint4B
   +0x048 CycleTime        : Uint8B
   +0x2d0 SecurePid        : ULONG_PTR           ; trustlet handle in VTL1
```

### Process Environment Block — `_PEB`

Lives in user-mode address space. Stores image loader state, heap info, and user-mode process settings.

```
; Dump PEB (must set process context first)
lkd> .process /P <eprocess_addr>
lkd> !peb <peb_addr>

; Or combined:
lkd> .process /P <eprocess_addr> ; !peb <peb_addr>
```

Key PEB fields:

| Field | Meaning |
|---|---|
| `ImageBaseAddress` | Mapped base of the primary executable |
| `Ldr` | Pointer to `_PEB_LDR_DATA` (module list) |
| `ProcessParameters` | RTL_USER_PROCESS_PARAMETERS (command line, env) |
| `BeingDebugged` | 1 if under a debugger |
| `NtGlobalFlag` | Global flag settings |
| `Heap` / `ProcessHeaps` | Default and additional process heaps |

### Loader Module Database — `_LDR_DATA_TABLE_ENTRY`

The image loader maintains three doubly-linked lists of loaded DLLs inside `PEB.Ldr`:

```
; Show PEB and module list
lkd> !peb

; Manually walk loader list
lkd> !list -x "dt ntdll!_LDR_DATA_TABLE_ENTRY" @@C++(&@$peb->Ldr->InLoadOrderModuleList)
```

Key `LDR_DATA_TABLE_ENTRY` fields:

| Field | Meaning |
|---|---|
| `DllBase` | Load base address |
| `FullDllName` | Full path (`_UNICODE_STRING`) |
| `BaseDllName` | Module name only |
| `EntryPoint` | DllMain address |
| `Flags` | Loader state flags (see table below) |

**Loader flags (selected):**

| Flag | Value | Meaning |
|---|---|---|
| Image DLL | 0x4 | Is a DLL, not data or EXE |
| In Legacy Lists | 0x40 | In linked list (InLoadOrder, etc.) |
| Load In Progress | 0x800 | Currently being loaded |
| Entry Processed | 0x2000 | DllMain has been called |
| Process Attach Called | 0x20000 | DLL_PROCESS_ATTACH sent |

### Displaying process context (useful patterns)

```
; Find process by name
lkd> !process 0 0 notepad.exe

; Use process address to set context and explore user space
lkd> .process /r /P ffffe001xxxxxxxx

; Check if process is in a job
lkd> !process 0 1 notepad.exe
; Look for "Job" field — non-zero means assigned to a job

; Dump job object
lkd> !job <ejob_addr>
lkd> dt nt!_EJOB <ejob_addr>

; CSR_PROCESS (Csrss subsystem structure)
lkd> .process /r /P <csrss_eprocess>
lkd> dt csrss!_csr_process
```

---

## 4. Thread Internals — ETHREAD / KTHREAD / TEB

### `_ETHREAD` (Executive Thread Object)

```
lkd> dt nt!_ETHREAD
   +0x000 Tcb            : _KTHREAD         ; kernel thread block (embedded)
   +0x5d8 CreateTime     : _LARGE_INTEGER
   +0x5e0 ExitTime       : _LARGE_INTEGER
   +0x7a0 EnergyValues   : Ptr64 _THREAD_ENERGY_VALUES
   +0x7b8 Silo           : Ptr64 _EJOB      ; server silo association
```

### `_KTHREAD` (Kernel Thread Control Block, embedded at ETHREAD+0x000)

```
lkd> dt nt!_KTHREAD
   +0x000 Header         : _DISPATCHER_HEADER   ; object header (waitability)
   +0x018 SListFaultAddress : Ptr64 Void
   +0x028 InitialStack   : Ptr64 Void
   +0x030 StackLimit     : Ptr64 Void
   +0x038 StackBase      : Ptr64 Void
   +0x040 ThreadLock     : Uint8B
   +0x048 CycleTime      : Uint8B
   +0x050 CurrentRunTime : Uint4B
   +0x31c SecureThreadCookie : Uint4B         ; VTL1 thread index
   +0x5a0 ReadOperationCount  : Int8B
   +0x5a8 WriteOperationCount : Int8B
   +0x5d0 QueuedScb      : Ptr64 _KSCB
```

### Thread States (KTHREAD.State)

| Value | State | Meaning |
|---|---|---|
| 0 | Initialized | Just created, not yet scheduled |
| 1 | Ready | Waiting to run; in a ready queue |
| 2 | Running | Executing on a processor |
| 3 | Standby | Selected to run next on a specific CPU |
| 4 | Terminated | Finished executing |
| 5 | Waiting | Blocked on an object (user or kernel) |
| 6 | Transition | Ready but kernel stack paged out |
| 7 | DeferredReady | Selected but per-CPU lock not yet released |

### Thread Priority Levels

Windows uses 32 priority levels (0–31):
- **0**: Zero Page Thread (system reserved)
- **1–15**: Variable (user-mode range, subject to boosts)
- **16–31**: Real-time (no boosts applied)

Priority class → base priority mappings (user-mode):

| API Priority Class | Base Priority |
|---|---|
| IDLE_PRIORITY_CLASS | 4 |
| BELOW_NORMAL_PRIORITY_CLASS | 6 |
| NORMAL_PRIORITY_CLASS | 8 |
| ABOVE_NORMAL_PRIORITY_CLASS | 10 |
| HIGH_PRIORITY_CLASS | 13 |
| REALTIME_PRIORITY_CLASS | 24 |

### WinDbg Commands for Threads

```
; List all threads of a process (flag 2 = brief list)
lkd> !process <eprocess> 2

; Full details of a specific thread
lkd> !thread <ethread_addr>

; Switch debugger context to a specific thread
lkd> .thread /p <ethread_addr>

; Display raw ETHREAD structure
lkd> dt nt!_ETHREAD <ethread_addr>

; Display KTHREAD
lkd> dt nt!_KTHREAD <ethread_addr>

; Secure thread cookie (trustlet)
lkd> dt nt!_ETHREAD <addr> Tcb.SecureThreadCookie
```

### Thread Environment Block — `_TEB`

Lives in user-mode process address space. Contains user-mode thread state.

```
; From user-mode debugger (attached to process)
0:000> !teb
0:000> dt ntdll!_TEB @$teb

; From kernel debugger (must set thread/process context first)
lkd> .thread /p <ethread>
lkd> !teb <teb_addr>        ; teb addr is shown in !process output
```

Key TEB fields:

| Field | Meaning |
|---|---|
| `NtTib.ExceptionList` | SEH chain root (32-bit only) |
| `NtTib.StackBase` / `StackLimit` | Stack bounds |
| `Self` | Self-pointer (useful for verification) |
| `ClientId.UniqueProcess` / `UniqueThread` | PID / TID |
| `LastErrorValue` | Win32 last error (GetLastError result) |
| `LastStatusValue` | NT status code |
| `Tls Storage` | TLS array pointer |
| `PEB Address` | Pointer back to the PEB |

### CSR_THREAD

```
; Set context to a Csrss process first
lkd> .process /r /P <csrss_eprocess>
lkd> dt csrss!_csr_thread
   +0x000 CreateTime      : _LARGE_INTEGER
   +0x008 Link            : _LIST_ENTRY
   +0x028 ClientId        : _CLIENT_ID
   +0x038 Process         : Ptr64 _CSR_PROCESS
   +0x050 ImpersonateCount : Uint4B
```

### Thread Stack Analysis

```
; Stack trace — user mode debugger
0:000> k           ; current thread
0:000> ~2k         ; thread #2's stack
0:000> ~ns         ; switch to thread n, then k

; Stack trace — kernel debugger (after .thread /p /r)
lkd> k             ; call stack
lkd> kv            ; with frame pointers
lkd> kn            ; with frame numbers
lkd> kb            ; with first 3 arguments

; All stacks in a process
lkd> !process <eprocess> 7    ; full details including stacks
```

---

## 5. Memory Management Structures

### Virtual Address Layout (x64 Windows 10)

| Region | Range | Description |
|---|---|---|
| User space | 0x0000000000000000 – 0x00007FFFFFFFFFFF | Per-process private address space (128 TB) |
| System range | 0xFFFF800000000000 – 0xFFFFFFFFFFFFFFFF | Kernel virtual address space |
| PTE space | varies | Self-referencing PML4 maps the page tables |
| Kernel image | ~0xFFFFF80000000000 | ntoskrnl.exe and core modules |

### Page Table Entry — `_MMPTE`

On x64, each PTE is 8 bytes. The hardware PTE has these key bits:

| Bit | Name | Meaning |
|---|---|---|
| 0 | Valid | Page is present in physical memory |
| 1 | Write | Page is writable (hardware write bit) |
| 2 | Owner | User-mode accessible (vs. kernel-only) |
| 3 | WriteThrough | Write-through / write-combined |
| 4 | CacheDisable | Uncached |
| 5 | Accessed | Set by MMU on first access |
| 6 | Dirty | Set by MMU on first write |
| 7 | LargePage | PDE maps a 2 MB page |
| 8 | Global | TLB entry not flushed on CR3 load |
| 11 | SoftwareWsBit | Managed by memory manager |
| 63 | NoExecute | NX bit (DEP enforcement) |

```
; Examine PTEs for a virtual address
lkd> !pte <virtual_addr>
    VA <va>
    PDE at <pde_va>     PTE at <pte_va>
    contains <pde_val>  contains <pte_val>
    pfn XXXXX  ---DA--UWEV  pfn YYYYY  ---DA--UW-V

; Decode PFN flags in output:
; D=Dirty, A=Accessed, U=User, W=Writable, E=Executable, V=Valid, C=CopyOnWrite
```

### Virtual Address Descriptor — VAD Tree

Each process has a balanced binary tree of VADs describing its virtual address allocations. The root is stored in `EPROCESS.VadRoot`.

```
; Show VAD tree for current process
lkd> !vad

; Show VAD for a specific process
lkd> !process 0 1 notepad.exe   ; get VadRoot address
lkd> !vad <vad_root_addr>

; Verbose VAD dump
lkd> !vad <vad_root_addr> 1

; Using dx for VAD inspection
lkd> dx ((nt!_EPROCESS*)@$proc)->VadRoot
```

VAD types and their meanings:

| VAD Type | Meaning |
|---|---|
| `VadNone` | Private allocation (VirtualAlloc) |
| `VadDevicePhysicalMemory` | Device-mapped physical memory |
| `VadImageMap` | PE image mapped from file |
| `VadAwe` | AWE (Address Windowing Extensions) |
| `VadWriteWatch` | Write-watch region |
| `VadLargePages` | Large page allocation |
| `VadRotatePhysical` | Rotated physical memory |
| `VadLargePageSection` | Section backed by large pages |

### Page Frame Number Database — PFN Database

The PFN database maps physical page frames to their type and state. Each entry is `_MMPFN`.

```
; Show physical memory / PFN information
lkd> !pfn <pfn_number>

; Show all page lists (working set, standby, free, etc.)
lkd> !vm          ; overall virtual memory summary
lkd> !vm 1        ; include page file info

; Query system PTE usage
lkd> !sysptes
```

### Address Translation Walkthrough

```
; Translate a virtual address to physical
lkd> !pte <va>         ; shows PDE and PTE physical addresses
lkd> !dd <physical_addr>    ; read physical memory directly
lkd> !dq <physical_addr>    ; read as quad-words

; Example: compare virtual and physical views
lkd> dd <va> L10
lkd> !dd <phys_addr> L10   ; should match
```

### Memory Analysis Commands

```
; Virtual address space summary for a process
lkd> !process <eprocess> 1    ; shows VirtualSize, WorkingSet, VadRoot

; Heap analysis
lkd> !heap                    ; all heaps in current process
lkd> !heap -s                 ; heap segments summary
lkd> !heap -i <heap_addr>     ; heap info
lkd> !heap <heap_addr> 3      ; detail including free blocks

; Working set list
lkd> !wsle <eprocess>

; Working set sizes via Performance counters  
; (Use !process 0 1 <name> and check "Working Set Sizes")

; ASLR check — calculate Ntdll load address
lkd> dt nt!_mi_system_information sections.imagebias <MiState_addr>
; Result: 0x78000000 - (ImageBias + NtdllSizeIn64KBChunks) * 0x10000

; Check CFG bitmap regions in a process
0:000> !address            ; shows [CFG Bitmap] regions

; System virtual address usage
lkd> dt nt!_mi_visible_state poi(nt!MiVisibleState)
```

### Pool Memory

Non-paged pool and paged pool are the kernel's primary memory allocators.

```
; Pool tag analysis
lkd> !pool <addr>          ; show pool block at address
lkd> !poolused             ; pool tag statistics (slow)
lkd> !poolused 2           ; sorted by non-paged pool
lkd> !poolused 4           ; sorted by paged pool

; Find pool allocations by tag
lkd> !poolfind <tag>

; Pool leak analysis
lkd> !poolused /t <tag>
```

Pool header structure (`_POOL_HEADER`):
```
lkd> dt nt!_POOL_HEADER <addr>
   +0x000 PreviousSize  : 9-bit (pages × 8)
   +0x000 PoolIndex     : 7-bit
   +0x000 BlockSize     : 9-bit  
   +0x000 PoolType      : 7-bit (0=NonPaged, 1=Paged, etc.)
   +0x004 PoolTag       : Uint4B (4 ASCII chars)
   +0x008 ProcessBilled : Ptr64 _EPROCESS (if quota-charged)
```

---

## 6. Security Structures — TOKEN / SIDs / ACLs

### Access Token — `_TOKEN`

Every process and thread (optionally) carries a security context in a token. Tokens identify user account, group memberships, privileges, and integrity level.

```
; Show token structure layout
lkd> dt nt!_token

   +0x000 TokenSource     : _TOKEN_SOURCE
   +0x010 TokenId         : _LUID
   +0x018 AuthenticationId : _LUID
   +0x020 ParentTokenId   : _LUID
   +0x028 ExpirationTime  : _LARGE_INTEGER
   +0x030 TokenLock       : Ptr64 _ERESOURCE
   +0x040 Privileges      : _SEP_TOKEN_PRIVILEGES
   +0x058 AuditPolicy     : _SEP_AUDIT_POLICY
   +0x078 SessionId       : Uint4B
   +0x07c UserAndGroupCount : Uint4B
   +0x080 RestrictedSidCount : Uint4B
   +0x098 UserAndGroups   : Ptr64 _SID_AND_ATTRIBUTES
   +0x0a0 RestrictedSids  : Ptr64 _SID_AND_ATTRIBUTES
   +0x0b8 DefaultDacl     : Ptr64 _ACL
   +0x0c0 TokenType       : _TOKEN_TYPE    ; Primary (1) or Impersonation (2)
```

**Getting a process token:**
```
; Token address shown in !process output
lkd> !process 0 1 explorer.exe
; ... Token  ffffcd82c72fc060

; Detailed token view
lkd> !token ffffcd82c72fc060

; Raw token structure
lkd> dt nt!_token ffffcd82c72fc060
```

### Token Types

| Type | Value | Description |
|---|---|---|
| Primary | 1 | Process-level token (identity of the process) |
| Impersonation | 2 | Thread-level temporary token (server impersonating client) |

**Impersonation levels** (`_SECURITY_IMPERSONATION_LEVEL`):

| Level | Value | Description |
|---|---|---|
| `SecurityAnonymous` | 0 | Server cannot identify or impersonate |
| `SecurityIdentification` | 1 | Server can identify but not impersonate |
| `SecurityImpersonation` | 2 | Server can impersonate locally |
| `SecurityDelegation` | 3 | Server can impersonate locally and remotely |

### Security Identifiers — SIDs

SIDs uniquely identify accounts, groups, and computers. Format: `S-revision-authority-sub1-sub2-...-RID`

Well-known SIDs:

| SID | Name | Use |
|---|---|---|
| S-1-0-0 | Nobody | Unknown SID |
| S-1-1-0 | Everyone | All authenticated users |
| S-1-5-18 | Local System | System account |
| S-1-5-19 | Local Service | Local service account |
| S-1-5-20 | Network Service | Network service account |
| S-1-16-0x1000 | Low Integrity | AppContainer/Protected IE |
| S-1-16-0x2000 | Medium Integrity | Normal user processes |
| S-1-16-0x3000 | High Integrity | Elevated admin processes |
| S-1-16-0x4000 | System Integrity | Services, system processes |
| S-1-15-2-... | AppContainer SID | UWP package identity |

### Integrity Levels (Mandatory Integrity Control)

Integrity level SIDs are stored as group SIDs in the token. They enforce Mandatory Integrity Control (MIC) — lower-integrity processes cannot write to higher-integrity objects (No-Write-Up policy).

```
; Check integrity level of a process token
lkd> !token <token_addr>   ; look for "Mandatory Label"

; From user-mode (if available)
; Process Explorer → Security tab → "Mandatory Label"
```

Mandatory policies:

| Policy | Default On | Effect |
|---|---|---|
| No-Write-Up | All objects | Blocks write from lower-integrity callers |
| No-Read-Up | Process objects | Prevents process memory reads across integrity |
| No-Execute-Up | COM classes | Prevents COM activation from lower integrity |

### Security Descriptors

Every securable object has a security descriptor containing Owner SID, Group SID, DACL, and SACL.

```
; Find security descriptor via object header
lkd> !object <eprocess_addr>
; → ObjectHeader: ffffZZ

lkd> dt nt!_object_header ffffZZ
; → SecurityDescriptor pointer (last 4 bits are flags, mask with ~0xF)

; Use !sd to dump a security descriptor
lkd> !sd <security_descriptor_addr>

; View access checks
lkd> !token <token>     ; to see token SIDs / privileges
```

### Privileges

Token privileges control what privileged operations a process can perform.

Important privileges for EDR:

| Privilege | Purpose |
|---|---|
| `SeDebugPrivilege` | Open any process for any access (bypasses DACL for processes) |
| `SeLoadDriverPrivilege` | Load/unload kernel drivers |
| `SeTcbPrivilege` | Act as part of the OS |
| `SeImpersonatePrivilege` | Impersonate any logged-on user |
| `SeAssignPrimaryTokenPrivilege` | Replace process token |
| `SeBackupPrivilege` | Read files/registry ignoring DACLs |
| `SeRestorePrivilege` | Write files/registry ignoring DACLs |
| `SeTakeOwnershipPrivilege` | Take ownership of any object |
| `SeCreateTokenPrivilege` | Create tokens |

```
; Check privileges in a token
lkd> !token <token_addr>
; Look for "Enabled Privileges" section in output

; Or via Process Explorer → Security tab → Privileges section
```

### Trust Level SIDs (Protected Process / PPL)

PPL/PP processes carry a TrustLevelSid in their primary token. This SID encodes the Protection level and Signer.

```
; Find trustlet processes
lkd> !for_each_process .if @@(((nt!_EPROCESS*)${@#Process})->Pcb.SecurePid) {
    .printf "Trustlet: %ma (%p)\n", @@(((nt!_EPROCESS*)${@#Process})->ImageFileName),
    @#Process }

; Examine secure PID
lkd> dt nt!_EPROCESS <addr> Pcb.SecurePid

; Show token with trust level
lkd> !token <token_addr>
; Look for: "TrustLevelSid: S-1-19-..." in output
```

---

## 7. System Mechanisms — IRQL / IDT / DPC / APC

### IRQL (Interrupt Request Level)

Windows uses 16 IRQL levels (0–15 on x86/x64). Higher IRQL masks lower-priority interrupts.

| IRQL | Name | Used By |
|---|---|---|
| 0 | PASSIVE_LEVEL | Normal thread execution |
| 1 | APC_LEVEL | APC delivery, page faults allowed |
| 2 | DISPATCH_LEVEL | DPC execution, no page faults |
| 3–11 | Device IRQLs | Hardware interrupt service routines |
| 13 | CLOCK_LEVEL | Timer interrupt handler |
| 14 | IPI_LEVEL | Interprocessor interrupt |
| 15 | HIGH_LEVEL | Bug checks, debugger |

```
; Check current IRQL
lkd> !irql

; IRQL stored in PRCB
lkd> dt nt!_KPRCB <prcb_addr> Irql
lkd> dx @$prcb->DebuggerSavedIRQL
```

### Interrupt Descriptor Table (IDT)

The IDT maps interrupt vectors (0x00–0xFF) to handler routines.

```
; Dump entire IDT
lkd> !idt

; Example output:
; 00: fffff802...  nt!KiDivideErrorFault
; 0e: fffff802...  nt!KiPageFault
; 2f: fffff802...  nt!KiApcInterrupt        (APC software interrupt)
; 30: fffff802...  nt!KiDpcInterrupt        (DPC software interrupt)

; Examine a specific IDT entry
lkd> dx @$pcr->IdtBase[0x0e]     ; page fault handler
lkd> dx @$pcr->IdtBase[2].IstIndex   ; IST stack index for NMI

; x64 GDT dump
lkd> dg 10 50      ; kernel CS, DS, user CS, user DS, compat CS, TEB

; Task State Segment
lkd> dx @$pcr->TssBase           ; TSS structure
lkd> dx @$pcr->TssBase->Ist      ; Interrupt Stack Table (IST)
```

Standard x64 IDT exceptions:

| Vector | Handler | Fault Type |
|---|---|---|
| 0x00 | `KiDivideErrorFault` | Divide by zero |
| 0x01 | `KiDebugTrapOrFault` | Single-step / debug |
| 0x02 | `KiNmiInterrupt` | Non-maskable interrupt |
| 0x03 | `KiBreakpointTrap` | INT3 breakpoint |
| 0x06 | `KiInvalidOpcodeFault` | Undefined opcode |
| 0x08 | `KiDoubleFaultAbort` | Double fault (IST stack) |
| 0x0d | `KiGeneralProtectionFault` | GPF |
| 0x0e | `KiPageFault` | Page fault |
| 0x2f | `KiApcInterrupt` | Software APC interrupt |
| 0x30 | `KiDpcInterrupt` | Software DPC interrupt |

### Deferred Procedure Calls (DPCs)

DPCs run at DISPATCH_LEVEL (IRQL 2). Used for deferred work from ISRs, timers, and system operations.

```
; View DPC queue depth
lkd> dx new { QueuedDpcCount = @$prcb->DpcData[0].DpcCount + @$prcb->DpcData[1].DpcCount, ExecutedDpcCount = ((nt!_ISRDPCSTATS*)@$prcb->IsrDpcStats)->DpcCount },d

; View KDPC structure
lkd> dt nt!_KDPC <addr>
   +0x000 Type           : 19 (DPC)
   +0x002 Importance     : LowImportance / MediumImportance / HighImportance
   +0x008 DpcListEntry   : _LIST_ENTRY
   +0x018 DeferredRoutine : Ptr64 void   ; the DPC routine
   +0x020 DeferredContext : Ptr64 Void   ; context passed to routine
   +0x028 SystemArgument1 : Ptr64 Void
   +0x030 SystemArgument2 : Ptr64 Void
```

### Asynchronous Procedure Calls (APCs)

APCs run at APC_LEVEL (IRQL 1) for kernel APCs, or at PASSIVE_LEVEL for user APCs. Used for async I/O completion, thread alerts, and injection techniques.

```
; View APC queue on a thread
lkd> dt nt!_KTHREAD <addr> ApcState
; ApcState.ApcListHead[0] = kernel APC queue
; ApcState.ApcListHead[1] = user APC queue

; KAPC structure
lkd> dt nt!_KAPC <addr>
   +0x000 Type            : UCHAR (18)
   +0x008 Thread          : Ptr64 _KTHREAD
   +0x010 ApcListEntry    : _LIST_ENTRY
   +0x020 KernelRoutine   : Ptr64           ; runs at IRQL=1
   +0x028 RundownRoutine  : Ptr64           ; runs at IRQL=1 on cancel
   +0x030 NormalRoutine   : Ptr64           ; user-mode routine (NULL for kernel APC)
   +0x038 NormalContext   : Ptr64 Void
   +0x040 SystemArgument1 : Ptr64 Void
   +0x048 SystemArgument2 : Ptr64 Void
   +0x050 ApcStateIndex   : CHAR
   +0x051 ApcMode         : CHAR            ; KernelMode or UserMode
   +0x052 Inserted        : BOOLEAN
```

### Interrupt Objects — `_KINTERRUPT`

```
; View interrupt registered for a device
lkd> !idt        ; find ISR (e.g., i8042prt!I8042KeyboardInterruptService)

; Inspect the interrupt object
lkd> dt nt!_KINTERRUPT <kinterrupt_addr>
   +0x000 Type            : 22 (KINTERRUPT)
   +0x018 ServiceRoutine  : Ptr64       ; ISR function pointer
   +0x020 MessageServiceRoutine : Ptr64 ; MSI ISR (if applicable)
   +0x058 Vector          : Uint4B      ; IDT vector
   +0x05c Irql            : UCHAR       ; IRQL at which ISR runs
   +0x050 DispatchAddress : Ptr64       ; KiInterruptDispatch
   +0x05f Connected       : BOOLEAN
   +0x060 Number          : Uint4B      ; processor number

; PIC status (legacy compatibility)
lkd> !pic

; APIC status (per-processor)
lkd> !apic

; I/O APIC routing table
lkd> !ioapic
```

---

## 8. Synchronization Objects

All kernel synchronization primitives inherit from `_DISPATCHER_HEADER` — the same `Header` field that makes `_KPROCESS` and `_KTHREAD` waitable objects.

```
lkd> dt nt!_DISPATCHER_HEADER
   +0x000 Type     : UCHAR    ; object type code
   +0x002 Signalling : BOOLEAN
   +0x003 TimerMiscFlags : UCHAR
   +0x000 Lock     : LONG (union)
   +0x004 SignalState : LONG  ; current signal state
   +0x008 WaitListHead : _LIST_ENTRY   ; threads waiting on this object
```

**Dispatcher object type codes:**

| Type | Value | Object |
|---|---|---|
| EventNotificationObject | 0 | Notification event |
| EventSynchronizationObject | 1 | Synchronization event |
| MutantObject | 2 | Mutex (KMUTANT) |
| ProcessObject | 3 | `_KPROCESS` |
| QueueObject | 4 | I/O completion queue |
| SemaphoreObject | 5 | Semaphore |
| ThreadObject | 6 | `_KTHREAD` |
| GateObject | 7 | Gate (non-exported, Windows internal) |
| TimerNotificationObject | 8 | Notification timer |
| TimerSynchronizationObject | 9 | Synchronization timer |

### Events

```
; View event object
lkd> dt nt!_KEVENT <addr>
   +0x000 Header : _DISPATCHER_HEADER
   ; SignalState: 0=non-signaled, 1=signaled

; NotificationEvent: stays signaled until manually reset
; SynchronizationEvent: auto-reset after one waiter is released
```

### Mutexes (Mutants)

```
lkd> dt nt!_KMUTANT <addr>
   +0x000 Header     : _DISPATCHER_HEADER
   +0x018 MutantListEntry : _LIST_ENTRY   ; owner's mutant list
   +0x028 OwnerThread : Ptr64 _KTHREAD   ; NULL if unowned
   +0x030 Abandoned   : BOOLEAN
   +0x031 ApcDisable  : UCHAR            ; kernel mutexes disable APCs
```

### Semaphores

```
lkd> dt nt!_KSEMAPHORE <addr>
   +0x000 Header  : _DISPATCHER_HEADER
   +0x018 Limit   : LONG    ; maximum count
   ; Header.SignalState = current count
```

### Timers

```
lkd> dt nt!_KTIMER <addr>
   +0x000 Header      : _DISPATCHER_HEADER
   +0x010 DueTime     : _ULARGE_INTEGER  ; expiration time (100ns units)
   +0x018 TimerListEntry : _LIST_ENTRY
   +0x028 Dpc         : Ptr64 _KDPC     ; optional DPC to fire
   +0x030 Processor   : Uint4B
   +0x034 Period      : Uint4B          ; 0 = one-shot, non-zero = periodic

; Show all timer objects
lkd> !timer
```

### Wait Blocks — `_KWAIT_BLOCK`

When a thread waits, the kernel allocates wait blocks linking the thread to the objects it waits on.

```
lkd> dt nt!_KWAIT_BLOCK
   +0x000 WaitListEntry : _LIST_ENTRY   ; links into object's WaitListHead
   +0x010 WaitType      : UCHAR         ; WaitAll=1, WaitAny=0
   +0x011 BlockState    : UCHAR
   +0x012 WaitKey       : USHORT        ; index in wait array
   +0x014 SpareLong     : LONG
   +0x018 Thread        : Ptr64 _KTHREAD
   +0x020 Object        : Ptr64 Void    ; the object being waited on
   +0x028 NextWaitBlock : Ptr64 _KWAIT_BLOCK
```

### Critical Sections (ERESOURCE / Push Locks)

```
; View critical section (user-mode)
0:000> !cs                   ; all critical sections
0:000> !cs <cs_addr>         ; specific critical section
0:000> !locks                ; deadlock detection

; Kernel push lock
lkd> dt nt!_EX_PUSH_LOCK <addr>
   +0x000 Value : Uint8B
   ; bit 0 = Locked, bit 1 = Waiting, bit 2 = Exclusive
```

---

## 9. Handle Tables and Object Namespaces

### Handle Table — `_HANDLE_TABLE`

Each process has a handle table accessed via `EPROCESS.ObjectTable`. Kernel handles live in the System process handle table.

```
; Dump process handle table
lkd> !handle 0 0            ; brief list for current process
lkd> !handle 0 3            ; with type names
lkd> !handle 0 f            ; full details

; Handle table for a specific process
lkd> .process /P <eprocess>
lkd> !handle 0 f

; dt handle table structure
lkd> dt nt!_HANDLE_TABLE <addr>
   +0x000 NextHandleNeedingPool : Uint4B
   +0x004 ExtraInfoPages        : Uint4B
   +0x008 TableCode             : Uint8B   ; points to table (or table of tables)
   +0x010 QuotaProcess          : Ptr64 _EPROCESS
   +0x018 HandleTableList       : _LIST_ENTRY
   +0x028 UniqueProcessId       : Uint4B
```

### Object Namespace

The object manager maintains a namespace rooted at `\`. Key directories:

| Path | Contents |
|---|---|
| `\Device` | Device objects |
| `\Driver` | Driver objects |
| `\BaseNamedObjects` | Session 0 named kernel objects |
| `\Sessions\N\BaseNamedObjects` | Per-session named objects |
| `\Sessions\N\AppContainerNamedObjects\<SID>` | Per-AppContainer objects |
| `\KernelObjects` | Memory notification events (LowMemoryCondition, etc.) |
| `\ObjectTypes` | All registered object types |
| `\GLOBAL??` | Symbolic links (DOS device map) |
| `\Silos\<JID>` | Windows Container silo namespace |

```
; Navigate object namespace
lkd> !object \

; Find a specific named object
lkd> !object \KernelObjects\LowMemoryCondition
lkd> !object \BaseNamedObjects\MyEvent

; List all object types
lkd> !object \ObjectTypes
```

---

## 10. Jobs and Silos

### Job Object — `_EJOB`

Jobs group processes together and enforce shared limits (CPU, memory, UI).

```
; Check if a process is in a job
lkd> !process 0 1 <name>    ; look for non-zero "Job" field

; Dump job details
lkd> !job <ejob_addr>

; Raw structure
lkd> dt nt!_EJOB <ejob_addr>

; Silo globals (server silos / Windows Containers)
lkd> !silo -g Host
lkd> dx -r1 (*((nt!_ESERVERSILO_GLOBALS *)0x<addr>))
```

### Silo (Container) Inspection

```
; List processes in a silo
lkd> !silo <job_addr>

; Silo context for AFD driver
lkd> dps poi(afd!AfdPodMonitor)

; Get silo slot content
lkd> r? @$t0 = (nt!_ESERVERSILO_GLOBALS*)@@masm(nt!PspHostSiloGlobals)
lkd> ?? ((void***)@$t0->Storage)[9 * 2 + 1]
lkd> !object (0x<slot_ptr> & -2)
```

---

## 11. Protected Processes and PPL

### Protection Levels

The `Protection` byte in `_EPROCESS` encodes both the protection type and the signer:

| Symbol | Value | Type | Signer | Used By |
|---|---|---|---|---|
| PS_PROTECTED_SYSTEM | 0x72 | Protected | WinSystem | System, Memory Compression |
| PS_PROTECTED_WINTCB | 0x62 | Protected | WinTcb | Smss, Csrss, Wininit |
| PS_PROTECTED_WINTCB_LIGHT | 0x61 | PPL | WinTcb | Werfaultsecure |
| PS_PROTECTED_WINDOWS | 0x52 | Protected | Windows | Spooler (some) |
| PS_PROTECTED_WINDOWS_LIGHT | 0x51 | PPL | Windows | RmSvc, FontDrvHost |
| PS_PROTECTED_LSA_LIGHT | 0x41 | PPL | Lsa | Lsass.exe (if configured) |
| PS_PROTECTED_ANTIMALWARE_LIGHT | 0x31 | PPL | Anti-malware | MsMpEng.exe, security vendors |
| PS_PROTECTED_AUTHENTICODE | 0x21 | Protected | Authenticode | Werfault (full) |
| PS_PROTECTED_AUTHENTICODE_LIGHT | 0x11 | PPL | Authenticode | Werfault (light) |
| PS_PROTECTED_NONE | 0x00 | None | None | All normal processes |

Access rights denied for protected processes:
- `PROCESS_VM_READ` / `PROCESS_VM_WRITE`
- `PROCESS_CREATE_THREAD`
- `PROCESS_DUP_HANDLE`
- `PROCESS_QUERY_INFORMATION` (only LIMITED allowed)

```
; Show protection value
lkd> dt nt!_EPROCESS <addr> Protection
; Or via !process output
lkd> !process 0 1 lsass.exe   ; look for "Protection" field

; Find all protected processes
lkd> !for_each_process .if @@(((nt!_EPROCESS*)${@#Process})->Pcb.SecurePid) {
    .printf "Trustlet: %ma (%p)\n",
    @@(((nt!_EPROCESS*)${@#Process})->ImageFileName), @#Process }

; ELAM driver detection — check anti-malware PPL processes
lkd> !process 0 0 MsMpEng.exe
lkd> dt nt!_EPROCESS <addr> Protection
```

### PatchGuard (Kernel Patch Protection)

PatchGuard monitors and crashes the system if it detects tampering with:
- Kernel code and dependencies
- SSDT (System Service Descriptor Table)
- GDT / IDT
- Critical kernel data structures

Detecting KPP trips:
- Bugcheck `0x109` (`CRITICAL_STRUCTURE_CORRUPTION`)
- Parameter 1 encodes the corrupted structure type:

| Parameter 1 | Corrupted Structure |
|---|---|
| 0x0 | Generic data region |
| 0x1 | Modification of a function or .pdata |
| 0x3 | Processor IDT |
| 0x4 | Processor GDT |
| 0x5 | Type 1 process list corruption |
| 0x6 | Type 2 process list corruption |
| 0x7 | Debug routine modification |
| 0x8 | CR4 modification |

```
; Analyze KPP crash dump
lkd> !analyze -v
; Look for CRITICAL_STRUCTURE_CORRUPTION (0x109)

; Check bugcheck parameters
lkd> .bugcheck
; p1 = structure type, p2 = address of modification, p3 = detail
```

---

## 12. Scenario Reference — Quick Command Lookup

### Scenario: Find a Process and Examine It

```
; Step 1: Find the process
lkd> !process 0 0 notepad.exe

; Step 2: Set context
lkd> .process /r /P <eprocess_addr>

; Step 3: Dump structures
lkd> dt nt!_EPROCESS <eprocess_addr>
lkd> !peb <peb_addr>
lkd> !handle 0 f
lkd> !vad
```

### Scenario: Analyze a Thread Hang

```
; Find the hung process and its threads
lkd> !process 0 2 <name>

; Look at the waiting threads
; Each THREAD line shows wait reason and objects

; Switch to a stuck thread
lkd> .thread /p /r <ethread_addr>

; Get full stack
lkd> !thread <ethread_addr>
lkd> k

; Check wait objects
lkd> dt nt!_KTHREAD <ethread_addr> WaitBlockList
```

### Scenario: Investigate a Token for Privilege Escalation

```
; Get token from process
lkd> !process 0 1 <suspicious_process>
; Note Token address

; Examine token
lkd> !token <token_addr>

; Check for dangerous privileges
; SeDebugPrivilege, SeLoadDriverPrivilege, SeTcbPrivilege

; Check integrity level
; Look for "Mandatory Label" in !token output

; Check impersonation tokens on threads
lkd> !process <eprocess> 4    ; show threads with security info
```

### Scenario: Detect DKOM (Direct Kernel Object Manipulation)

```
; Walk the official ActiveProcessLinks list
dx Debugger.Utility.Collections.FromListEntry(*(nt!_LIST_ENTRY*)&nt!PsActiveProcessHead, "nt!_EPROCESS", "ActiveProcessLinks").Select(p => new { Name = p.ImageFileName, PID = (__int64)p.UniqueProcessId })

; Compare against CID table (handle-based list)
; !handle 0 f 0 Process    ; enumerate all process handles in System process

; Walk PspCidTable to find all live processes/threads
lkd> dt nt!_HANDLE_TABLE poi(nt!PspCidTable)
```

### Scenario: Investigate Memory Injection

```
; List VADs of a process
lkd> !process 0 1 <name>   ; get VadRoot
lkd> !vad <vad_root> 1     ; verbose VAD dump

; Look for VADs with PAGE_EXECUTE_READWRITE or no image backing
; Suspicious: executable private allocation, no mapped file

; Check specific address
lkd> !pte <suspicious_va>
lkd> !address <suspicious_va>    ; shows region type and state

; Dump memory
lkd> db <suspicious_va>          ; bytes
lkd> uf <suspicious_va>          ; disassemble as function
```

### Scenario: Track Kernel Object Creation

```
; Pool allocation tracing (requires special pool debug)
; Enable special pool for a tag:
; verifier /flags 0x1 /driver <driver_name>  ; then !verifier

; Pool allocation by tag
lkd> !poolused 2    ; non-paged pool by tag
lkd> !poolfind Proc ; find allocations with "Proc" tag

; Specific object counts
lkd> dt nt!ObTypeIndexTable    ; check object type counters
lkd> dt nt!_OBJECT_TYPE <type_addr> TypeInfo.TotalNumberOfObjects
```

### Scenario: IRQL and Interrupt Analysis

```
; Current IRQL
lkd> !irql

; View interrupt routing
lkd> !idt         ; all IDT entries with handlers

; Check APIC state
lkd> !apic        ; per-processor APIC
lkd> !ioapic      ; I/O APIC routing

; Find interrupt for a device
lkd> !idt         ; look for driver name in output
lkd> dt nt!_KINTERRUPT <addr>   ; inspect interrupt object
```

### Scenario: Examine Security Descriptor of an Object

```
; Get object header
lkd> !object <obj_addr>
; Note ObjectHeader address

lkd> dt nt!_object_header <obj_header_addr>
; SecurityDescriptor is usually encoded in the last field
; (mask last nibble — it encodes flags)

; Decode security descriptor
lkd> !sd <sd_addr & ~0xf>

; Check specific process SD
lkd> !process 0 0 explorer.exe
lkd> !object <eprocess_addr>
lkd> dt nt!_object_header <header_addr>
```

### Scenario: Debug BSOD / Crash Dump

```
; Automated analysis
lkd> !analyze -v

; Bugcheck code and parameters
lkd> .bugcheck

; Current stack at crash
lkd> k

; Faulting module
lkd> lmv m <module_name>

; Check pool corruption
lkd> !pool <crash_addr>

; Trap frame (if available)
lkd> !trap <trap_frame_addr>
lkd> dt nt!_KTRAP_FRAME <addr>
```

### Key Command Quick Reference

| Command | Purpose |
|---|---|
| `!process 0 0` | List all processes (brief) |
| `!process 0 2` | List all processes with thread summary |
| `!process <addr> 7` | Full process dump with threads and stacks |
| `!thread <addr>` | Dump thread details |
| `dt nt!_EPROCESS <addr>` | Raw EPROCESS structure |
| `dt nt!_ETHREAD <addr>` | Raw ETHREAD structure |
| `!peb [addr]` | Process Environment Block |
| `!teb [addr]` | Thread Environment Block |
| `!token <addr>` | Security token details |
| `!handle 0 f` | All handles in current process |
| `!object <path or addr>` | Object Manager object |
| `!vad` | Virtual Address Descriptor tree |
| `!pte <va>` | Page Table Entry for a virtual address |
| `!pfn <pfn>` | Physical Page Frame Number info |
| `!pool <addr>` | Pool allocation details |
| `!heap` | Heap information |
| `!idt` | Interrupt Descriptor Table |
| `!irql` | Current IRQL |
| `!apic` | Per-CPU APIC state |
| `!timer` | All timer objects |
| `!locks` | Deadlock / critical section analysis |
| `!analyze -v` | Automated crash analysis |
| `!vm` | Virtual memory summary |
| `!sysptes` | System PTE usage |
| `!job <addr>` | Job object details |
| `!silo` | Container silo information |
| `dx @$cursession.Processes` | DDM process enumeration |
| `dx @$pcr` | Processor Control Region |
| `dx @$thread` | Current thread (DDM) |

---

## Appendix A: Structure Offset Quick Reference (x64 Windows 10/11)

| Structure | Key Field | Approx Offset | Notes |
|---|---|---|---|
| `_EPROCESS` | `Pcb` (KPROCESS) | +0x000 | Embedded, not pointer |
| `_EPROCESS` | `UniqueProcessId` | +0x2e8 | PID |
| `_EPROCESS` | `ActiveProcessLinks` | +0x2f0 | LIST_ENTRY in global list |
| `_EPROCESS` | `ObjectTable` | +0x418 | `_HANDLE_TABLE *` |
| `_EPROCESS` | `Token` | varies | `_EX_FAST_REF` to token |
| `_EPROCESS` | `Job` | +0x3b0 | `_EJOB *` or NULL |
| `_EPROCESS` | `VadRoot` | varies | VAD tree root |
| `_EPROCESS` | `Protection` | varies | `_PS_PROTECTION` byte |
| `_KPROCESS` | `DirectoryTableBase` | +0x028 | CR3 / physical page dir PA |
| `_KPROCESS` | `ThreadListHead` | +0x030 | All threads of this process |
| `_KPROCESS` | `SecurePid` | +0x2d0 | VTL1 handle (trustlets) |
| `_ETHREAD` | `Tcb` (KTHREAD) | +0x000 | Embedded KTHREAD |
| `_ETHREAD` | `CreateTime` | +0x5d8 | Thread creation time |
| `_KTHREAD` | `InitialStack` | +0x028 | Top of kernel stack |
| `_KTHREAD` | `WaitBlockList` | varies | Chain of wait blocks |
| `_KTHREAD` | `SecureThreadCookie` | +0x31c | VTL1 thread table index |
| `_PEB` | `ImageBaseAddress` | +0x010 | Base of EXE |
| `_PEB` | `Ldr` | +0x018 | `_PEB_LDR_DATA *` |
| `_PEB` | `BeingDebugged` | +0x002 | 1 if debugger attached |
| `_TEB` | `ClientId` | +0x040 | PID + TID |
| `_TEB` | `LastErrorValue` | +0x068 | Win32 last error |
| `_TEB` | `NtTib.StackBase` | +0x008 | Stack top |
| `_TEB` | `NtTib.StackLimit` | +0x010 | Stack guard page |
| `_TOKEN` | `Privileges` | +0x040 | `_SEP_TOKEN_PRIVILEGES` |
| `_TOKEN` | `UserAndGroups` | +0x098 | Array of SID+attributes |
| `_TOKEN` | `SessionId` | +0x078 | Session ID |
| `_OBJECT_HEADER` | `TypeIndex` | +0x018 | Index in ObTypeIndexTable |
| `_OBJECT_HEADER` | `HandleCount` | +0x008 | Open handle count |
| `_OBJECT_HEADER` | `InfoMask` | +0x01a | Optional header bits |
| `_KPCR` | `TssBase` | varies | `_KTSS64 *` for this CPU |
| `_KPCR` | `IdtBase` | varies | IDT pointer |
| `_KPCR` | `Self` | +0x018 | Self-pointer |
| `_KPRCB` | `CurrentThread` | varies | Currently executing thread |
| `_KPRCB` | `DebuggerSavedIRQL` | varies | IRQL before debugger break |
| `_KPRCB` | `DpcData` | varies | DPC queue (threaded + nonthreaded) |

> **Note:** All offsets are approximate for 64-bit Windows 10/11. Exact offsets change between Windows builds. Always use `dt nt!_STRUCTURE` in a kernel debugger to get the exact layout for your target.

---

## Appendix B: EDR-Relevant WinDbg Scenarios

### Detect Process Hollowing (VAD Mismatch)

```
; Compare mapped image sections vs. expected file paths
lkd> !process 0 1 svchost.exe
lkd> !vad <vad_root> 1
; Look for VADs with MEM_IMAGE but unexpected file path
; Or VADs with EXECUTE_READWRITE (private + executable) that should be image-backed
```

### Detect Thread Hijacking / APC Injection

```
; Check for queued user-mode APCs
lkd> !process <eprocess> 4
; If threads show WAIT APC_LEVEL or UserMode APC pending, inspect further

; APC list on a specific thread
lkd> dt nt!_KTHREAD <ethread> ApcState.ApcListHead
```

### Detect Handle Table Manipulation (DKOM)

```
; Validate handle table consistency
lkd> .process /P <eprocess>
lkd> !handle 0 f     ; enumerate all handles — should include expected objects

; Walk object reference counts for suspicious objects
lkd> !object <obj_addr>   ; check HandleCount vs PointerCount
```

### Detect Token Theft

```
; Check if a process has an unexpected high-privilege token
lkd> !process 0 1 malware.exe
lkd> !token <token_addr>
; Check: does this process have SeDebugPrivilege or SeTcbPrivilege enabled?
; Is TokenType = Primary but token authentication ID matches another session?
```

### Examine Kernel Callbacks (EDR Registration)

```
; Process creation callbacks
lkd> dt nt!PspCreateProcessNotifyRoutine
; or via DDM:
dx Debugger.Utility.Collections.FromArray((void*(*)[64])&nt!PspCreateProcessNotifyRoutine, 64).Where(r => r != 0).Select(r => new { Callback = ((__int64)r) & ~0xf })

; Thread creation callbacks
lkd> dt nt!PspCreateThreadNotifyRoutine

; Image load callbacks
lkd> dt nt!PspLoadImageNotifyRoutine

; Object callbacks (ObRegisterCallbacks)
lkd> dt nt!ObpCalloutCache
```

---

---

**Sources and Verification**

All structure layouts in this document can be independently verified using Microsoft's free public symbols:

```
; In WinDbg: configure the Microsoft Symbol Server
.sympath srv*C:\Symbols*https://msdl.microsoft.com/download/symbols

; Then verify any structure, e.g.:
dt nt!_EPROCESS
dt nt!_KTHREAD
dt nt!_TOKEN
```

WinDbg and its extension commands are documented at:
- [WinDbg command reference](https://learn.microsoft.com/en-us/windows-hardware/drivers/debugger/commands)
- [Debugger Data Model (dx)](https://learn.microsoft.com/en-us/windows-hardware/drivers/debugger/dx--display-visualizer-variables-)
- [Kernel-mode extensions](https://learn.microsoft.com/en-us/windows-hardware/drivers/debugger/kernel-mode-extensions)

Privilege constants and SID definitions: Windows SDK `winnt.h`, `ntifs.h` (publicly available).

*These are independent study notes. Any resemblance in structure to published works reflects the underlying subject matter — the Windows kernel itself — not reproduction of any copyrighted text.*
