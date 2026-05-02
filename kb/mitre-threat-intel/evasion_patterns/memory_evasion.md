---
content_type: evasion
category: memory_evasion
platform: Windows
techniques: [T1055, T1027, T1620]
severity: High
data_sources: [ETWTI, ETW-Process, ETW-Memory]
---

# Memory Evasion Patterns

Memory evasion techniques manipulate in-memory state to defeat scanners, hooks, and behavioral monitors that inspect process address spaces. The Windows Virtual Address Descriptor (VAD) tree, the Process Environment Block (PEB) module list, and the kernel's ETHREAD structure are the primary ground-truth data structures that these techniques target or exploit.

---

## ME-001: RW → RX Permission Flip (Avoiding RWX Allocation)

**Technique:** T1055, T1027.002

**Description:** Early behavior-based detection systems flagged `PAGE_EXECUTE_READWRITE` allocations as inherently suspicious because legitimate code rarely requires simultaneous write and execute permissions on the same region. Attackers adapted by splitting the operation: allocate with `PAGE_READWRITE`, write the payload, then call `VirtualProtect` (or `NtProtectVirtualMemory`) to change permissions to `PAGE_EXECUTE_READ`. The ALLOCVM_REMOTE event now shows a non-executable allocation, potentially bypassing rules that trigger only on RWX.

**Why it still generates telemetry:** ETWTI emits a `PROTECTVM` event on every `NtProtectVirtualMemory` call. A sequence of ALLOCVM(RW) → WRITEVM → PROTECTVM(RX) against the same base address in the same target process is as high-confidence as a direct RWX allocation. The three-event chain is even more specific to injection behavior than a single RWX alloc.

**Detection:**

```
SEQUENCE (same target_pid, same base_address) within 30 seconds:
  ETWTI ALLOCVM(Protect = PAGE_READWRITE, RegionSize > 0x1000)
  ETWTI WRITEVM OR direct writes to that region
  ETWTI PROTECTVM(NewProtect = PAGE_EXECUTE_READ or PAGE_EXECUTE_READWRITE)
→ ME-001 High (0.90)
```

---

## ME-002: Section-Based Injection (Avoiding WriteProcessMemory)

**Technique:** T1055

**Description:** `WriteProcessMemory` (and its native counterpart `NtWriteVirtualMemory`) generates ETWTI WRITEVM_REMOTE events — a well-monitored API. To avoid this, attackers use the Windows section object subsystem: `NtCreateSection` creates a shared memory region backed by the pagefile; `NtMapViewOfSection` maps it into both the attacker's and the target process's address space with different permission settings (RW in attacker space, RX in target space). The attacker writes the payload into its own RW mapping; the target process automatically sees the same content via shared physical pages. No `NtWriteVirtualMemory` call is needed.

**Telemetry:** ETWTI MAPVIEW_REMOTE fires when the section is mapped into the remote process. The event fields include the `TargetPid`, the mapped base address, the size, and the protection flags. A MAPVIEW_REMOTE where `Protect = PAGE_EXECUTE_READ` or `PAGE_EXECUTE_READWRITE` targeting a non-system process is a high-confidence injection indicator.

**Detection:**

```
ETWTI MAPVIEW_REMOTE(
  TargetPid ≠ CallerPid
  Protect ∈ {PAGE_EXECUTE_READ, PAGE_EXECUTE_READWRITE, PAGE_EXECUTE_WRITECOPY}
  NOT (CallerProcess IN known_runtime_set)  -- exclude CLR, JIT
)
→ ME-002 High (0.85)
```

---

## ME-003: Gargoyle — Intermittent RW/RX Toggling

**Technique:** T1055, T1027

**Description:** Gargoyle is a timer-based technique that keeps shellcode marked as `PAGE_READWRITE` (non-executable) while it is idle, flipping to `PAGE_EXECUTE_READ` only for the duration of each execution interval. A Windows timer (created via `CreateTimerQueueTimer` or `RtlCreateTimer`) is configured with a callback that: transitions the shellcode to RX, executes the payload, then transitions back to RW. Between execution windows, memory scanners that walk VAD trees looking for anonymous executable regions will not find the shellcode because it is currently non-executable.

**Detection:** The RW ↔ RX transition sequence in ETWTI is the detection pivot. A VAD region that repeatedly oscillates between `PAGE_READWRITE` and `PAGE_EXECUTE_READ` is the behavioral signature — legitimate JIT engines (CLR, V8, LuaJIT) can generate similar patterns but do so from known DLLs. When the oscillating region is in an anonymous VadNone allocation (no backing image), and the process has no known JIT runtime loaded, Gargoyle is indicated.

```
ETWTI PROTECTVM CLUSTER(
  base_address = constant (same region)
  alternating: Protect cycles between PAGE_READWRITE ↔ PAGE_EXECUTE_READ
  interval between flips = timer period (60–300 seconds typical)
  region.VadType = VadNone
  process has no CLR/V8/LuaJIT loaded
)
→ ME-003 High (0.85)
```

---

## ME-004: PEB Module List Unlinking (Hiding Loaded DLLs)

**Technique:** T1055, T1014

**Description:** The Process Environment Block (`PEB.Ldr`) contains three doubly-linked lists of `LDR_DATA_TABLE_ENTRY` structures, one for each ordering (load order, memory order, initialization order), that enumerate all DLLs loaded in a process. User-mode tools that list loaded DLLs walk these lists. A rootkit or post-injection cleanup step can unlink an `LDR_DATA_TABLE_ENTRY` from one or all three lists, making the associated DLL invisible to tools that rely on `NtQueryInformationProcess(ProcessModuleInformation)` or `EnumProcessModules`.

**Evasion achieved:** The injected DLL appears to have disappeared after loading; tools enumerating loaded DLLs no longer see it. However, the Image Load callback (`PsSetLoadImageNotifyRoutine`) already fired when the DLL was originally loaded, and the EDR's internal module list retains the record. ETWTI also captured the image map event.

**Detection:**

- Cross-reference the EDR's internal image-load event stream (from kernel callback) against the current `LDR_DATA_TABLE_ENTRY` walk. Any module that was seen in image load events but is absent from the current module list has been unlinked.
- VAD tree scan: A VadImageMap entry with a backing file object pointing to a DLL path, for which no `LDR_DATA_TABLE_ENTRY` exists in any of the three PEB lists, indicates an unlinked or reflectively-loaded DLL.

---

## ME-005: Heap Spray and Use-After-Free (Exploitation-Phase Memory Evasion)

**Technique:** T1068 (Exploitation)

**Description:** During the exploitation phase of a kernel or browser vulnerability, the attacker may spray memory with carefully crafted objects to control the state of heap allocations at specific addresses. This is not a persistence or stealth technique per se, but it does complicate forensic analysis: the memory at the time of exploitation contains many copies of similar-looking data, and the exploit's payload may execute and self-delete from memory before analysis can occur.

**Detection relevance:** The exploit's execution almost always transitions into a standard shellcode or process injection sequence, which generates ETWTI events regardless of the exploit mechanism. The exploitation phase itself is visible via `Microsoft-Windows-Win32k` ETW events (for GDI/win32k exploits), pool allocation anomalies, or crash dump analysis.

---

## ME-006: CFG (Control Flow Guard) Bypass via Valid Call Sites

**Technique:** T1055, T1106

**Description:** Control Flow Guard maintains a bitmap of valid indirect call targets (every address that a `call [reg]` or `jmp [reg]` instruction may legally target must have a corresponding 1-bit in the CFG bitmap). Shellcode executing from a VadNone region lacks CFG bitmap entries for its internal call targets. However, some injection techniques pivot execution to a region with valid CFG coverage before calling into shellcode: they use a "trampoline" at a valid CFG target that then calls a pointer in attacker-controlled data.

**Detection:** This technique does not suppress ETW or ETWTI events; the initial thread or APC creation still fires ETWTI notifications. CFG bypass is relevant for endpoint protection products that enforce CFG via page-fault interception, not for ETW-based detection.

---

## ME-007: Reflective PE Loading — No Image Load Callback

**Technique:** T1055.001

**Description:** Reflective DLL injection loads a PE into memory without using the Windows OS loader. The custom reflective loader stub: (1) finds the base address of the target DLL in memory, (2) walks the PE headers to resolve imports manually, (3) applies relocations, (4) calls DllMain. Because `LdrLoadDll` / `LoadLibraryEx` is never called, the kernel's `PsSetLoadImageNotifyRoutine` callback does not fire — the EDR never receives an Image Load event for the injected DLL.

**Residual telemetry:**

- ETWTI ALLOCVM_REMOTE and WRITEVM_REMOTE fire for the initial payload write.
- The VAD entry for the injected region is `VadNone` with executable protection — the DLL's PE signature (`MZ`/`PE`) is present at the base, detectable by VAD content inspection.
- A module is executing (visible via ETWTI events attributed to this PID/address range) for which no Image Load event exists — the gap between ETWTI-observed execution and the Image Load stream is itself a signal.

**Detection:**

```
VAD_SCAN(process):
  node.VadType = VadNone
  AND node.Protection ∈ {PAGE_EXECUTE_READ, PAGE_EXECUTE_READWRITE}
  AND memory_at(node.BaseAddress)[0:2] = "MZ"  -- PE signature present
  AND no LDR_DATA_TABLE_ENTRY for this base address
→ Reflective DLL High (0.90)
```

---

## Summary: Memory Evasion → Telemetry Mapping

| Pattern | Evades | ETWTI Signal | VAD Signal |
|---|---|---|---|
| RW→RX flip | Single RWX alert | PROTECTVM after ALLOCVM+WRITEVM | VadNone, RX after flip |
| Section injection | WRITEVM detection | MAPVIEW_REMOTE(RX) | VadNone + executable |
| Gargoyle | Static VAD scanner | Oscillating PROTECTVM | VadNone, currently RW |
| PEB unlinking | LDR module enumeration | Prior ImageLoad event (now absent from list) | VadImageMap without LDR entry |
| Reflective DLL | Image Load callback | ALLOCVM + WRITEVM preceding | VadNone with MZ signature |
