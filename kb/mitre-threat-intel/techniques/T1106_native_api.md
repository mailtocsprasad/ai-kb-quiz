---
technique_id: T1106
technique_name: Native API
tactic: [Execution]
platform: Windows
severity: High
data_sources: [ETWTI, ETW-Process, ETW-Memory]
mitre_url: https://attack.mitre.org/techniques/T1106/
---

# T1106 — Native API

## Description (T1106)

T1106 Native API covers the use of Windows Native API functions — those exported from `ntdll.dll` and accessible via system call numbers — to execute malicious operations while bypassing higher-level Win32 API hooks and monitoring. Many EDR solutions instrument Win32 APIs by patching the prologue of functions in Win32 subsystem DLLs or in ntdll.dll itself. Native API abuse can circumvent these hooks by invoking system calls directly, loading an unhooked copy of ntdll.dll, or using the WoW64 transition thunk (Heaven's Gate) to transition from 32-bit to 64-bit execution mode.

The term "native API" in this context refers to the NT native layer: functions prefixed with `Nt` or `Zw` in ntdll.dll that make direct system calls to the kernel without going through the Win32 subsystem (`csrss.exe`, `kernel32.dll`). Operations like `NtAllocateVirtualMemory`, `NtCreateThreadEx`, `NtWriteVirtualMemory`, `NtOpenProcess`, and `NtCreateFile` have no equivalent abstraction layer between the caller and the kernel.

---

## Windows Implementation Details (T1106)

### System Call Dispatch Mechanism

Every native API function in ntdll.dll follows a standard stub pattern on 64-bit Windows:

```asm
; ntdll!NtAllocateVirtualMemory stub (representative)
mov   r10, rcx          ; save first parameter (required by syscall ABI)
mov   eax, <SSN>        ; load System Service Number into EAX
syscall                 ; transition to Ring 0
ret
```

The `syscall` instruction transfers control to the kernel's `KiSystemCall64` handler (address stored in the `LSTAR` MSR). The kernel uses the value in `EAX` as an index into the System Service Descriptor Table (`KeServiceDescriptorTable`, SSDT) to find the actual kernel function to execute. The SSDT is a read-only table protected by PatchGuard; its entries cannot be modified without triggering Kernel Patch Protection (Bugcheck 0x109).

The System Service Number (SSN) for each native API is not fixed across Windows versions — it changes with each OS build. Malware that uses direct syscalls must resolve the current SSN dynamically, either by:
- Parsing the ntdll stub to extract the value from the `mov eax, <SSN>` instruction
- Sorting ntdll exports alphabetically and counting position (the "Hell's Gate" technique)
- Hard-coding SSN values per OS version (fragile, breaks on patches)

### Direct Syscall Abuse (T1106)

Direct syscall abuse bypasses ntdll.dll entirely. The malicious code contains its own `syscall` stub:

```asm
; Attacker-controlled syscall stub in shellcode or PE
mov   r10, rcx
mov   eax, <resolved_SSN>
syscall
ret
```

The CPU transitions to the kernel, which processes the syscall normally — the kernel does not know that the caller skipped ntdll. However, the kernel's KTRAP_FRAME records the user-mode return address (RIP) at the time of the syscall. ETW Threat Intelligence provider captures this: if the KTRAP_FRAME.RIP at syscall entry falls outside any module-backed image in the calling process (i.e., in a VadNone region), it indicates a direct syscall from shellcode.

ETWTI's detection of direct syscalls: ETWTI examines the call stack at the time of certain sensitive operations. If the call stack shows the `syscall` instruction originating from a non-module address, this is the kernel-level indicator. Some ETWTI events include a `CallerAddress` field that can be cross-referenced against the process's VAD tree.

### Heaven's Gate (32→64-bit Thunk) (T1106)

Heaven's Gate exploits the WoW64 execution environment for 32-bit processes on 64-bit Windows. In a WoW64 process, there are two ntdll.dll copies: one 32-bit (`ntdll32`) and one 64-bit (`ntdll64`). The 32-bit ntdll stubs call a WoW64 thunk (a 64-bit code segment) to transition from 32-bit to 64-bit mode before issuing the syscall.

An attacker in a 32-bit process can jump directly into the WoW64 thunk code segment (`CS = 0x33` for 64-bit code, the "far call" to segment 0x33) to execute 64-bit code, including 64-bit syscalls, without going through the 32-bit ntdll or Win32 API layer. This bypasses all 32-bit hooks.

Detection: A 32-bit process executing a `far call` to code segment `0x33` that is not the legitimate WoW64 transition stub is anomalous. ETWTI can detect this when the resulting 64-bit syscall's caller address falls outside the expected WoW64 thunk range.

### NTDLL Unhooking (T1106)

EDR solutions typically hook ntdll.dll by patching the first few bytes of sensitive native API stubs with a JMP to an analysis trampoline. To bypass these hooks, malware can:

1. Open a file handle to `\KnownDlls\ntdll.dll` or directly to `%SystemRoot%\System32\ntdll.dll`
2. Create a section object from the file (`NtCreateSection(SEC_IMAGE)`)
3. Map a view of the section into the current process (`NtMapViewOfSection`)
4. Copy the `.text` section from the fresh mapping over the hooked ntdll.dll in memory
5. Optionally call `NtProtectVirtualMemory` to restore the original protection

After step 4, all native API stubs are restored to their original, unhooked state.

Detection: The Image Load callback (`PsSetLoadImageNotifyRoutineEx`) fires when ntdll.dll is initially loaded at process creation. If a `LoadImage` event for ntdll.dll occurs again (a second load) after process creation, or if ETWTI reports a `VirtualAlloc + MAP_VIEW` event for a new ntdll-sized region followed by a `WriteVM` to the existing ntdll.dll address range, this is the unhooking indicator.

---

## Observable Artifacts (T1106)

- ETWTI event with `CallerAddress` outside any module-backed VAD range (direct syscall from shellcode)
- A freshly-mapped image section of `ntdll.dll` appearing in the VAD tree of a running process after process initialization is complete (second ntdll mapping)
- `VirtualAlloc(PAGE_EXECUTE_READ)` allocation immediately following an `NtMapViewOfSection` of ntdll.dll-sized region — this is the copy-and-execute pattern for ntdll unhooking
- Process whose `Win32StartAddress` falls in a VadNone region (thread started from shellcode that used direct syscalls to create itself)

---

## ETW / eBPF Telemetry Signals (T1106)

### Microsoft-Windows-Threat-Intelligence (ETWTI)

- **ALLOCVM_LOCAL / ALLOCVM_REMOTE**: When the allocation has no corresponding module load event and is in a private anonymous VAD, correlates with shellcode that will use direct syscalls.
- **MAPVIEW_REMOTE / MAPVIEW_LOCAL**: A view mapped for `ntdll.dll` after the process is already running indicates unhooking. Cross-reference the base address against the expected ntdll base from the initial Image Load event.
- Sensitive ETWTI events where the `ReturnAddress` or `CallerAddress` field is in a non-module range indicate direct syscall abuse.

### Microsoft-Windows-Kernel-Process

- `LoadImage` event for `ntdll.dll`: the first occurrence is legitimate (process initialization). Any subsequent `LoadImage` for ntdll.dll in the same process = unhooking attempt.
- Thread create event with `Win32StartAddress` in a VadNone region: the thread was started from shellcode using direct syscalls to avoid `CreateThread` hooks.

---

## Detection Logic (T1106)

### NTDLL Unhooking Rule

```
IF:
  image_load_event(module = ntdll.dll, pid = P) occurs at time T1
  AND image_load_event(module = ntdll.dll, pid = P) occurs again at time T2 > T1
THEN:
  technique = T1106, confidence = 0.90 (ntdll unhooking)
```

### Direct Syscall from Shellcode Rule

```
IF:
  etwti.event.caller_address NOT IN any_image_backed_vad_for_pid
  AND etwti.event.type IN {ALLOCVM_REMOTE, WRITEVM_REMOTE, MAPVIEW_REMOTE, CREATETHREAD_REMOTE}
THEN:
  technique = T1106, confidence = 0.85
```

### Heaven's Gate WoW64 Abuse

```
IF:
  process.is_wow64 = true
  AND etwti.64bit_syscall.caller_address NOT IN wow64_thunk_range
THEN:
  technique = T1106 (Heaven's Gate), confidence = 0.80
```

---

## OCSF Mapping (T1106)

| OCSF Class | Class ID | Discriminating Fields | Technique Confidence |
|---|---|---|---|
| Module Activity | 1008 | Second `ntdll.dll` load event for same PID | T1106 High |
| Memory Activity (extension) | custom | `caller_address` outside module-backed VAD | T1106 High |
| Process Activity | 1007 | Thread Win32StartAddress in VadNone region | T1106 Medium |
