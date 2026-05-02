---
technique_id: T1059
technique_name: Command and Scripting Interpreter
tactic: [Execution]
platform: Windows
severity: High
data_sources: [ETW-Process, ETW-PowerShell, ETW-File, ETW-Network]
mitre_url: https://attack.mitre.org/techniques/T1059/
---

# T1059 — Command and Scripting Interpreter

## Description (T1059)

T1059 Command and Scripting Interpreter covers adversary use of built-in Windows scripting engines to execute malicious commands. Because these interpreters are legitimate system binaries with broad application whitelist exemptions, their use is a core component of "living off the land" tradecraft. The key Windows sub-techniques are PowerShell (T1059.001), Windows Command Shell (T1059.003), and WMI (T1059.005). ETW provides deep visibility into PowerShell and process execution, making this one of the better-instrumented technique families.

---

## Windows Implementation Details (T1059)

### PowerShell Architecture

PowerShell on modern Windows (version 5.0+) is built on .NET and runs within the `powershell.exe` (Windows PowerShell) or `pwsh.exe` (PowerShell 7+) host process. The scripting engine (`System.Management.Automation.dll`) executes scripts and commands.

Windows PowerShell 5.0 introduced Script Block Logging, which captures the deobfuscated content of every script block executed by the engine. This logging works even when scripts use `Invoke-Expression` on encoded or concatenated strings — the engine logs the final decoded form. Script block content is emitted via `Microsoft-Windows-PowerShell` ETW provider Event ID 4104.

**AMSI (Antimalware Scan Interface)**: PowerShell passes script content to AMSI before execution. AMSI routes the content to registered security products for scanning. Common AMSI bypass patterns include:
- Patching `amsi.dll!AmsiScanBuffer` to always return `AMSI_RESULT_CLEAN`
- Setting `[Ref].Assembly.GetType('System.Management.Automation.AmsiUtils').GetField('amsiInitFailed','NonPublic,Static').SetValue($null,$true)` to disable AMSI initialization
- Invoking PowerShell through COM objects that bypass the AMSI hook surface

**Constrained Language Mode (CLM)**: AppLocker / WDAC policy can restrict PowerShell to Constrained Language Mode, which prevents COM object creation, .NET type access, and arbitrary code execution via `Add-Type`. Attackers bypass CLM by downgrading to PowerShell version 2 (`powershell.exe -Version 2.0 -Command ...`) which lacks CLM support and Script Block Logging.

---

## Observable Artifacts (T1059)

- PowerShell process created with `-EncodedCommand` or `-enc` flag — the base64-encoded command is visible in the command-line field of the process create event.
- Script block logging (Event 4104) capturing deobfuscated script content including AMSI bypass attempts, download cradles (`IEX (New-Object Net.WebClient).DownloadString(...)`), and credential theft patterns.
- Suspicious parent-child chains: `WINWORD.EXE` → `powershell.exe`, `EXCEL.EXE` → `cmd.exe` → `powershell.exe`, `outlook.exe` → `wscript.exe` → `powershell.exe`.
- PowerShell establishing outbound network connections (ETW-Network / eBPF) — indicates download cradle or C2 communication.
- `cmd.exe` invoked with `/c` and a complex one-liner (long command line > 200 characters) from an Office application parent.

---

## ETW / eBPF Telemetry Signals (T1059)

### Microsoft-Windows-PowerShell (Provider GUID: A0C1853B-5C40-4B15-8766-3CF1C58F985A)

- **Event ID 4104 (ScriptBlockLogging)**: The most valuable PowerShell telemetry event. Fields: `ScriptBlockText` (the actual PowerShell code, deobfuscated), `ScriptBlockId` (GUID for the block), `Path` (script file path if applicable). Key patterns in `ScriptBlockText` to flag:
  - Base64-encoded strings inline: `[System.Text.Encoding]::Unicode.GetString([System.Convert]::FromBase64String(...))`
  - `IEX` / `Invoke-Expression` — in-memory execution of downloaded or constructed strings
  - `New-Object Net.WebClient` / `Invoke-WebRequest` / `Start-BitsTransfer` — download cradles
  - `AmsiUtils` reflection patterns — AMSI bypass
  - `Add-MpPreference -ExclusionPath` — Windows Defender exclusion addition
  - `Compress-Archive` with paths pointing to sensitive data — staging for exfiltration

- **Event ID 400 (EngineLifecycleState Changed to Started)**: Fires when PowerShell engine starts. The `HostApplication` field shows the full command line, which includes encoded command arguments that Event 4104 may not capture if the engine is started but no script blocks run.

### Microsoft-Windows-Kernel-Process

- Process creation of `powershell.exe` / `pwsh.exe` with parent process context. The `CommandLine` field in process create events reveals `-enc`, `-EncodedCommand`, `-e`, `-nop` (no profile), `-w hidden` (hidden window), `-noni` (non-interactive), `-exec bypass` (bypass execution policy) flags — each flag adds to the maliciousness score.
- Process creation event chain analysis: parent → child relationships are recorded and can be traced to identify execution chains originating from Office applications, browsers, or email clients.

### Microsoft-Windows-Kernel-Network / eBPF

- `powershell.exe` establishing outbound TCP connections on port 80/443 to external addresses — download cradle execution.
- DNS queries from `powershell.exe` to domains registered recently (< 30 days) or with unusual TLDs.
- `powershell.exe` connecting to non-standard ports — C2 over custom ports.

---

## Sub-Techniques (T1059)

### T1059.001 — PowerShell (T1059)

T1059.001 PowerShell is the most commonly abused scripting interpreter for post-exploitation. The combination of encoded command, AMSI bypass, and download cradle in a single invocation is the canonical malicious PowerShell pattern.

**Encoded command detection**: When `powershell.exe` is launched with `-EncodedCommand` (or abbreviations `-enc`, `-e`), the argument is a base64-encoded UTF-16LE string. The ETW process create event's `CommandLine` field contains this encoded string. The LLM classifier can identify the pattern by regex: `-[Ee]([Nn][Cc]([Oo][Dd][Ee][Dd]([Cc][Oo][Mm][Mm][Aa][Nn][Dd])?)?)?` followed by a base64 string matching `[A-Za-z0-9+/]{20,}={0,2}`.

**Script block logging bypass (PowerShell v2)**: If the process command line contains `-Version 2` or `-v 2`, the PowerShell v2 engine is invoked, which lacks Script Block Logging and AMSI support. This is a deliberate bypass of those monitoring mechanisms. Detection: `-Version 2` flag in any PowerShell invocation in a Windows 10+ environment = strong indicator.

**Typical phishing execution chain for T1059.001:**

```
[User opens malicious email attachment]
OUTLOOK.EXE (medium integrity)
  → WINWORD.EXE (macro executes)
    → cmd.exe /c powershell.exe -nop -w hidden -enc <base64_payload>
      → [payload connects to C2, downloads stage 2]
```

This chain appears in the genome as four ordered process creation events with specific parent-child relationships and command-line patterns.

### T1059.003 — Windows Command Shell (T1059)

T1059.003 covers `cmd.exe` used for executing batch files, running commands in a chain (using `&&`, `||`, piping), or launching other processes. `cmd.exe` is commonly used as an intermediary launcher to obfuscate the final executable.

Detection: `cmd.exe` launched from Office applications, browser processes, or with `/c` arguments containing paths to temp directories, user profile directories, or commands that download/execute code (`curl`, `certutil`, `bitsadmin`).

### T1059.005 — WMI Scripting (T1059)

WMI-based execution uses `wmic.exe` or the WMI COM interface to execute processes or set up persistent subscriptions. `wmic.exe process call create "<command>"` spawns a process as a child of the WMI host (`WmiPrvSE.exe`), not the attacker's process — this breaks parent-child chain analysis.

Detection: `WmiPrvSE.exe` spawning unexpected child processes (`cmd.exe`, `powershell.exe`, suspicious PE names). ETW process creation events where parent is `WmiPrvSE.exe` and child is a scripting interpreter or network tool.

---

## Detection Logic (T1059)

### Office → PowerShell Encoded Command

```
IF:
  process.create(image = powershell.exe, cmdline matches /-[eE]([nN][cC])?/)
  AND process.parent.image IN {WINWORD.EXE, EXCEL.EXE, OUTLOOK.EXE, POWERPNT.EXE, MSPUB.EXE}
THEN:
  technique = T1059.001 + T1566.001, confidence = 0.93
```

### PowerShell Download Cradle (Event 4104)

```
IF:
  powershell_event_4104.script_block_text matches:
    (IEX|Invoke-Expression).*(DownloadString|WebRequest|BitsTransfer)
THEN:
  technique = T1059.001 + T1105 (Ingress Tool Transfer), confidence = 0.90
```

### PowerShell Version 2 Downgrade

```
IF:
  process.create(image = powershell.exe, cmdline contains -Version 2)
THEN:
  technique = T1059.001 (AMSI/SBL bypass via v2 downgrade), confidence = 0.85
```

---

## OCSF Mapping (T1059)

| OCSF Class | Class ID | Discriminating Fields | Technique Confidence |
|---|---|---|---|
| Process Activity | 1007 | `process.cmd_line` contains `-enc` + parent is Office app | T1059.001 + T1566.001 High |
| Process Activity | 1007 | `process.name = powershell.exe`, `parent = WmiPrvSE.exe` | T1059.005 High |
| Network Activity | 4001 | `src_endpoint.process = powershell.exe`, outbound 443 to new domain | T1059.001 Medium |
