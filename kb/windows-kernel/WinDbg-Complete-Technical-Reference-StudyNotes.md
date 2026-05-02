# WinDbg Complete Technical Reference — Study Notes

> **Independent study notes** covering WinDbg commands, kernel structures, debugging workflows,
> scripting (DDM, PyKD, Natvis), and EDR/security analysis patterns.
>
> **Sources:** All commands and structure layouts are drawn from publicly available Microsoft documentation:
> - [WinDbg command reference](https://learn.microsoft.com/en-us/windows-hardware/drivers/debugger/commands)
> - [Debugger Data Model (dx)](https://learn.microsoft.com/en-us/windows-hardware/drivers/debugger/dx--display-visualizer-variables-)
> - [Kernel debugging reference](https://learn.microsoft.com/en-us/windows-hardware/drivers/debugger/kernel-mode-extensions)
> - [Windows Driver Kit (WDK) documentation](https://learn.microsoft.com/en-us/windows-hardware/drivers/)
> - [PyKD project documentation](https://githubcom/ivellioscolin/pykd) (open source, Apache 2.0)
> - [Natvis framework reference](https://learn.microsoft.com/en-us/visualstudio/debugger/create-custom-views-of-native-objects)
> - Microsoft public debug symbols (`srv*https://msdl.microsoft.com/download/symbols`)
> - Windows SDK public headers: `ntdef.h`, `wdm.h`, `ntifs.h`, `winnt.h`
>
> Structure field names and offsets are verifiable with `dt nt!_STRUCTURENAME` in WinDbg
> using public symbols against any matching Windows build.
>
> **License:** Released under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).
> Free to share and adapt with attribution.

---

## Table of Contents

1. [Kernel Object Types and Key Fields](#1-kernel-object-types-and-key-fields)
2. [WinDbg Core Commands](#2-windbg-core-commands)
3. [Extension Commands by Category](#3-extension-commands-by-category)
4. [Debugger Data Model (DDM) and dx Queries](#4-debugger-data-model-ddm-and-dx-queries)
5. [LIST_ENTRY Architecture and Debugging](#5-list_entry-architecture-and-debugging)
6. [Pool Memory Structures and Commands](#6-pool-memory-structures-and-commands)
7. [Synchronization Objects and Commands](#7-synchronization-objects-and-commands)
8. [Memory Management Structures and Commands](#8-memory-management-structures-and-commands)
9. [I/O and IRP Structures](#9-io-and-irp-structures)
10. [Symbol Management](#10-symbol-management)
11. [Crash Dump Types and Collection](#11-crash-dump-types-and-collection)
12. [Debugging Scenarios](#12-debugging-scenarios)
13. [PyKD API Reference](#13-pykd-api-reference)
14. [Natvis Framework Reference](#14-natvis-framework-reference)
15. [Bug Check Codes and Analysis](#15-bug-check-codes-and-analysis)
16. [EDR Kernel Callbacks and Security Internals](#16-edr-kernel-callbacks-and-security-internals)
17. [Pseudo-Registers and Scripting](#17-pseudo-registers-and-scripting)
18. [Malware Memory Analysis Patterns](#18-malware-memory-analysis-patterns)
19. [Debug Session Setup and Attachment Modes](#19-debug-session-setup-and-attachment-modes)
20. [x64 Architecture and Calling Convention](#20-x64-architecture-and-calling-convention)
21. [Additional Commands and Patterns](#21-additional-commands-and-patterns)

---

## 1. Kernel Object Types and Key Fields

### 1.1 _EPROCESS / _KPROCESS

`_KPROCESS` is embedded as the **first member** of `_EPROCESS`. Accessing `_KPROCESS` fields through `_EPROCESS` is valid by pointer cast.

**_KPROCESS key fields:**
| Field | Description |
|---|---|
| `PID` | Process ID |
| `DirectoryTableBase` | CR3 value / page directory base |
| `ThreadListHead` | LIST_ENTRY head → _KTHREAD.ThreadListEntry |
| `Affinity` | Processor affinity mask |
| `Priority` | Base scheduling priority |
| `BasePriority` | Base priority class |
| `Quantum` | Thread quantum |
| `State` | Process state |
| `WaitListEntry` | LIST_ENTRY for wait list |
| `KernelStack` | Kernel stack pointer |

**_EPROCESS additional fields (beyond _KPROCESS):**
| Field | Description |
|---|---|
| `UniqueProcessId` | PID (HANDLE) |
| `ActiveProcessLinks` | LIST_ENTRY → `PsActiveProcessHead` |
| `ObjectTable` | Handle table (PHANDLE_TABLE) |
| `VadRoot` | VAD tree root |
| `Token` | Security token (_EX_FAST_REF) |
| `QuotaPoolUsage` | Paged/NonPaged pool usage |
| `WorkingSetSize` | Working set page count |
| `PageFaultCount` | Page fault counter |
| `Peb` | Pointer to _PEB (user-mode) |
| `InheritedFromUniqueProcessId` | Parent PID |
| `ImageFileName` | 15-char image name (UCHAR[15]) |
| `DebugPort` | Debug port (attached debugger) |
| `ExceptionPort` | Exception port |

**WinDbg commands for EPROCESS:**
```
!process 0 0                        ; list all processes (brief)
!process 0 7                        ; list all processes (full detail)
!process 0 0 notepad.exe            ; find specific process
!process <addr> 7                   ; full detail for one process
dt nt!_EPROCESS <addr>              ; dump full structure
dt nt!_EPROCESS <addr> Token        ; single field
dx @$curprocess                     ; current process (DDM)
dx -r1 @$curprocess.ObjectTable.HandleCount
dx @$proc.DirectoryTableBase
```

**Flags for !process:**
| Flag | Output |
|---|---|
| 0 | Time and priority info |
| 1 | Threads, events, wait state |
| 2 | Thread list |
| 3 | Return address + stack pointer |

---

### 1.2 _ETHREAD / _KTHREAD

`_KTHREAD` (TCB = Thread Control Block) is embedded as the **first member** of `_ETHREAD`.

**_KTHREAD key fields:**
| Field | Description |
|---|---|
| `TID` | Thread ID |
| `Context` | Saved context (registers) |
| `KernelStack` | Kernel stack pointer |
| `ApcState` | APC state structure |
| `WaitBlock` | Array of wait blocks |
| `State` | Thread state (Running/Waiting/etc.) |
| `Priority` | Current priority |
| `Affinity` | Processor affinity |
| `Quantum` | Remaining quantum |
| `ThreadListEntry` | LIST_ENTRY → _KPROCESS.ThreadListHead |

**_ETHREAD additional fields (beyond _KTHREAD):**
| Field | Description |
|---|---|
| `Tcb` | Embedded _KTHREAD (first member) |
| `Teb` | Pointer to _TEB (user-mode) |
| `Cid.UniqueProcess` | Owning process ID |
| `Cid.UniqueThread` | Thread ID |
| `ImpersonationToken` | Impersonation token |
| `TerminationPort` | Termination port |
| `IrpList` | LIST_ENTRY of pending IRPs |

**WinDbg commands for ETHREAD:**
```
!thread                             ; current thread
!thread <addr>                      ; specific thread
!thread <addr> 7                    ; full detail
dt nt!_ETHREAD <addr>
dx @$thread                         ; current thread (DDM)
dx @$thread.Tcb                     ; KTHREAD via DDM
dx @$thread.Tcb.Teb                 ; TEB pointer via DDM
~*kb                                ; all thread stacks
~<n>s                               ; switch to thread n
~.                                  ; current thread
~                                   ; list all threads
```

**Flags for !thread:**
| Flag | Output |
|---|---|
| 1 | Wait states |
| 2 | Stack trace + wait |
| 3 | Return address + stack pointers |
| 4 | Set process context |

---

### 1.3 _PEB (Process Environment Block)

**_PEB key fields (32-bit offsets):**
| Offset | Field | Description |
|---|---|---|
| +0x000 | `InheritedAddressSpace` | BOOLEAN |
| +0x001 | `ReadImageFileExecOptions` | BOOLEAN |
| +0x002 | `BeingDebugged` | BOOLEAN — anti-debug check target |
| +0x008 | `ImageBaseAddress` | Base address of main executable |
| +0x00c | `Ldr` | Ptr to _PEB_LDR_DATA |
| +0x010 | `ProcessParameters` | Ptr to _RTL_USER_PROCESS_PARAMETERS |

**_PEB_LDR_DATA fields:**
| Offset | Field | Description |
|---|---|---|
| +0x000 | `Length` | Size of structure |
| +0x004 | `Initialized` | Initialization flag |
| +0x00c | `InLoadOrderModuleList` | LIST_ENTRY (load order) |
| +0x014 | `InMemoryOrderModuleList` | LIST_ENTRY (memory order) |
| +0x01c | `InInitializationOrderModuleList` | LIST_ENTRY (init order) |

**WinDbg commands for PEB:**
```
!peb                                ; current process PEB
!peb <addr>                         ; specific PEB address
dt nt!_PEB -r @$peb                 ; recursive dump
dt ntdll!_PEB 7efde000              ; at specific address
dx @$peb                            ; DDM access
```

---

### 1.4 _TEB (Thread Environment Block)

**_TEB key fields:**
| Field | Description |
|---|---|
| `ExceptionList` | SEH chain head |
| `StackBase` | Top of thread stack |
| `StackLimit` | Current stack commit limit |
| `DeallocationStack` | Base of stack reservation (+0xe0c) |
| `LastErrorValue` | Win32 last error |
| `LastStatusValue` | NTSTATUS last status |

**WinDbg commands for TEB:**
```
!teb                                ; current thread TEB
dt nt!_TEB                          ; dump TEB structure
dt ntdll!_TEB DeallocationStack 7ffdf000   ; single field at address
!address esp                        ; shows stack region info
```

---

### 1.5 _KPCR / _KPRCB

`_KPCR` (Kernel Processor Control Region): per-processor block at the base of each processor's data.

`_KPRCB` (Kernel Processor Control Block): embedded in _KPCR, larger structure with scheduling data.

**WinDbg commands:**
```
!pcr [Processor]                    ; dump KPCR for processor N
!prcb [Processor]                   ; dump KPRCB for processor N
dt nt!_KPCR
dt nt!_KPRCB
```

---

### 1.6 _OBJECT_HEADER / _OBJECT_TYPE

All kernel objects are preceded by `_OBJECT_HEADER`.

**_OBJECT_HEADER fields:**
| Field | Description |
|---|---|
| `PointerCount` | Reference count |
| `HandleCount` | Handle count |
| `Type` | Ptr to _OBJECT_TYPE |
| `NameInfoOffset` | Offset to name info (if any) |
| `Body` | Start of the actual object |

Object body address = `_OBJECT_HEADER` address + `sizeof(_OBJECT_HEADER)`.
Reverse: header address = object address - `FIELD_OFFSET(_OBJECT_HEADER, Body)`.

**WinDbg commands:**
```
!object <addr>                      ; display object at address
!object \                           ; walk object directory from root
!object \Device                     ; specific directory
!obja <addr>                        ; object attributes
dt nt!_OBJECT_HEADER <addr>
dt nt!_OBJECT_TYPE
```

---

### 1.7 _DISPATCHER_HEADER

Embedded at offset 0 in all waitable kernel objects (events, mutexes, semaphores, threads, timers).

**_DISPATCHER_HEADER fields:**
| Field | Description |
|---|---|
| `Type` | Object type code |
| `Size` | Size in DWORDs |
| `SignalState` | Current signal state |
| `WaitListHead` | LIST_ENTRY of waiting threads (_KWAIT_BLOCK) |

---

### 1.8 _TOKEN

Access token attached to process or thread for security context.

```
!token                              ; current process token
!token <addr>                       ; specific token
dt nt!_TOKEN
```

**_TOKEN referenced structures:**
- `_TOKEN_TYPE` (TokenPrimary or TokenImpersonation)
- `_SID` (security identifier)
- `_SID_NAME_USE`
- `_TOKEN_SOURCE`
- `_SEP_TOKEN_PRIVILEGES`
- `_SECURITY_IMPERSONATION_LEVEL`
- `_TOKEN_CONTROL`
- `_SID_AND_ATTRIBUTES_HASH`

**Token access from EPROCESS:**
```
dt nt!_EPROCESS <addr> Token        ; _EX_FAST_REF (low bits = ref count)
; To get clean token pointer: mask off low 4 bits
? (<Token_value> & ~0xf)
```

---

### 1.9 _KTRAP_FRAME

Constructed on the kernel stack during system calls and exceptions. Contains saved user-mode register state.

**Kernel entry (x64 system call):**
1. `syscall` instruction executed in user mode
2. LSTAR MSR = address of `KiSystemCall64`
3. SSN (System Service Number) in EAX
4. `_KTRAP_FRAME` constructed on kernel stack
5. `PreviousMode` set to `UserMode`

```
.trap <addr>                        ; set context to trap frame
dt nt!_KTRAP_FRAME <addr>
```

---

### 1.10 _KWAIT_BLOCK

Linked list node connecting a thread to an object it is waiting on.

**_KWAIT_BLOCK fields:**
| Field | Description |
|---|---|
| `WaitListEntry` | LIST_ENTRY into dispatcher object's WaitListHead |
| `Thread` | Back-pointer to waiting _KTHREAD |
| `Object` | Pointer to object being waited on |
| `NextWaitBlock` | Next wait block in thread's chain |
| `WaitKey` | Index in WaitBlockArray |
| `WaitType` | WaitAny or WaitAll |

---

### 1.11 _KAPC / _KAPC_STATE

APC (Asynchronous Procedure Call) structures for deferred procedure calls to threads.

**Referenced data structures:**
- `_KAPC` — individual APC object
- `_KAPC_STATE` — APC state per thread (Normal/Attaching/etc.)

```
dt nt!_KAPC
dt nt!_KAPC_STATE
```

---

### 1.12 _KDPC

Deferred Procedure Call object, queued to run at DISPATCH_LEVEL.

```
!dpcs [Processor]                   ; list pending DPCs
dt nt!_KDPC
```

---

### 1.13 _KTIMER / _KTIMER_TABLE

Kernel timer objects, backed by timer tables per processor.

```
!timer                              ; list all active timers
dt nt!_KTIMER
dt nt!_KTIMER_TABLE
dt nt!_KTIMER_TABLE_ENTRY
```

---

## 2. WinDbg Core Commands

### 2.1 Execution Control

```
g                                   ; go (continue)
p                                   ; step over
t                                   ; step into
gu                                  ; step out (go up)
.restart                            ; restart target
q                                   ; quit debugger
```

### 2.2 Breakpoints

```
bp <address>                        ; software breakpoint (ordinary)
bu <symbol>                         ; deferred/unresolved breakpoint
bm <pattern>                        ; breakpoint on all matching symbols
ba w4 <addr>                        ; hardware data BP (write 4 bytes)
ba r4 <addr>                        ; hardware data BP (read/write 4 bytes)
ba e1 <addr>                        ; hardware execution BP (1 byte)
bd <id>                             ; disable breakpoint
bc <id>                             ; clear/delete breakpoint
be <id>                             ; enable breakpoint
bl                                  ; list all breakpoints
```

**Conditional breakpoints:**
```
bp addr "j (@@(Irp)=0xffb5c4f8) ''; 'g'"    ; j = IF/ELSE
bp addr ".if (@rax == 0) { .echo hit } .else { g }"
bp /1 addr                          ; one-shot breakpoint
bp /p <EPROCESS_addr> addr          ; break only in specific process
bp /t <ETHREAD_addr> addr           ; break only on specific thread
bp /1 /C 4 /p 0x81234000 addr       ; combined: one-shot, CPU 4, process
bu sioctl!DriverEntry               ; deferred (unresolved) BP
```

**Data breakpoint (hardware):**
```
ba w4 0xffb5c4f8+0x18+0x4           ; write 4 bytes at IRP.IoStatus.Information
```

### 2.3 Stack Traces

```
k                                   ; basic stack trace
kn                                  ; stack with frame numbers
kb                                  ; stack with first 3 params
kv                                  ; stack with frame pointer and params
kp                                  ; stack with full params (requires symbols)
kL                                  ; suppress module/line info
kbn                                 ; frame numbers + params
kvn                                 ; frame number + pointer + params
kpn                                 ; frame number + full params
kPn                                 ; full param names + frame numbers
kf                                  ; show frame size
~*kb                                ; all threads: stack with params
```

### 2.4 Memory Display

```
d <addr>                            ; display memory (current format)
dd <addr>                           ; display as DWORDs
dq <addr>                           ; display as QWORDs
db <addr>                           ; display as bytes + ASCII
dw <addr>                           ; display as WORDs
da <addr>                           ; display as ASCII string
du <addr>                           ; display as Unicode string
dc <addr>                           ; display as DWORDs + ASCII
dyb <addr>                          ; display as binary + bytes
dp <addr>                           ; display as pointer-size
dps <addr>                          ; display pointer-sized values + symbols
dds <addr>                          ; display DWORDs + symbols
dpa <addr>                          ; display pointers as ASCII
dpu <addr>                          ; display pointers as Unicode
dpp <addr>                          ; display pointer then pointed-to pointer
dd <addr> l0x10                     ; limit output to 0x10 DWORDs
```

### 2.5 Memory Edit

```
eb <addr> <val>                     ; enter byte
ew <addr> <val>                     ; enter word
ed <addr> <val>                     ; enter dword
eq <addr> <val>                     ; enter qword
eza <addr> "string"                 ; enter zero-terminated ASCII
ezu <addr> "string"                 ; enter zero-terminated Unicode
f <addr> <len> <pattern>            ; fill memory with pattern
```

### 2.6 Display Variables and Types

```
dt <type>                           ; show type layout
dt <type> <addr>                    ; show instance of type
dt nt!_EPROCESS <addr>              ; specific module qualified
dt nt!_IRP <addr>                   ; IRP at address
dt -r1 <type> <addr>                ; recurse one level
dt -r <type> <addr>                 ; fully recursive (deep)
dt <type> <field> <addr>            ; single field only
dt ntdll!*peb*                      ; wildcard type search
dv                                  ; display local variables
dv /t /i /V                         ; with types, classify, verbose
dv <varname>                        ; specific variable
```

### 2.7 Disassembly

```
u <addr>                            ; unassemble (forward)
ub <addr>                           ; unassemble backward
uf <addr>                           ; unassemble entire function
u <addr> l10                        ; unassemble 16 instructions
```

### 2.8 Expression Evaluation

```
? <expr>                            ; MASM expression evaluator
?? <expr>                           ; C++ expression evaluator
?? Irp->Size                        ; C++ field access
?? @@c++( (nt!_EPROCESS*)@rax )     ; cast with C++ eval inside MASM
@@(<symbol>)                        ; evaluate symbol as address in MASM context
@@c++(<expr>)                       ; force C++ evaluation in MASM context
poi(<addr>)                         ; dereference pointer
.formats <value>                    ; show value in all formats (hex/dec/octal/binary)
```

### 2.9 Registers

```
r                                   ; display all registers
r rax                               ; specific register
r rax=<val>                         ; set register
.frame [/r] [N]                     ; switch to frame N, /r shows registers
```

### 2.10 Module Listing

```
lm                                  ; list modules (compact)
lm v                                ; verbose
lm vm <module>                      ; module verbose detail (timestamps, checksum)
lmstm                               ; list modules + timestamps
!lmi <module>                       ; PE header info, GUID, PDB path
!dlls                               ; loaded DLLs
!dlls -a                            ; with headers and sections
!dlls -v                            ; with version info
!dlls -c <module>                   ; specific module
dd <module_name> L1                 ; resolve module base (shows MZ: 00905a4d)
```

### 2.11 Thread Commands

```
~                                   ; list all threads
~.                                  ; current thread marker
~*                                  ; all threads + info
~0                                  ; thread 0
~<n>s                               ; set current thread to n
~* k                                ; all thread stacks
!uniqstack [-b|-v|-p] [-n]          ; unique stacks only
!findstack <Symbol> [DisplayLevel]  ; find threads with symbol on stack
                                    ; Level: 0=TID, 1=TID+frame, 2=full stack
!runaway [Flags]                    ; thread CPU usage
                                    ; 0=user time, 1=kernel time, 2=elapsed time, 7=all
```

**!runaway output format:**
```
Thread_index:TID  N days H:MM:SS.mmm
```

**~* output format:**
```
. 0 Id: dac.d28 Suspend: 1 Teb: 7efdd000 Unfrozen Start: ... Priority: 0 Priority class: 32 Affinity: 3
```

### 2.12 Process Commands

```
.tlist                              ; list processes (user-mode)
.process <addr>                     ; switch process context
.process /r /p <addr>               ; switch + reload user symbols
```

### 2.13 Scripting and Automation

```
.foreach (token {command}) { commands }
.shell <cmd>                        ; run shell command
.cmdtree                            ; open command tree window
z(<condition>)                      ; loop while condition true
.if (<cond>) { cmds } .else { cmds }
j <cond> 'true_cmds'; 'false_cmds'  ; inline if/else
#<pattern>                          ; search disassembly for pattern
s -a <range> "string"               ; search memory for ASCII string
s -u <range> "string"               ; search memory for Unicode string
s -d <range> <dword>                ; search for DWORD value
```

### 2.14 Logging

```
.logopen <filename>                 ; open log file
.logclose                           ; close log
.logappend <filename>               ; append to log
```

### 2.15 Misc Commands

```
.cls                                ; clear screen
.time                               ; show elapsed time
vertarget                           ; show target OS version
.chain                              ; list loaded extension DLLs
.prefer_dml 1                       ; enable DML (hyperlink output)
.dml_start                          ; start DML session
.help /D a*                         ; DML help, wildcard
ln <addr>                           ; list nearest symbols
x <module>!<pattern>                ; examine symbols
!exchain                            ; walk exception handler chain
!validatelist <addr>                ; validate LIST_ENTRY
dl <addr> <MaxCount>                ; display linked list (raw follow Flink)
dlb <addr> <MaxCount>               ; display linked list backward (follow Blink)
wt                                  ; watch trace (instruction count)
```

---

## 3. Extension Commands by Category

### 3.1 Process and Thread Analysis

```
!process [/s Session] [/m Module] [Process [Flags]]
!processfields                      ; field names for !process output
!thread [-p] [-t] [Address [Flags]]
!threadfields                       ; field names for !thread output
!teb [Address]                      ; Thread Environment Block
!peb [Address]                      ; Process Environment Block
!tp pool Address [Flags]            ; thread pool
```

### 3.2 Stack Analysis

```
!uniqstack [-b|-v|-p] [-n]          ; deduplicated thread stacks
!findstack [Symbol] [DisplayLevel]  ; find symbol on thread stacks
!for_each_frame <cmd>               ; execute command for each stack frame
```

### 3.3 Pool Memory

```
!pool [Address [Flags]]             ; pool contents + headers
                                    ; Flags: 0=contents+headers, 1=suppress others, 31=suppress type+tag
!poolval Address [Level]            ; validate pool entry
!poolfind Tag [PoolType]            ; find pool allocations by tag
                                    ; PoolType: 0=NonPaged, 1=Paged, 2=Special, 4=Session
!poolused [Flags [Tag]]             ; pool usage by tag
                                    ; Flags: 0=detail, 1=sort NP, 2=sort paged, 3=session
!frag [Flags]                       ; pool fragmentation
                                    ; Flags: 0=fragments only, 1=pool alloc+tags
!pooltag                            ; pool tag info
```

### 3.4 Virtual Memory

```
!vm [Flags]                         ; virtual memory summary
                                    ; 0=omit process, 1=MM stacks, 2=TS usage, 3=page log,
                                    ; 4=WS owner stacks, 5=kernel addr stats
!vprot [Address]                    ; virtual protect info for address
!vadump [-v]                        ; dump VAD tree (-v = verbose)
!address [Address]                  ; address region info
!address -summary                   ; summary of address space usage
!address -RegionUsageStack          ; stack region info
!pte [VA or PTE addr]               ; page table entry info
!pfn [Page Frame Number]            ; physical frame info
!memusage [Flags]                   ; memory usage (8=summary)
!sysptes                            ; system PTE usage
!ptov [PFN]                         ; physical-to-virtual translation
```

### 3.5 Object Manager

```
!object [Address or Name]           ; display kernel object
!obja [Address]                     ; object attributes
!handle [Handle [KMFlags [Process [TypeName]]]]
                                    ; KMFlags: 0=basic, 1=objects, 2=free, 4=kernel table, 5=TID/PID
!sd [Address]                       ; security descriptor
```

### 3.6 Processors and IRQLs

```
!irql                               ; current IRQL
!idt [IDT] [-a]                     ; Interrupt Descriptor Table
!ipi [Processor]                    ; IPI info
!qlocks                             ; queued spinlock status
!pcr [Processor]                    ; KPCR for processor
!prcb [Processor]                   ; KPRCB for processor
!running -ti                        ; running threads with time info
```

**IRQL Levels:**
| IRQL | Decimal | Description |
|---|---|---|
| PASSIVE_LEVEL | 0 | Normal thread execution |
| APC_LEVEL | 1 | APC delivery |
| DISPATCH_LEVEL | 2 | Thread scheduler, DPCs |
| DIRQL | 3-26 | Device interrupt levels |
| HIGH_LEVEL | 31 | NMI, machine check |

### 3.7 Locks and Synchronization

```
!locks [-v|-p|-d] [Address]         ; ERESOURCE locks
!locks -v                           ; verbose (include waiters)
!cs [Opts] [CsAddr]                 ; critical section(s)
                                    ; -l=locked, -s=init stack, -o=owner stack, -t=tree
!deadlock [1]                       ; deadlock detection (1=stacks)
!qlocks                             ; queued spinlock status
!avrf -cs                           ; Application Verifier: CS analysis
```

### 3.8 Heap

```
!heap -stat                         ; heap statistics
!heap -stat -h 0                    ; default heap statistics
!heap -m                            ; heap map
!heap -s 0                          ; summary for heap 0
!heap -p -all                       ; all page heap allocations
!heap -p -a <UserAddr>              ; specific allocation + backtrace
!heap -flt s <Size>                 ; filter by size
!heap -l                            ; leaks
!heap -h                            ; help
!heap -p -h <HeapHandle>            ; page heap entries for handle
!address -summary                   ; overall allocation summary
```

**Memory leak workflow:**
```
!address -summary           ; find suspicious heap growth
!heap -stat -h 0            ; heap stats for default heap
!heap -flt s <size>         ; filter to specific size
!heap -p -a <addr>          ; allocation + stack trace
dt ntdll!_DPH_HEAP_BLOCK StackTrace <addr>
dds <StackTrace>            ; resolve stack trace addresses
```

**GFlags for heap debugging:**
```
gflags.exe /i IMAGE.EXE +ust +hpa   ; +ust=user stack trace DB, +hpa=page heap
```

### 3.9 I/O and IRPs

```
!irp [Address] [Detail]             ; display IRP
!irpfind [-v] [PoolType [Restart [Criteria Data]]]  ; find IRPs in pool
!devobj <addr>                      ; device object
!drvobj <addr>                      ; driver object
!devnode [0] [1]                    ; device tree
                                    ; 0 1=entire tree, 1=pending removals, 2=pending ejects
!devstack [DeviceObject]            ; device stack
!irp @@(Irp)                        ; display IRP using C++ eval (use in MASM context)
```

### 3.10 Access Token

```
!token [Address]                    ; access token info
```

### 3.11 Timers and DPCs

```
!timer                              ; all active timers
!dpcs [Processor]                   ; pending DPCs
```

### 3.12 System Info

```
!sysinfo machineid                  ; machine ID
!sysinfo cpuinfo                    ; CPU info
!sysinfo cpuspeed                   ; CPU speed
!cpuinfo                            ; CPU info (alias)
!cpuid                              ; CPUID info
!whea                               ; WHEA errors
!errpkt [Address]                   ; error packet
!errrec [Address]                   ; error record
!tz / !tzinfo                       ; time zone info
```

### 3.13 Driver Verifier

```
!verifier                           ; driver verifier stats
!deadlock [1]                       ; deadlock detection
```

### 3.14 Analysis Commands

```
!analyze -v                         ; automatic crash analysis (exceptions)
!analyze -hang -v                   ; automatic hang analysis
!gle                                ; GetLastError + NTSTATUS for current thread
.lastevent                          ; last debug event
.ecxr                               ; exception context record
```

### 3.15 Symbol Commands

```
!sym noisy                          ; verbose symbol loading
!sym quiet                          ; quiet symbol loading
!chkimg [-f|-v|-d]                  ; check image integrity vs on-disk
!itoldyouso                         ; show previously dismissed warnings
```

### 3.16 Registry Extension

```
!reg hivelist                       ; list registry hives
!reg dumppool                       ; registry pool usage
!reg viewlist                       ; registry view list
!reg freebins                       ; free bins in hive
!reg openkeys                       ; open key count
!reg kcb                            ; key control blocks
!reg findkcb                        ; find specific KCB
!reg cellindex                      ; cell index lookup
```

### 3.17 ALPC

```
!alpc /lpp <Process_Addr>           ; ALPC ports for process
!alpc /p <Port_Addr>                ; specific ALPC port
!alpc /m <Message_Addr>             ; ALPC message
```

### 3.18 Power Management

```
!popolicy                           ; power policy
!pocaps                             ; power capabilities
!poaction                           ; power action
!podev                              ; power device list
```

### 3.19 Third-Party Extensions

**SwishDbgExt:**
```
!ms_timers                          ; timer details
!ms_idt                             ; IDT details
!ms_ssdt                            ; SSDT hooks
!ms_gdt                             ; GDT details
!ms_drivers /scan                   ; scan for IRP hooking
```

**ProcDumpExt:**
```
!dpx                                ; process dump extension
!dtr                                ; debug target registers
!msr                                ; model-specific registers
!procdumpext.help                   ; help
```

### 3.20 Dump Commands

```
.dump /mfht c:\Test.dmp             ; mini dump with handles + thread times
.dumpcab -a c:\fulldump             ; create CAB with dump + symbols
.writemem c:\file.dll StartAddr (EndAddr - 0x1)
.writemem c:\file.dll StartAddr L<size>
```

---

## 4. Debugger Data Model (DDM) and dx Queries

The `dx` command provides a structured, LINQ-capable query interface over kernel data.

### 4.1 Basic dx Usage

```
dx @$curprocess                     ; current process
dx @$curthread                      ; current thread
dx -r1 @$curprocess                 ; one-level recursive expansion
dx -r2 @$curprocess                 ; two-level recursive expansion
dx @$proc.DirectoryTableBase        ; field access
dx -r1 @$curprocess.ObjectTable.HandleCount
dx @$thread.Tcb                     ; KTHREAD via thread DDM object
dx @$thread.Tcb.Teb                 ; TEB pointer
dx @$peb                            ; PEB
```

### 4.2 FromListEntry — Walking Kernel Lists

```
; Walk PsActiveProcessHead → EPROCESS.ActiveProcessLinks
dx Debugger.Utility.Collections.FromListEntry(
    (nt!_LIST_ENTRY*)&nt!PsActiveProcessHead,
    "nt!_EPROCESS",
    "ActiveProcessLinks"
)

; Walk process thread list
dx Debugger.Utility.Collections.FromListEntry(
    &@$curprocess.Pcb.ThreadListHead,
    "nt!_ETHREAD",
    "Tcb.ThreadListEntry"
)
```

### 4.3 LINQ Queries on DDM

```
; Filter by PID
dx -r1 Debugger.Utility.Collections.FromListEntry(
    (nt!_LIST_ENTRY*)&nt!PsActiveProcessHead,
    "nt!_EPROCESS", "ActiveProcessLinks"
).Where(p => p.UniqueProcessId == 0x1234)

; Select specific fields
.Where(p => p.UniqueProcessId == 0x1234).Select(p => p.ImageFileName)

; ForEach iteration
dx @$proc.ThreadListHead.Flink.forEach(function(thread) { print(thread.Tcb.Teb); })

; Select with projection
.Select(p => new { p.UniqueProcessId, p.ImageFileName })
```

### 4.4 dx with Natvis Integration

When a Natvis visualizer is loaded, `dx` applies it automatically:

```
dx @$myStdVector                    ; applies Natvis visualizer if loaded
```

---

## 5. LIST_ENTRY Architecture and Debugging

### 5.1 Structure Definition

```c
typedef struct _LIST_ENTRY {
    struct _LIST_ENTRY *Flink;   // Forward link (next)
    struct _LIST_ENTRY *Blink;   // Backward link (previous)
} LIST_ENTRY, *PLIST_ENTRY;
```

- Intrusive doubly-linked circular list
- Head node's Flink points to first element; Blink points to last
- Empty list: `Flink == Blink == ListHead`

### 5.2 CONTAINING_RECORD Macro

```c
#define CONTAINING_RECORD(address, type, field) \
    ((type *)((PCHAR)(address) - (ULONG_PTR)(&((type *)0)->field)))
```

Used to recover the containing structure pointer from a LIST_ENTRY pointer.

### 5.3 Core List API

```c
VOID InitializeListHead(PLIST_ENTRY ListHead);          // sets Flink=Blink=ListHead
BOOLEAN IsListEmpty(PLIST_ENTRY ListHead);              // checks Flink==ListHead
VOID InsertHeadList(PLIST_ENTRY ListHead, PLIST_ENTRY Entry);
VOID InsertTailList(PLIST_ENTRY ListHead, PLIST_ENTRY Entry);
PLIST_ENTRY RemoveHeadList(PLIST_ENTRY ListHead);
PLIST_ENTRY RemoveTailList(PLIST_ENTRY ListHead);
BOOLEAN RemoveEntryList(PLIST_ENTRY Entry);
```

### 5.4 Thread-Safe Variants

```c
// All require PKSPIN_LOCK parameter
ExInterlockedInsertHeadList(PLIST_ENTRY ListHead, PLIST_ENTRY ListEntry, PKSPIN_LOCK Lock);
ExInterlockedInsertTailList(PLIST_ENTRY ListHead, PLIST_ENTRY ListEntry, PKSPIN_LOCK Lock);
PLIST_ENTRY ExInterlockedRemoveHeadList(PLIST_ENTRY ListHead, PKSPIN_LOCK Lock);
```

### 5.5 Lock-Free LIFO (SLIST)

```c
// Requires DECLSPEC_ALIGN(MEMORY_ALLOCATION_ALIGNMENT) on x64 (16-byte alignment)
ExInitializeSListHead(PSLIST_HEADER ListHead);
ExInterlockedPushEntrySList(PSLIST_HEADER ListHead, PSLIST_ENTRY ListEntry, PKSPIN_LOCK Lock);
PSLIST_ENTRY ExInterlockedPopEntrySList(PSLIST_HEADER ListHead, PKSPIN_LOCK Lock);
ExInterlockedFlushSList(PSLIST_HEADER ListHead);
```

### 5.6 Real-World LIST_ENTRY Uses in Windows

| Head | Entry Type | Field Name |
|---|---|---|
| `nt!PsActiveProcessHead` | `_EPROCESS` | `ActiveProcessLinks` |
| `_KPROCESS.ThreadListHead` | `_KTHREAD` | `ThreadListEntry` |
| `_IRP.Tail.Overlay.ListEntry` | `_IRP` | (self) |
| `PEB->Ldr->InMemoryOrderModuleList` | `_LDR_DATA_TABLE_ENTRY` | `InMemoryOrderLinks` |

### 5.7 WinDbg List Traversal Commands

```
; Raw Flink following (type-unaware)
dl <ListHeadAddr> <MaxCount>         ; forward (follow Flink)
dlb <ListHeadAddr> <MaxCount>        ; backward (follow Blink)

; !list extension (executes command for each node)
!list -t <Type.Field> -x "<Command>" <AddressOfHead>
; @$extret pseudo-register = current node address during !list
; Example: iterate EPROCESS list
!list -t nt!_EPROCESS.ActiveProcessLinks -x "dt nt!_EPROCESS @$extret" nt!PsActiveProcessHead

; DDM approach (best — type-aware + LINQ)
dx Debugger.Utility.Collections.FromListEntry(
    (nt!_LIST_ENTRY*)&nt!PsActiveProcessHead, "nt!_EPROCESS", "ActiveProcessLinks"
)
```

### 5.8 List Corruption Detection

**Bug Check 0x139 (KERNEL_SECURITY_CHECK_FAILURE):**
- Arg1 = 3 → "A LIST_ENTRY has been corrupted (double remove)"

```
!validatelist <addr>                ; validate a LIST_ENTRY chain
```

---

## 6. Pool Memory Structures and Commands

### 6.1 Pool Types

| Type | Description |
|---|---|
| Non-paged pool | Always in physical memory; safe at DISPATCH_LEVEL |
| Paged pool | Can be paged out; only safe at PASSIVE/APC_LEVEL |
| Session pool | Per-session allocations |
| Special pool | Debug pool with guard pages on both sides |

### 6.2 Pool Header

```c
// _POOL_HEADER (64-bit, 16 bytes)
typedef struct _POOL_HEADER {
    ULONG PreviousSize : 8;
    ULONG PoolIndex    : 8;
    ULONG BlockSize    : 8;
    ULONG PoolType     : 8;
    ULONG PoolTag;
    union {
        PEPROCESS ProcessBilled;
        struct {
            USHORT AllocatorBackTraceIndex;
            USHORT PoolTagHash;
        };
    };
} POOL_HEADER, *PPOOL_HEADER;
```

**Referenced types:** `_POOL_HEADER`, `_POOL_TYPE`, `_POOL_DESCRIPTOR`

### 6.3 Pool Commands

```
!pool <addr>                        ; dump pool block at address
!pool <addr> 1                      ; suppress other block headers
!pool <addr> 31                     ; suppress type+tag
!poolval <addr> [Level]             ; validate pool block
!poolfind <Tag> [PoolType]          ; find allocations by 4-char tag
                                    ; PoolType: 0=NonPaged, 1=Paged, 2=Special, 4=Session
!poolused                           ; all pool usage by tag
!poolused 1                         ; sort by non-paged usage
!poolused 2                         ; sort by paged usage
!poolused 3                         ; session pool usage
!frag                               ; fragmentation report
!frag 1                             ; with tag details
!pooltag                            ; pool tag database info
```

### 6.4 Kernel Object Sizes in Pool (from PyKD automated measurement)

| Object Type | Pool Size |
|---|---|
| Event | 0x40 |
| Semaphore (unnamed) | 0x48 |
| Semaphore (named) | 0x58 |
| Mutex (unnamed) | 0x50 |
| Mutex (named) | 0x60 |
| IoCompletionReserve | 0x60 |
| IoCompletionPort | 0x98 |
| Job (unnamed) | 0x168 |
| Job (named) | 0x178 |

---

## 7. Synchronization Objects and Commands

### 7.1 KSPIN_LOCK

Raw spinlock acquired at DISPATCH_LEVEL. No WinDbg extension; inspect via:
```
dt nt!_KSPIN_LOCK <addr>
```

### 7.2 ERESOURCE (Executive Resource)

Reader-writer lock. `!locks` extension for these.

```
!locks                              ; list all ERESOURCE locks
!locks -v                           ; verbose (include waiters)
!locks -p                           ; with process info
!locks -d                           ; dump details
dt nt!_ERESOURCE <addr>
```

### 7.3 Critical Sections (_RTL_CRITICAL_SECTION)

User-mode synchronization primitive.

```
!cs                                 ; all critical sections in process
!cs -l                              ; only locked critical sections
!cs -s                              ; with init stack trace
!cs -o                              ; with owner stack trace
!cs -t                              ; tree display
!cs <addr>                          ; specific critical section
!locks                              ; kernel-mode equivalent
dt ntdll!_RTL_CRITICAL_SECTION <addr>
```

**GFlags for CS debugging:**
```
!avrf -cs                           ; Application Verifier CS analysis
```

### 7.4 Other Synchronization Types

```
dt nt!_KEVENT <addr>                ; kernel event
dt nt!_KMUTEX <addr>                ; kernel mutex
dt nt!_KSEMAPHORE <addr>            ; kernel semaphore
dt nt!_DISPATCHER_HEADER <addr>     ; base of all waitable objects
dt nt!_FAST_MUTEX <addr>            ; fast mutex
dt nt!_KWAIT_BLOCK <addr>           ; wait block
dt nt!_ERESOURCE <addr>             ; executive resource
dt nt!_KAPC <addr>                  ; APC object
dt nt!_KAPC_STATE <addr>            ; APC state
dt nt!_GROUP_AFFINITY <addr>        ; group affinity
```

---

## 8. Memory Management Structures and Commands

### 8.1 Key Structures

```
dt nt!_HARDWARE_PTE                 ; hardware page table entry
dt nt!_MMPTE_PROTOTYPE              ; prototype PTE
dt nt!_MMLISTS                      ; page list types
dt nt!_MMPFNENTRY                   ; PFN flags
dt nt!_MMPFN                        ; page frame number entry
dt nt!_MI_SYSTEM_VA_TYPE            ; system VA region types
```

### 8.2 Virtual Address Descriptor (VAD)

Each process has a VAD tree (`VadRoot` in EPROCESS) describing all committed memory regions.

```
!vadump                             ; dump all VAD entries
!vadump -v                          ; verbose (with flags)
dt nt!_MMVAD <addr>                 ; VAD node structure
```

### 8.3 Page Table Inspection

```
!pte <virtual_address>              ; walk page tables for address
!pfn <page_frame>                   ; physical frame database info
!ptov <PFN>                         ; map physical frame to virtual
```

### 8.4 Heap Structures

**Normal heap:**
```
dt ntdll!_HEAP <addr>               ; heap control block
dt ntdll!_HEAP_ENTRY <addr>         ; heap allocation entry
dt ntdll!_HEAP_LOCK <addr>          ; heap lock
dt ntdll!_HEAP_TUNING_PARAMETERS    ; tuning params
```

**Vista+:** `_HEAP_SEGMENT.SegmentListEntry` links additional segments (changed from fixed arrays to doubly-linked lists).

**Page heap (debug):**
```
dt ntdll!_DPH_HEAP_ROOT <addr>      ; page heap root
                                    ; addr = HeapHandle + 0x1000
dt ntdll!_DPH_HEAP_BLOCK <addr>     ; individual block
                                    ; StackTrace at +0x024
                                    ; CreateStackTrace at +0x08c
dt ntdll!_DPH_BLOCK_INFORMATION <addr>
```

---

## 9. I/O and IRP Structures

### 9.1 _IRP Fields (32-bit offsets)

| Offset | Field | Description |
|---|---|---|
| +0x000 | `Type` | Object type |
| +0x002 | `Size` | Total IRP size |
| +0x004 | `MdlAddress` | MDL for direct I/O |
| +0x008 | `Flags` | IRP flags |
| +0x00c | `AssociatedIrp` | Union: SystemBuffer or MasterIrp |
| +0x010 | `ThreadListEntry` | LIST_ENTRY for thread's IRP list |
| +0x018 | `IoStatus` | IO_STATUS_BLOCK |
| +0x018+0x4 | `IoStatus.Information` | Bytes transferred / pointer |
| +0x020 | `RequestorMode` | KernelMode or UserMode |
| +0x021 | `PendingReturned` | Pending flag |
| +0x022 | `StackCount` | Stack location count |
| +0x023 | `CurrentLocation` | Current stack position |
| +0x024 | `Cancel` | Cancellation flag |
| +0x025 | `CancelIrql` | IRQL at cancel |
| +0x026 | `ApcEnvironment` | APC environment |
| +0x027 | `AllocationFlags` | Allocation flags |
| +0x028 | `UserIosb` | User-mode IO status |
| +0x02c | `UserEvent` | User-mode event |
| +0x030 | `Overlay` | Overlay union |
| +0x038 | `CancelRoutine` | Cancel callback |
| +0x03c | `UserBuffer` | User buffer pointer |
| +0x040 | `Tail` | Tail union (includes ListEntry) |

### 9.2 IRP Commands

```
!irp <addr>                         ; display IRP
!irp <addr> 1                       ; detailed
!irpfind                            ; find all IRPs in pool
!irpfind -v                         ; verbose IRP find
!irp @@(Irp)                        ; IRP using C++ address eval
dt nt!_IRP <addr>
dt nt!_IRP <addr> -r1               ; expand one level
```

**Data breakpoint on IRP.IoStatus.Information:**
```
ba w4 <IRP_addr>+0x18+0x4
```

### 9.3 Device/Driver Structures

```
dt nt!_DEVICE_OBJECT <addr>
dt nt!_DRIVER_OBJECT <addr>
dt nt!_MDL <addr>
dt nt!_IO_STATUS_BLOCK <addr>
dt nt!_IO_STACK_LOCATION <addr>
```

---

## 10. Symbol Management

### 10.1 Symbol Path Setup

```
.sympath SRV*d:\DebugSymbols*http://msdl.microsoft.com/download/symbols
.symfix c:\mss                      ; shortcut to MS symbol server
.reload                             ; reload symbols
.reload /f nt                       ; force reload nt symbols
.reload /f /v /i                    ; force, verbose, ignore mismatches
ld *                                ; load all module symbols
```

**Environment variable:**
```
_NT_SYMBOL_PATH=SRV*c:\symbols*http://msdl.microsoft.com/download/symbols
```

### 10.2 Symbol Options

```
.symopt                             ; show current options
.symopt +0x40                       ; SYMOPT_LOAD_ANYTHING (load any matching PDB)
!sym noisy                          ; verbose symbol loading messages
!sym quiet                          ; quiet mode
```

### 10.3 Symbol Verification

```
!lmi <module>                       ; module info: GUID, age, PDB path, symbol type
!chkimg [-f|-v|-d]                  ; verify image vs on-disk copy
!chksym                             ; check symbol correctness
```

**!lmi output fields:**
- Module, Base Address, Image Name, Machine Type, Time Stamp, Size, CheckSum
- CODEVIEW GUID, Age, Pdb filename
- Image Type, Symbol Type, Compiler, Load Report

### 10.4 Symbol Search

```
x nt!*EPROCESS*                     ; search symbols with wildcard
x ntdll!*peb*                       ; search ntdll for peb-related
ln <addr>                           ; nearest symbol to address
```

### 10.5 Incorrect Stack Trace Pattern

Symptom of missing symbols:
```
; Wrong (no symbols):
user32!SfmDxSetSwapChainStats+0x1a
notepad+0x1064

; Correct (with symbols):
user32!GetMessageW+0x34
notepad!WinMain+0x182
```

---

## 11. Crash Dump Types and Collection

### 11.1 Dump Types

| Type | Content | Use Case |
|---|---|---|
| Minidump | Thread stacks, loaded modules, some memory | Small; default for user-mode crashes |
| Kernel dump | All kernel memory (no user pages) | Kernel debugging |
| Complete/Physical dump | All RAM | Full malware/rootkit analysis |
| Kernel minidump | Minimal kernel state | Limited analysis |

> Note: Kernel minidumps excluded from malware analysis training as insufficient.

### 11.2 MINIDUMP_TYPE Flags (MiniDumpWriteDump API)

Key flags for controlling minidump content:
- `MiniDumpNormal` — basic thread/stack info
- `MiniDumpWithFullMemory` — all accessible memory
- `MiniDumpWithHandleData` — open handles
- `MiniDumpWithThreadInfo` — extended thread info
- `MiniDumpWithFullMemoryInfo` — virtual memory info

### 11.3 WER Dump Configuration

**Registry paths:**
```
; Postmortem debugger
HKLM\Software\Microsoft\Windows NT\CurrentVersion\AeDebug

; WER dump settings
HKLM\SOFTWARE\Microsoft\Windows\Windows Error Reporting\LocalDumps
DumpType: 0=custom, 1=mini, 2=full
```

### 11.4 WinDbg Dump Commands

```
.dump /mfht c:\Test.dmp             ; mini dump with handles + thread times
.dump /ma c:\full.dmp               ; full memory dump
.dumpcab -a c:\fulldump             ; CAB with dump + symbols
```

### 11.5 Dump Creation from Command Line

```
.writemem c:\file.dll StartAddr (EndAddr - 0x1)
.writemem c:\file.dll StartAddr L<size>
```

---

## 12. Debugging Scenarios

### 12.1 Access Violation (NULL Dereference)

**Example cause:** `int* i = NULL; *i = 100;`

**Analysis workflow:**
```
!analyze -v                         ; automatic analysis, shows exception code + address
.ecxr                               ; switch to exception context
k                                   ; stack at point of crash
r                                   ; registers (check null pointer in register)
dt nt!_EXCEPTION_RECORD             ; if needed
```

### 12.2 Stack Overflow

**Causes:** Large stack frame allocation, deep recursion

**Indicators:**
- `STATUS_STACK_OVERFLOW` exception
- `STATUS_GUARD_PAGE_VIOLATION` (0x80000001) when guard page hit
- Stack limit reached: `StackBase - StackLimit` = committed; guard page below

```
!analyze -v
!teb                                ; check StackBase and StackLimit
!address <esp>                      ; region usage for stack
dt ntdll!_TEB DeallocationStack <teb_addr>   ; +0xe0c
```

### 12.3 Deadlock

**Cause:** `EnterCriticalSection` without matching `LeaveCriticalSection`; or multiple locks acquired in different orders.

```
!analyze -hang -v                   ; hang analysis
!locks                              ; find locked ERESOURCE
!cs -l                              ; locked critical sections
!deadlock 1                         ; driver verifier deadlock stacks
~* kb                               ; all thread stacks — look for blocked threads
```

### 12.4 High CPU / Infinite Loop

```
!runaway 7                          ; threads sorted by CPU time
!analyze -hang -v
~<thread>s                          ; switch to top CPU thread
k                                   ; stack of burning thread
```

### 12.5 Memory Leak

```
!address -summary                   ; overall allocation summary
!heap -stat -h 0                    ; default heap statistics
!heap -flt s <suspect_size>         ; filter to size
!heap -p -a <addr>                  ; allocation + stack trace
dt ntdll!_DPH_HEAP_BLOCK StackTrace <block_addr>
dds <StackTrace_addr>               ; resolve creation stack
gflags.exe /i IMAGE.EXE +ust +hpa   ; enable stack tracing
```

### 12.6 Handle Leak

```
!handle                             ; all handles in process
!handle 0 3                         ; with object info
dt nt!_OBJECT_HEADER <addr>
```

### 12.7 Kernel Crash (Bug Check)

```
!analyze -v                         ; decode bug check code + params
.trap <addr>                        ; set to trap frame
k                                   ; stack at crash point
!irql                               ; check IRQL
!pool <addr>                        ; if pool-related
```

### 12.8 Code Injection Analysis

**Indicators in memory:**
- PE headers in unexpected process memory regions
- Memory regions with PAGE_EXECUTE_READWRITE
- Loaded module list vs actual memory-mapped modules mismatch

**Analysis commands:**
```
!process <addr> 1                   ; get module list
lm                                  ; loaded modules
!vadump -v                          ; full VAD — check for suspicious regions
!address -summary                   ; summary shows exe/heap/stack/mapped breakdown
!chkimg <module>                    ; detect in-memory patching vs disk
```

### 12.9 Complete Memory Dump First-Order Analysis Script

For complete/physical dumps, run batch of commands to log file then analyze:
```
.logopen c:\analysis.log
!process 0 0
!vm
!handle 0 5
!locks
!pool
.logclose
```

---

## 13. PyKD API Reference

### 13.1 Installation and Loading

```python
# Install
pip install pykd

# Load in WinDbg
.load pykd
# or
.load pykd.pyd

# Extension search paths
# C:\Program Files (x86)\Windows Kits\10\Debuggers\x64\winext
# or _NT_DEBUGGER_EXTENSION_PATH environment variable
```

### 13.2 Running Scripts

```
!py script.py                       ; run script
!py -g script.py                    ; global namespace
!py --local script.py               ; isolated namespace
!py -m script.py                    ; as __main__
```

### 13.3 Core API

**Executing commands:**
```python
result = pykd.dbgCommand("!process 0 0")  # returns string output
```

**Register access:**
```python
rip = pykd.reg("rip")              # returns integer value
rax = pykd.reg("rax")
```

**Memory access (read):**
```python
pykd.loadBytes(addr, count)         # returns list of bytes
pykd.loadDWords(addr, count)        # returns list of DWORDs
pykd.loadQWords(addr, count)        # returns list of QWORDs
pykd.loadCStr(addr)                 # null-terminated ASCII string
pykd.loadUnicodeStr(addr)           # UNICODE_STRING
pykd.loadPtrs(addr, num)            # list of pointer-sized values
```

**Memory access (write):**
```python
pykd.setByte(addr, val)
pykd.setDWord(addr, val)
pykd.setFloat(addr, val)
```

**Execution control:**
```python
pykd.go()                           # g
pykd.trace()                        # t (step into)
pykd.step()                         # p (step over)
pykd.setIP(address)                 # set RIP/EIP
```

**MSR access:**
```python
val = pykd.rdmsr(msr_address)
pykd.wrmsr(msr_address, value)
```

### 13.4 Breakpoints

```python
# Software breakpoint
bp = pykd.setBp(offset)
bp = pykd.setBp(offset, callback_fn)

# Hardware breakpoint
bp = pykd.setBp(offset, size, accessType)
bp = pykd.setBp(offset, size, accessType, callback_fn)

# Remove
pykd.removeBp(bp_id)
pykd.removeAllBp()
```

### 13.5 Structural Parsing

```python
# Type metadata (offsets, layout)
ti = pykd.typeInfo("nt!_UNICODE_STRING")
ti = pykd.typeInfo("nt!_OB_CALLBACK_REGISTRATION")
offset = ti.fieldOffset("SomeField")  # dynamic CONTAINING_RECORD

# Live typed variable (instance + symbol access)
var = pykd.typedVar("nt!_OB_CALLBACK_REGISTRATION", address)
addr = var.OperationRegistration.Altitude.getAddress()
# Access nested fields via dot notation

# Performance note:
# typedVar is ~3x faster than dbgCommand() + regex parsing
```

**CONTAINING_RECORD in Python:**
```python
# Use typeInfo.fieldOffset() to compute base from Flink address
ti = pykd.typeInfo("nt!_EPROCESS")
offset = ti.fieldOffset("ActiveProcessLinks")
eprocess_base = flink_addr - offset
```

### 13.6 Event Handlers

```python
class MyHandler(pykd.eventHandler):
    def onException(self, exceptInfo):
        if exceptInfo.exceptionCode == 0x80000001:  # guard page violation
            # handle it
            return pykd.eventResult.NoChange   # resume execution
        return pykd.eventResult.Handled

handler = MyHandler()
pykd.go()
```

### 13.7 Token Stealing (Kernel Exploit Example via PyKD)

```python
# 1. Walk ActiveProcessLinks to find SYSTEM process (PID 4)
# 2. Extract Token from EPROCESS._EX_FAST_REF (mask off low 4 bits)
# 3. Write SYSTEM token to target process's Token field

eprocess_ti = pykd.typeInfo("nt!_EPROCESS")
links_offset = eprocess_ti.fieldOffset("ActiveProcessLinks")
pid_offset = eprocess_ti.fieldOffset("UniqueProcessId")
token_offset = eprocess_ti.fieldOffset("Token")

# Walk list from PsActiveProcessHead
head = pykd.getSymbolOffset("nt!PsActiveProcessHead")
# ... iterate, find PID 4, get Token, write to target
```

### 13.8 Bugcheck Callbacks (PyKD)

```
KbCallbackAddPages              ; add pages to dump
KbCallbackSecondaryDumpData     ; secondary dump data
KbCallbackRemovePages           ; remove pages from dump
```

**Flags:**
```
KB_REMOVE_PAGES_FLAG_VIRTUAL_ADDRESS    = 0x1
KB_REMOVE_PAGES_FLAG_PHYSICAL_ADDRESS   = 0x2
KB_REMOVE_PAGES_FLAG_ADDITIONAL_RANGES_EXIST = 0x80000000
```

---

## 14. Natvis Framework Reference

### 14.1 File Structure

```xml
<AutoVisualizer xmlns="http://schemas.microsoft.com/vstudio/debugger/natvis/2010">
  <Type Name="Namespace::ClassName" Optional="true" Priority="MediumHigh" Inheritable="true">
    <DisplayString Condition="optional_condition">
      literal text {member,specifier} more text
    </DisplayString>
    <Expand HideRawView="true">
      <!-- expansion nodes -->
    </Expand>
  </Type>
</AutoVisualizer>
```

**Priority values (highest to lowest):** High, MediumHigh, Medium (default), MediumLow, Low

### 14.2 Expansion Node Types

**Simple item:**
```xml
<Item Name="label" Condition="condition" Optional="true">expression,specifier</Item>
```

**Array:**
```xml
<ArrayItems>
  <Size>count_expression</Size>
  <ValuePointer>pointer_expression</ValuePointer>
</ArrayItems>
```

**Linked list:**
```xml
<LinkedListItems>
  <HeadPointer>head_pointer_expr</HeadPointer>
  <NextPointer>next_field</NextPointer>
  <ValueNode>value_expression</ValueNode>
</LinkedListItems>
```

**Tree:**
```xml
<TreeItems>
  <HeadPointer>...</HeadPointer>
  <LeftPointer>left_field</LeftPointer>
  <RightPointer>right_field</RightPointer>
  <ValueNode>value_expr</ValueNode>
</TreeItems>
```

**Custom (scripted):**
```xml
<CustomListItems>
  <Variable Name="i" InitialValue="0"/>
  <Loop Condition="i &lt; size">
    <Item>arr[i]</Item>
    <Exec>i++</Exec>
  </Loop>
</CustomListItems>
```

### 14.3 Format Specifiers

| Specifier | Meaning |
|---|---|
| `d` | Signed decimal |
| `o` | Octal |
| `x` | Hex lowercase |
| `X` | Hex uppercase |
| `c` | Character |
| `s` | ASCII string |
| `su` | Unicode/wchar_t string |
| `s8` | UTF-8 string |
| `sb` | Unquoted string |
| `b` | Binary |
| `f` | Float |
| `e` | Scientific notation |
| `g` | General float |
| `wc` | Wide char |
| `wm` | Windows message name |
| `[ptr]` | Show address |
| `na` | No address |
| `hr` | HRESULT decode |
| `en` | Enum name |
| `![flag]` | Bitfield flag |
| `[N]` | N elements |
| `nd` | No derived (static type only) |
| `,!` | Raw mode (bypass Natvis) |

### 14.4 Loading Natvis Files

```
.nvload <FileName>                  ; load explicit .natvis file
.nvload <ModuleName>                ; load from PDB-embedded Natvis
.nvlist                             ; list loaded Natvis files
.nvunload <FileName or ModuleName>  ; unload specific
.nvunloadall                        ; unload all
```

**Priority order (highest first):**
1. `.nvload` explicit load
2. PDB-embedded Natvis
3. User directory (`%LOCALAPPDATA%\dbg\Visualizers`)
4. System directory

**Embed in PDB via linker:**
```
/NATVIS:filename.natvis
```

### 14.5 Natvis Expressions

- Evaluated as C++ subset
- `this` = current object being visualized
- No side-effect function calls
- No local variable access
- Debugger intrinsic functions are allowed
- Format specifiers after comma inside `{}`

**WinDbg Preview note:** Use `%LOCALAPPDATA%\dbg\Visualizers` (not the classic Visualizers folder).

---

## 15. Bug Check Codes and Analysis

### 15.1 Common Bug Check Codes

| Code | Name | Description |
|---|---|---|
| 0x0A | IRQL_NOT_LESS_OR_EQUAL | Invalid memory access at wrong IRQL |
| 0x1E | KMODE_EXCEPTION_NOT_HANDLED | Unhandled kernel exception |
| 0x3B | SYSTEM_SERVICE_EXCEPTION | Exception in system service |
| 0x50 | PAGE_FAULT_IN_NONPAGED_AREA | NULL/bad ptr access in nonpaged code |
| 0x7E | SYSTEM_THREAD_EXCEPTION_NOT_HANDLED | Thread exception not handled |
| 0x7F | UNEXPECTED_KERNEL_MODE_TRAP | Double fault, etc. |
| 0x93 | INVALID_KERNEL_HANDLE | Closed/invalid handle used |
| 0xA | (see 0x0A above) | |
| 0x100 | LOADER_BLOCK_MISMATCH | Boot loader mismatch |
| 0x101 | CLOCK_WATCHDOG_TIMEOUT | CPU not responding to clock |
| 0x124 | WHEA_UNCORRECTABLE_ERROR | Hardware error (MCA, PCIe) |
| 0x133 | DPC_WATCHDOG_VIOLATION | DPC took too long |
| 0x139 | KERNEL_SECURITY_CHECK_FAILURE | Stack corruption or LIST_ENTRY corruption |
| 0x13A | KERNEL_MODE_HEAP_CORRUPTION | Heap corruption in kernel |

**0x139 Argument meanings:**
| Arg1 | Meaning |
|---|---|
| 1 | GS cookie check failed (stack buffer overrun) |
| 2 | Stack variable around buffer corrupted |
| 3 | LIST_ENTRY corrupted (double remove) |
| 4 | Reserved for future |

### 15.2 WHEA Structures

```
!whea                               ; WHEA overview
!errpkt <addr>                      ; error packet
!errrec <addr>                      ; error record
dt nt!_WHEA_ERROR_RECORD
dt nt!_WHEA_ERROR_RECORD_HEADER
dt nt!_WHEA_ERROR_RECORD_HEADER_VALIDBITS
dt nt!_WHEA_TIMESTAMP
dt nt!_WHEA_ERROR_SOURCE_TYPE
dt nt!_WHEA_ERROR_PACKET
```

---

## 16. EDR Kernel Callbacks and Security Internals

### 16.1 Kernel Callback APIs

```c
// Process creation (modern)
PsSetCreateProcessNotifyRoutineEx2(
    PsCreateProcessNotifySubsystems,  // type
    callback_fn,                       // PCREATE_PROCESS_NOTIFY_ROUTINE_EX
    FALSE                              // remove=FALSE to register
);

// Thread creation
PsSetCreateThreadNotifyRoutineEx(
    PsCreateThreadNotifyNonSystem,
    callback_fn
);

// Image load
PsSetLoadImageNotifyRoutineEx(callback_fn, PS_IMAGE_NOTIFY_ALL_PROCESSES);

// Object (handle) callbacks
ObRegisterCallbacks(&CallbackRegistration, &RegistrationHandle);
// Used for process/thread handle access control

// Registry callbacks
CmRegisterCallbackEx(&CallbackFn, &Altitude, DriverObject, &Cookie);
```

### 16.2 ETW-Ti (ETW Threat Intelligence)

Provider GUID for ETW-Ti events (TI = Threat Intelligence):

**Key events:**
- `EtwTiLogReadWriteVm` — triggered when executable memory allocated
- `EtwTiLogSetContextThread` — triggered when thread context modified (SetThreadContext)

**Access requirement:** Process must have PPL (Protected Process Light) + ELAM certificate.

### 16.3 BYOVD (Bring Your Own Vulnerable Driver)

Attack pattern: load legitimate but vulnerable signed driver, exploit it to:
1. Traverse kernel structures
2. Find `PsSetCreateProcessNotifyRoutine` callback array
3. Zero out registered EDR callbacks

**Detection approach:**
- Monitor driver load events
- Check callback arrays for unexpected null entries
- Use kernel sensor with ETW-Ti to detect callback manipulation

### 16.4 Adversarial Techniques (from Windows Internals Guide)

**Direct Syscalls:**
- Place SSN in EAX
- Execute `syscall` instruction directly from shellcode
- Bypasses user-mode API hooks (ntdll hooks)

**Indirect Syscalls:**
- Prepare registers as normal
- Jump to `syscall;ret` sequence inside legitimate ntdll
- Preserves call stack appearance of coming from ntdll

**Call Stack Spoofing:**
- Use ROP gadgets to forge stack frames
- Makes kernel callbacks and ETW-Ti see fake call stacks

**Early-Bird Injection:**
- `CreateProcess` with `CREATE_SUSPENDED`
- Write shellcode to process memory
- Queue APC via `NtQueueApcThread`
- Resume thread — shellcode runs before main entry point

**Hardware Breakpoint Evasion:**
- Set DR0-DR7 debug registers via `NtSetContextThread`
- Register VEH (Vectored Exception Handler)
- On breakpoint hit in VEH, call `NtContinue` with modified context
- Bypasses ETW-Ti `EtwTiLogSetContextThread` monitoring

### 16.5 System Call Dispatch Internals

```
; User mode:
mov eax, <SSN>          ; system service number
syscall                  ; transfers to KiSystemCall64

; Kernel mode entry:
; LSTAR MSR = KiSystemCall64 address
; KiSystemCall64 constructs _KTRAP_FRAME on kernel stack
; Sets PreviousMode = UserMode
; Dispatches via SSDT (System Service Descriptor Table)
```

**Read LSTAR MSR with PyKD:**
```python
lstar = pykd.rdmsr(0xC0000082)      # IA32_LSTAR = KiSystemCall64
```

---

## 17. Pseudo-Registers and Scripting

### 17.1 Built-in Pseudo-Registers

| Register | Description |
|---|---|
| `$teb` | Current thread TEB address |
| `$peb` | Current process PEB address |
| `$ip` | Instruction pointer (EIP/RIP) |
| `$retreg` | Return register (EAX/RAX) |
| `$csp` | Stack pointer (ESP/RSP) |
| `$ra` | Return address |
| `$tpid` | Current thread's PID |
| `$tid` | Current thread ID |
| `$exentry` | Executable entry point |
| `$ptrsize` | Pointer size (4 or 8) |
| `$pagesize` | Page size (usually 0x1000) |
| `$extret` | Return value in `!list` commands |

### 17.2 User-Defined Pseudo-Registers

```
$t0 through $t19                    ; user scratch registers
r? $t0 = @$peb->ProcessParameters  ; assign typed value
```

### 17.3 Scripting Constructs

```
; Conditional
.if (<condition>) { commands } .else { commands }
j <condition> 'true_cmds'; 'false_cmds'

; Loop
z(<condition>)                      ; loop while condition true

; Foreach
.foreach /pS 5 /ps 5 (token {<cmd>}) { <body_cmd> }
.foreach (val {dd MyAddr L4}) { dd @val }

; Shell command
.shell <cmd>                        ; run cmd.exe command

; Nested command file
$<                                  ; execute commands from file
```

---

## 18. Malware Memory Analysis Patterns

### 18.1 Analysis Philosophy

Memory dump analysis = analysis of textual output for patterns. Approach:
1. Run commands → examine output
2. When something suspicious found → run more targeted commands
3. Use checklists for systematic coverage
4. For complete dumps: batch commands into log file, then analyze

**Key insight:** Malware patterns = intentional abnormal structure/behavior. May overlap with:
- Unintentional software defects
- Intentional non-malicious behavior (value-adding hooks, code patching)

### 18.2 Process Memory Dump Types for Malware Analysis

| Dump Type | Value for Malware Analysis |
|---|---|
| Process dump | User-space injection, PE headers, hooks |
| Kernel dump | Kernel-mode rootkits, callback tampering, DKOM |
| Complete/Physical dump | Full picture; best for advanced rootkits |
| Kernel minidump | Usually insufficient — rarely useful |

### 18.3 Malware Indicators Checklist

**Process anomalies:**
```
!process 0 0                        ; look for: unexpected process names,
                                    ; PID/PPID mismatches, unusual parent processes
lm                                  ; modules in process — look for:
                                    ; unsigned/unsigned DLLs, unexpected paths
!vadump -v                          ; look for: PAGE_EXECUTE_READWRITE regions,
                                    ; regions with no backing image file
```

**Code injection:**
```
; Check for PE headers outside module list
s -d 0x1000 L?0x7fffffff 0x00905a4d  ; search for MZ (PE header) in user space
; Check !vadump for committed executable non-image memory
```

**Hook detection:**
```
!chkimg <module>                    ; compare in-memory vs on-disk
!ms_ssdt                            ; SSDT hook check (SwishDbgExt)
!ms_drivers /scan                   ; IRP hook check (SwishDbgExt)
```

**Kernel-mode rootkit indicators:**
```
; DKOM (Direct Kernel Object Manipulation): process hidden from list
; Check by walking PsActiveProcessHead vs by checking pool for EPROCESS tags
!pool 0 4                           ; look for Proc tags (process objects)
```

### 18.4 Exercise Approach (from Malware Analysis Course)

**Setup for all exercises:**
```
.symfix c:\mss                      ; set symbol path
.reload                             ; load symbols
k                                   ; verify stack trace correctness
```

**M1A/M1B — PE Header Analysis:**
- Load EXE/DLL as dump in WinDbg (File → Open Crash Dump → select .exe)
- Examine PE headers with `!dh`, `lm`, `!lmi`
- Look for: unusual export names, no version info (_Unknown Module_ pattern)

**Address space quick reference:**
- 32-bit process: 0x00000000–0x7FFFFFFF (user), 0x80000000–0xFFFFFFFF (kernel)
- 32-bit /3GB: 0x00000000–0xBFFFFFFF (user, with /3GB boot.ini switch)
- 64-bit process: much larger user space; many DLLs above 2 GB

### 18.5 First-Order Analysis Script (Complete Memory Dumps)

```
; Save as script.wds, run with: $<script.wds
.logopen c:\malware_analysis.log
vertarget
!running -ti
!process 0 0
!vm
!memusage 8
!locks
!irql
.logclose
```

---

## 19. Debug Session Setup and Attachment Modes

### 19.1 Invasive vs. Non-Invasive Attachment

**Invasive attach** (default):
- Calls `DebugActiveProcess` — creates a break-in thread in the target
- Only one invasive debugger can attach at a time
- Prior to Windows XP: target is killed on debugger exit or detach
- Required for setting breakpoints and stepping

**Non-invasive attach** (`.attach -noninvasive <PID>` or WinDbg → Attach with non-invasive):
- Calls `OpenProcess` — no break-in thread, all target threads frozen
- Can examine and change memory, but cannot set breakpoints or step
- Target survives debugger exit/detach
- Multiple non-invasive debuggers can attach simultaneously (+ one invasive)
- Useful when: VS is already invasively debugging the target, or the target is frozen and cannot launch a break-in thread

```
.attach <PID>                       ; invasive attach to running process
.attach -noninvasive <PID>          ; non-invasive attach
.detach                             ; detach from process
.kill                               ; terminate target
```

### 19.2 Exception Dispatching Order

When an exception occurs, Windows dispatches it in this fixed order:

1. **First-chance notification** — the system notifies the attached debugger first. In WinDbg, the exception appears as a first-chance exception. The debugger can handle it (`gh` = Go with Exception Handled) or pass it through (`gn` = Go with Exception Not Handled).

2. **Frame-based exception handlers** — if the debugger passes or no debugger is attached, the system walks the stack searching for SEH `__try/__except` blocks that will handle the exception.

3. **Second-chance notification** — if no frame handler catches it, the debugger receives a second (last) chance. If the debugger does not handle it here, the process will terminate.

4. **AeDebug (postmortem debugger)** — if no debugger is attached or the second-chance is unhandled, the postmortem debugger specified in AeDebug is launched.

**WinDbg exception commands:**
```
gh                                  ; Go with Exception Handled (consumes exception)
gn                                  ; Go with Exception Not Handled (passes to SEH)
gN                                  ; Go with Exception Not Handled (same as gn)
.lastevent                          ; show the last exception/event details
.exr -1                             ; show the most recent exception record
.ecxr                               ; switch context to the exception context record
dt nt!_EXCEPTION_RECORD <addr>      ; dump exception record
```

**Exception filter commands:**
```
sxe <event>                         ; break on exception (first chance)
sxd <event>                         ; disable break (second chance only)
sxi <event>                         ; ignore exception
sxn <event>                         ; notify but do not break
sx                                  ; list all exception filter settings
```

**Common exception codes:**
| Code | Name |
|---|---|
| `0xC0000005` | Access Violation |
| `0xC0000034` | Object Name Not Found |
| `0xC000001D` | Illegal Instruction |
| `0x80000001` | Guard Page Violation |
| `0xC00000FD` | Stack Overflow |
| `0xC0000409` | Stack Buffer Overrun (GS cookie) |
| `0xE06D7363` | C++ Exception (0x'msc') |

### 19.3 AeDebug — Postmortem Debugging

Controls which debugger is invoked when an unhandled exception terminates a process.

**Registry key:**
```
HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion\AeDebug
  Debugger = "windbg.exe -p %ld -e %ld -g"
  Auto     = 1  (1=attach automatically, 0=prompt user first)
```

**Install WinDbg as postmortem debugger:**
```
windbg.exe -I                       ; registers WinDbg as AeDebug debugger
drwtsn32.exe -i                     ; register Dr. Watson (legacy)
```

No validation is made that the program specified in `AeDebug` is actually a debugger — any executable can be specified.

### 19.4 Source Paths

```
.srcpath <path>                     ; set source search path
.srcpath+ <path>                    ; append to source path
.srcnoisy 1                         ; verbose source file search
.srcnoisy 0                         ; quiet source search
```

**Environment variable:**
```
_NT_SOURCE_PATH=C:\Sources
```

Source files are found by:
1. Original build location (embedded in PDB)
2. `_NT_SOURCE_PATH` / `.srcpath` directories
3. Source server (if PDB has source indexing)

### 19.5 WinDbg Workspaces

Workspaces save symbol paths, source paths, window layout, and breakpoints.

```
; Save workspace from menu: File → Save Workspace As
; Load workspace from command line:
windbg.exe -W <WorkspaceName> -k 1394:channel=1
windbg.exe -y SRV*d:\symbols*http://msdl.microsoft.com/download/symbols -W MyWorkspace
```

### 19.6 PE Header Inspection

```
!dh <module>                        ; display PE headers (file + optional + sections)
!dh <addr>                          ; PE headers at memory address
!lmi <module>                       ; summary: GUID, PDB path, symbol type, load report
lm vm <module>                      ; verbose module info: timestamp, checksum, version
!imgreloc                           ; display relocation info for all modules
dd <module_name> L1                 ; module base (shows MZ: 00905a4d)
```

**`!dh` output includes:**
- Machine type, number of sections, timestamp
- Optional header: magic, image base, entry point, stack/heap reserves
- Section headers: name, virtual size, virtual address, characteristics
- Import/Export/Resource directory addresses and sizes

---

## 20. x64 Architecture and Calling Convention

### 20.1 x64 General-Purpose Registers

| Register | Role | Preserved? |
|---|---|---|
| `RAX` | Return value, accumulator | No (volatile) |
| `RBX` | General purpose | Yes (non-volatile) |
| `RCX` | Arg 1 (integer/pointer) | No |
| `RDX` | Arg 2 (integer/pointer) | No |
| `R8` | Arg 3 (integer/pointer) | No |
| `R9` | Arg 4 (integer/pointer) | No |
| `RSP` | Stack pointer | Yes |
| `RBP` | Frame pointer (optional) | Yes |
| `RSI` | General purpose | Yes |
| `RDI` | General purpose | Yes |
| `R10`, `R11` | Scratch | No |
| `R12`–`R15` | General purpose | Yes |
| `XMM0`–`XMM3` | FP args 1–4 | No |
| `XMM4`–`XMM5` | FP scratch | No |
| `XMM6`–`XMM15` | FP general | Yes |

### 20.2 x64 Windows Calling Convention (Microsoft ABI)

- **First 4 integer/pointer args**: RCX, RDX, R8, R9 (left to right)
- **First 4 float/double args**: XMM0, XMM1, XMM2, XMM3
- **Additional args**: pushed right-to-left on stack
- **Caller** allocates a 32-byte "shadow space" (home space) on stack before call, even if callee uses no stack args
- **Stack must be 16-byte aligned** at point of `call` instruction
- **Return value**: RAX (integer) or XMM0 (float)
- **Caller cleans stack** (no `stdcall` style auto-cleanup in x64)

### 20.3 x64 Stack Layout at Function Entry

```
; Stack layout at function entry (after prologue allocates locals):
; [RSP+0x00] - return address (pushed by CALL)
; [RSP+0x08] - shadow space slot for RCX (arg 1 home)
; [RSP+0x10] - shadow space slot for RDX (arg 2 home)
; [RSP+0x18] - shadow space slot for R8  (arg 3 home)
; [RSP+0x20] - shadow space slot for R9  (arg 4 home)
; [RSP+0x28] - 5th arg (if any), then 6th...
; RSP must remain 16-byte aligned throughout the function
```

**WinDbg: examine x64 function arguments:**
```
r rcx, rdx, r8, r9                  ; first 4 args at call site
dq rsp L8                           ; stack dump including shadow space
kP                                  ; stack with full parameter names (requires PDB)
```

### 20.4 Function Prolog and Epilog Patterns

**Debug build prolog:**
```asm
push    rbp
mov     rbp, rsp
sub     rsp, 0x30                   ; allocate locals + alignment
```

**Optimized (no frame pointer):**
```asm
sub     rsp, 0x28                   ; shadow space only, no frame pointer saved
```

**Epilog:**
```asm
add     rsp, 0x28                   ; or: mov rsp, rbp
pop     rbp                         ; if frame pointer used
ret
```

### 20.5 x64 Disassembly Patterns in WinDbg

```
uf <func>                           ; full function disassembly
uf /c <func>                        ; with call annotations
uf /D <func>                        ; DML format (clickable calls)
u rip                               ; disassemble at current instruction
u rip L20                           ; 32 instructions from current RIP
r rip = <addr>                      ; manually set instruction pointer
```

**Identify args before a CALL:**
```
; Before "call target":
; RCX = arg1, RDX = arg2, R8 = arg3, R9 = arg4
; Additional args at [RSP+0x20], [RSP+0x28], ...
```

---

## 21. Additional Commands and Patterns

### 21.1 Assemble Command

```
a <addr>                            ; enter assembly mode at address
; Then type instructions; blank line exits
a @rip                              ; assemble at current instruction pointer
```

### 21.2 Watch Trace

```
wt                                  ; watch trace: count instructions executed per function
wt -l 3                             ; limit call depth to 3
wt -nc                              ; no call/return display, summary only
wt -oa                              ; show actual return values
```

`wt` steps until the current function returns, displaying a tree of called functions and instruction counts. Useful for identifying hot code paths or unexpected call chains.

### 21.3 Pattern Search in Disassembly

```
#<pattern> <addr>                   ; search for pattern in disassembly starting at addr
#call <addr>                        ; find next CALL instruction
#ret                                ; find next RET instruction
#<pattern>                          ; continue search from last position
```

### 21.4 Memory Search

```
s -b <range_start> L<len> <bytes>   ; search for byte pattern
s -a <range_start> L<len> "string"  ; search for ASCII string
s -u <range_start> L<len> "string"  ; search for Unicode string
s -d <range_start> L<len> <dword>   ; search for DWORD value
s -q <range_start> L<len> <qword>   ; search for QWORD value

; Example: search for MZ header (PE) in user space
s -d 0x1000 L?0x7fffffff 0x00905a4d

; Example: search for ASCII string in a module
s -a ntdll L0x100000 "ntdll"
```

### 21.5 DML (Debugger Markup Language)

DML adds hyperlink-style interactivity to WinDbg output — click to run associated commands.

```
.prefer_dml 1                       ; enable DML globally
.dml_start                          ; start DML session
.help /D a*                         ; help with DML links for commands starting with 'a'
.chain /D                           ; extensions list with DML links
lmD                                 ; module list with DML links (clickable → lm vm)
kM                                  ; stack trace with DML links (frame → dv, .frame)
```

### 21.6 Breakpoint Refinements

```
.bpsync 1                           ; stop all threads when any breakpoint is hit
.bpsync 0                           ; only stop thread that hit the breakpoint
bp /1 <addr>                        ; one-shot breakpoint (auto-deletes after hit)
bp <addr> "r; g"                    ; log registers and continue (non-breaking BP)
bp <addr> ".if (@rax != 0) {} .else { k; g }"  ; conditional: break only on rax=0
bu <module>!<func>                  ; deferred breakpoint (set before module loads)
bm <module>!*alloc*                 ; breakpoint on all symbols matching pattern
```

### 21.7 Thread Breakpoint Isolation

```
bp /p <EPROCESS_addr> <addr>        ; break only when executing in specific process
bp /t <ETHREAD_addr> <addr>         ; break only on specific thread
~<n> bp <addr>                      ; set breakpoint active only for thread n
```

### 21.8 Extension DLL Reference

| Extension DLL | Help Command | Coverage |
|---|---|---|
| `exts.dll` | `!exts.help` | General extensions |
| `uext.dll` | `!uext.help` | User-mode (non-OS-specific) |
| `ntsdexts.dll` | `!ntsdexts.help` | User-mode (OS-specific) |
| `kdexts.dll` | `!kdexts.help` | Kernel-mode extensions |
| `logexts.dll` | `!logexts.help` | Logger extensions |
| `sos.dll` | `!sos.help` | Managed (.NET) debugging |
| `wow64exts.dll` | `!wow64exts.help` | WOW64 debugging |

```
.chain                              ; list all currently loaded extension DLLs
.load <path\ext.dll>                ; load extension DLL
.unload <ext>                       ; unload extension DLL
.extmatch /D *                      ; DML: list all extension commands
```

---

## Appendix: Key Data Structure Cross-Reference

| Structure | Module | Key Extension | Key Relation |
|---|---|---|---|
| `_EPROCESS` | nt | `!process` | Contains _KPROCESS, PEB, Token, VadRoot |
| `_KPROCESS` | nt | `!process` | First member of _EPROCESS; has ThreadListHead |
| `_ETHREAD` | nt | `!thread` | Contains _KTHREAD, TEB pointer, ClientId |
| `_KTHREAD` | nt | `!thread` | First member of _ETHREAD; has APC, WaitBlock |
| `_PEB` | ntdll | `!peb` | UserMode; has Ldr, ProcessParameters, BeingDebugged |
| `_TEB` | ntdll | `!teb` | Per-thread usermode; StackBase, StackLimit, LastError |
| `_KPCR` | nt | `!pcr` | Per-processor; contains _KPRCB |
| `_KPRCB` | nt | `!prcb` | Per-processor; scheduling, DPC queue |
| `_OBJECT_HEADER` | nt | `!object` | Precedes all kernel objects |
| `_OBJECT_TYPE` | nt | `!object` | Describes type of kernel object |
| `_TOKEN` | nt | `!token` | Security token; in EPROCESS.Token (_EX_FAST_REF) |
| `_KTRAP_FRAME` | nt | `.trap` | Saved user state at exception/syscall |
| `_DISPATCHER_HEADER` | nt | — | First member of all waitable objects |
| `_KWAIT_BLOCK` | nt | — | Links thread → object being waited on |
| `_POOL_HEADER` | nt | `!pool` | Precedes each pool allocation |
| `_IRP` | nt | `!irp` | I/O Request Packet; has IoStatus, stack locations |
| `_DEVICE_OBJECT` | nt | `!devobj` | Device object in device stack |
| `_DRIVER_OBJECT` | nt | `!drvobj` | Driver registration info |
| `_HEAP` | ntdll | `!heap` | Heap control block (user mode) |
| `_DPH_HEAP_ROOT` | ntdll | `!heap -p` | Page heap root at HeapHandle+0x1000 |
| `_RTL_CRITICAL_SECTION` | ntdll | `!cs` | User-mode critical section |
| `_ERESOURCE` | nt | `!locks` | Kernel reader-writer lock |
| `_KDPC` | nt | `!dpcs` | Deferred Procedure Call |
| `_KTIMER` | nt | `!timer` | Kernel timer |
| `_KAPC` | nt | — | APC object |
| `_HARDWARE_PTE` | nt | `!pte` | Hardware page table entry |
| `_MMPFN` | nt | `!pfn` | Page Frame Number database entry |
| `LIST_ENTRY` | nt | `dl`, `!list` | Universal doubly-linked list node |

---

**Sources and Verification**

All structure layouts can be independently verified using Microsoft's free public symbols:

```
; Configure the Microsoft Symbol Server in WinDbg
.sympath srv*C:\Symbols*https://msdl.microsoft.com/download/symbols
.reload

; Verify any structure
dt nt!_EPROCESS
dt nt!_IRP
dt nt!_KDPC
```

Key public references:
- WinDbg docs: https://learn.microsoft.com/en-us/windows-hardware/drivers/debugger/
- WDK API reference: https://learn.microsoft.com/en-us/windows-hardware/drivers/
- PyKD (open source): https://github.com/ivellioscolin/pykd
- Natvis docs: https://learn.microsoft.com/en-us/visualstudio/debugger/create-custom-views-of-native-objects

*These are independent study notes. Any resemblance in structure to published works reflects the underlying subject matter — the Windows debugging ecosystem — not reproduction of any copyrighted text.*
