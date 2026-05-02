---
technique_id: T1027
technique_name: Obfuscated Files or Information
tactic: [Defense Evasion]
platform: Windows
severity: High
data_sources: [ETW-Process, ETW-Memory, ETW-File, ETWTI]
mitre_url: https://attack.mitre.org/techniques/T1027/
---

# T1027 — Obfuscated Files or Information

## Description (T1027)

T1027 Obfuscated Files or Information covers techniques that make malicious code or data harder to detect through encoding, encryption, packing, or deliberate corruption of file structures. Obfuscation targets static analysis tools (signature scanners, YARA rules, file-format parsers) by changing the on-disk representation of malicious content while preserving its runtime semantics. The attacker accepts a deobfuscation overhead at execution time — either embedding a stub that decodes the payload into memory, or relying on a host interpreter (PowerShell, .NET runtime) to evaluate obfuscated text.

Windows is particularly susceptible because its rich scripting ecosystem (`powershell.exe`, `wscript.exe`, `mshta.exe`, `cscript.exe`) can evaluate dynamically-constructed code strings, and because user-space loader flexibility allows arbitrary packing algorithms to decompress into executable memory without involving the OS loader.

---

## Windows Implementation Details (T1027)

Software packing (T1027.002) operates by replacing the original PE sections with compressed or encrypted data and adding a small unpacking stub as the new entry point. The stub runs first, allocates executable memory (typically via `VirtualAlloc` with `PAGE_EXECUTE_READWRITE`), decompresses the original PE or shellcode into that region, and transfers control. From the OS loader's perspective, only the packer shell is a valid PE; the payload exists exclusively in memory.

The EPROCESS VAD tree is the ground-truth artifact of packing at runtime: the decompressed payload will appear as a `VadNone` anonymous private region with an executable protection flag, with no backing file object and no corresponding `LDR_DATA_TABLE_ENTRY` in the PEB module list. This is the same VAD signature as process injection (T1055), because both involve code executing from private anonymous memory — a fundamental OS-level invariant that cannot be evaded without kernel-mode modifications to the VAD tree itself.

PowerShell obfuscation (T1027.010) exploits the PowerShell parser's permissive evaluation model. The `-EncodedCommand` parameter accepts Base64-encoded UTF-16LE input and evaluates it at runtime. `Invoke-Expression` (alias `iex`) can evaluate arbitrary strings, enabling multi-hop obfuscation where a first-stage script downloads and evaluates a second-stage string. Script block logging (ETW provider `Microsoft-Windows-PowerShell`, Event ID 4104) captures the final deobfuscated script block before execution — bypassing static obfuscation entirely and providing a clear view of what was actually executed.

AMSI (Antimalware Scan Interface) is the Windows mechanism that intercepts calls to `IAmsiStream::Scan` from scripting hosts, allowing security products to inspect content before execution. AMSI bypass (related to T1562) is frequently combined with T1027 to prevent the deobfuscated payload from being scanned.

---

## Observable Artifacts (T1027)

- A PE binary with an unusually high entropy section (entropy > 7.0 bits/byte in `.text` or custom sections) — normal compiled code has entropy in the 5–6.5 range; compressed or encrypted payloads approach 8.0.
- A PE binary where standard section names (`.text`, `.data`, `.rdata`) are absent or replaced with non-standard names, or where the declared section virtual size and raw size differ dramatically.
- Execution of `powershell.exe` with the `-enc`, `-EncodedCommand`, `-e`, or `-en` flag followed by a Base64 string.
- A `VirtualAlloc` call with `PAGE_EXECUTE_READWRITE` from the main thread of a process that loaded no additional DLLs after startup (packer stub running in the process's initial thread context).
- An `NtWriteFile` or file creation event creating a file with a `.exe` or `.dll` extension in `%TEMP%` from a scripting engine process, followed by `CreateProcess` on that file.

---

## ETW / eBPF Telemetry Signals (T1027)

### Microsoft-Windows-PowerShell

- **Event ID 4104 (Script Block Logging)**: Captures every PowerShell script block as it is compiled, including content that was dynamically assembled via `Invoke-Expression`, string concatenation, or `[System.Text.Encoding]::Unicode.GetString()` / `.GetBytes()` chains. The `ScriptBlockText` field contains the actual evaluated code regardless of how it was encoded at rest. Detection: look for common obfuscation residue (`iex`, `-join`, `[char[]]`, `[Convert]::FromBase64String`, `-bxor` XOR decoding, `$env:` environment variable string assembly).
- **Event ID 400 (Engine Lifecycle)**: Records PowerShell engine start. The `HostApplication` field exposes the full command line that launched PowerShell, including any `-EncodedCommand` arguments, enabling correlation between the obfuscated form and the 4104 decoded form.
- **Event ID 4103 (Module Logging)**: Captures parameter bindings and pipeline input/output for each PowerShell command. Combined with 4104, provides the clearest picture of obfuscated command execution.

### Microsoft-Windows-Threat-Intelligence (ETWTI)

- **ALLOCVM events**: A packer stub allocates memory for the unpacked payload. When the allocation occurs in the process's own address space (`TargetPid == CallerPid`) with `Protect = PAGE_EXECUTE_READWRITE` within the first few seconds of process execution, this is a strong packing indicator. Legitimate JIT compilers (CLR, V8) also allocate RWX memory but do so from known runtime DLLs and after full module initialization.
- **PROTECTVM events**: The RW → RX permission flip after payload write. ETWTI fires `PROTECTVM` on every `NtProtectVirtualMemory` call. A sequence of ALLOCVM(RWX or RW) → WRITEVM or direct write → PROTECTVM(RX) in the same process from the initial thread or packer stub thread is canonical pack-and-execute behavior.

### Microsoft-Windows-Kernel-File

- **File Create + File Write**: Dropper activity — creating and writing an executable file to a user-writable path from a scripting engine. The combination `actor = wscript.exe` + `target = *.exe in %TEMP%` + subsequent `ProcessStart` from that target is a three-event chain that maps to T1027 (obfuscated delivery) + T1204 (user execution).

---

## Evasion Variants (T1027)

- **PE header erasure**: After unpacking, the payload zeros or corrupts the MZ/PE signature in the first bytes of the allocation. Memory scanners that rely on walking the PEB module list and verifying PE headers will miss this payload; VAD-based scanning that inspects all private executable regions without relying on valid headers remains effective.
- **Multi-stage encoding**: First stage retrieves an encoded second stage (XOR, Base64, AES), which retrieves a third stage from a C2 URL. Each stage is too small or ambiguous for signature matching. Script block logging captures each stage's decoded form at evaluation time.
- **Compile-time obfuscation (ConfuserEx, Obfuscar for .NET)**: Method names, string literals, and control flow are randomized at build time. The resulting assembly is a valid .NET binary with legitimate metadata, defeating YARA rules based on string patterns. ETWTI telemetry is unaffected because the obfuscation is purely structural.
- **Environment variable string assembly**: `$env:COMPUTERNAME[2] + $env:OS[0] + ...` assembles command keywords character by character from environment variable values. Script block logging captures the assembled string after PowerShell evaluates it.
- **Reflective PE loading with import address table (IAT) obfuscation**: The injected PE resolves its imports manually using a hand-rolled `GetProcAddress` equivalent that walks export tables with hashed function names. This defeats string-search based detection of import names.

---

## Detection Logic (T1027)

### PowerShell Encoded Command

```
ProcessStart(
  image_name = powershell.exe
  cmd_line MATCHES "-[eE][nN]{0,2}[cC]{0,1}.*[A-Za-z0-9+/=]{20,}"
)
→ T1027.010 Medium (0.65) — correlate with ETW 4104 for decoded content

Event ID 4104(
  ScriptBlockText MATCHES "iex|Invoke-Expression|FromBase64String|
                            -bxor|-join.*\[char\]|\.GetBytes\(\)"
)
→ T1027.010 High (0.80)
```

### RWX Packer Stub Detection

```
ETWTI ALLOCVM(
  TargetPid = CallerPid
  Protect = PAGE_EXECUTE_READWRITE
  RegionSize > 0x1000
  time_since_process_start < 5 seconds
) AND
  process_module_count < 5 (packer stub before loading runtime)
→ T1027.002 High (0.85)
```

### VAD Anomaly (Packed Payload In-Memory)

```
VAD_SCAN(target_process):
  node.VadType = VadNone
  AND node.PrivateMemory = 1
  AND node.Protection ∈ {PAGE_EXECUTE_READ, PAGE_EXECUTE_READWRITE}
  AND no LDR_DATA_TABLE_ENTRY for this address range
  AND no Image Load event for this address range
→ T1027 / T1055 High (0.90) — private anonymous executable region
```

---

## Sub-Techniques (T1027)

### T1027.002 — Software Packing

A PE binary is compressed or encrypted and bundled with an unpacking stub. Common packers include UPX (benign use common, so presence alone is low confidence), custom proprietary packers with high-entropy sections, and VM-based protectors (Themida, VMProtect) that translate native code into custom bytecode interpreted by an embedded VM. The entropy-based static indicator and the runtime VAD signature are the two complementary detection angles.

### T1027.009 — Embedded Payloads

A binary carries its actual payload embedded within a resource section, overlay data (bytes appended after the PE's last section), or a steganographic carrier file. The payload is extracted and executed at runtime. ETW File events for resource extraction and ETWTI ALLOCVM for the extracted region provide telemetry.

### T1027.010 — Command Obfuscation

PowerShell, `cmd.exe`, and other CLI tools support syntactic obfuscation: caret escaping (`^p^o^w^e^r^s^h^e^l^l`), quote insertion (`po"wer"shell`), and environment variable substitution (`%COMSPEC%`). PowerShell-specific obfuscation is logged by script block logging; `cmd.exe` obfuscation is visible in the raw process command line from ETW-Process Event ID 1.

---

## Related Techniques (T1027)

- T1055 (Process Injection) — Packed payloads often use injection to execute in a host process
- T1106 (Native API) — Packers use direct syscalls or native APIs to avoid hook-based detection of their memory operations
- T1562 (Impair Defenses) — AMSI bypass commonly precedes script-based obfuscation
- T1059 (Scripting) — PowerShell and scripting engines are the primary vehicle for script obfuscation

---

## OCSF Mapping (T1027)

| OCSF Class | Class ID | Discriminating Fields | Technique Confidence |
|---|---|---|---|
| Process Activity | 1007 | `process.cmd_line` contains `-enc` + Base64 blob, `file.name = powershell.exe` | T1027.010 Medium |
| Memory Activity (extension) | custom | `memory.protection = PAGE_EXECUTE_READWRITE`, `target_pid = caller_pid`, early in process lifetime | T1027.002 High |
| File Activity | 1001 | High-entropy file created in temp path by scripting host | T1027.009 Medium |
