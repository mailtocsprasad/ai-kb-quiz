# MITRE ATT&CK Technique Index

> Technique descriptions reference MITRE ATT&CK® (mitre.org/attack). ATT&CK® is a registered trademark of The MITRE Corporation. Content derived from ATT&CK is used under CC BY 4.0.

This index provides a quick-reference table of all techniques covered in this knowledge base. Each row links to the corresponding deep-dive file. Use this index to map an observed technique ID to its detailed coverage file and to understand which ETW providers are most relevant for detection.

---

| Technique ID | Name | Tactics | Severity | Primary ETW Sources | File |
|---|---|---|---|---|---|
| T1055 | Process Injection | Defense Evasion, Privilege Escalation | High | ETW-Process, ETW-Memory, ETWTI | techniques/T1055_process_injection.md |
| T1055.001 | Dynamic-link Library Injection | Defense Evasion, Privilege Escalation | High | ETW-Process, ETW-Memory, ETWTI | techniques/T1055_process_injection.md |
| T1055.002 | Portable Executable Injection | Defense Evasion, Privilege Escalation | High | ETW-Process, ETW-Memory, ETWTI | techniques/T1055_process_injection.md |
| T1055.003 | Thread Execution Hijacking | Defense Evasion, Privilege Escalation | High | ETW-Process, ETW-Memory, ETWTI | techniques/T1055_process_injection.md |
| T1055.004 | Asynchronous Procedure Call | Defense Evasion, Privilege Escalation | High | ETW-Process, ETW-Memory, ETWTI | techniques/T1055_process_injection.md |
| T1055.012 | Process Hollowing | Defense Evasion, Privilege Escalation | High | ETW-Process, ETW-Memory, ETWTI | techniques/T1055_process_injection.md |
| T1055.013 | Process Doppelganging | Defense Evasion, Privilege Escalation | Critical | ETW-Process, ETW-Memory, USN | techniques/T1055_013_process_doppelganging.md |
| T1134 | Access Token Manipulation | Defense Evasion, Privilege Escalation | High | ETW-Security, ETW-Process | techniques/T1134_access_token_manipulation.md |
| T1134.001 | Token Impersonation/Theft | Defense Evasion, Privilege Escalation | High | ETW-Security, ETWTI | techniques/T1134_access_token_manipulation.md |
| T1134.002 | Create Process with Token | Defense Evasion, Privilege Escalation | High | ETW-Security, ETW-Process | techniques/T1134_access_token_manipulation.md |
| T1134.003 | Make and Impersonate Token | Defense Evasion, Privilege Escalation | High | ETW-Security, ETW-Process | techniques/T1134_access_token_manipulation.md |
| T1547 | Boot or Logon Autostart Execution | Persistence, Privilege Escalation | High | ETW-Registry, ETW-Process | techniques/T1547_persistence.md |
| T1547.001 | Registry Run Keys / Startup Folder | Persistence, Privilege Escalation | Medium | ETW-Registry | techniques/T1547_persistence.md |
| T1548 | Abuse Elevation Control Mechanism | Defense Evasion, Privilege Escalation | High | ETW-Process, ETW-Registry, ETW-Security | techniques/T1134_access_token_manipulation.md |
| T1548.002 | Bypass User Account Control | Defense Evasion, Privilege Escalation | High | ETW-Process, ETW-Registry | techniques/T1134_access_token_manipulation.md |
| T1562 | Impair Defenses | Defense Evasion | Critical | ETW-Process, ETWTI, ETW-Security | techniques/T1562_impair_defenses.md |
| T1562.001 | Disable or Modify Tools | Defense Evasion | High | ETW-Process, ETW-Registry | techniques/T1562_impair_defenses.md |
| T1562.002 | Disable Windows Event Logging | Defense Evasion | High | ETW-Security, ETWTI | techniques/T1562_impair_defenses.md |
| T1562.003 | Impair Command History Logging | Defense Evasion | Medium | ETW-Process | techniques/T1562_impair_defenses.md |
| T1562.004 | Disable or Modify System Firewall | Defense Evasion | Medium | ETW-Registry, ETW-Process | techniques/T1562_impair_defenses.md |
| T1562.006 | Indicator Blocking | Defense Evasion | Critical | ETWTI, ETW-Process | techniques/T1562_impair_defenses.md |
| T1014 | Rootkit | Defense Evasion | Critical | ETW-Process, eBPF, ETWTI | techniques/T1014_rootkit.md |
| T1068 | Exploitation for Privilege Escalation | Privilege Escalation | Critical | ETW-Process, ETW-CodeIntegrity, ETW-AuditAPI | techniques/T1068_exploitation_privilege_escalation.md |
| T1106 | Native API | Execution | High | ETWTI, ETW-Process | techniques/T1106_native_api.md |
| T1059 | Command and Scripting Interpreter | Execution | High | ETW-Process, ETW-PowerShell | techniques/T1059_scripting.md |
| T1059.001 | PowerShell | Execution | High | ETW-PowerShell, ETW-Process | techniques/T1059_scripting.md |
| T1059.002 | AppleScript | Execution | Low | — | techniques/T1059_scripting.md |
| T1059.003 | Windows Command Shell | Execution | Medium | ETW-Process | techniques/T1059_scripting.md |
| T1027 | Obfuscated Files or Information | Defense Evasion | High | ETW-Memory, ETW-Process, ETWTI | techniques/T1027_obfuscation.md |
| T1027.002 | Software Packing | Defense Evasion | Medium | ETW-Process, ETW-Memory | techniques/T1027_obfuscation.md |
| T1574 | Hijack Execution Flow | Defense Evasion, Persistence, Privilege Escalation | High | ETW-Process, ETW-File | techniques/T1574_hijack_execution.md |
| T1574.001 | DLL Search Order Hijacking | Defense Evasion, Persistence | High | ETW-Process, ETW-File | techniques/T1574_hijack_execution.md |
| T1574.002 | DLL Side-Loading | Defense Evasion | High | ETW-Process, ETW-File | techniques/T1574_hijack_execution.md |
| T1195 | Supply Chain Compromise | Initial Access | High | ETW-Process, ETW-File | techniques/T1027_obfuscation.md |
| T1070 | Indicator Removal | Defense Evasion | High | ETW-Security, ETW-Process, USN | techniques/T1070_indicator_removal.md |
| T1070.001 | Clear Windows Event Logs | Defense Evasion | High | ETW-Security, ETW-Process | techniques/T1070_indicator_removal.md |
| T1218 | System Binary Proxy Execution | Defense Evasion | High | ETW-Process, ETW-Network, ETW-File | techniques/T1218_lolbins.md |
| T1003 | OS Credential Dumping | Credential Access | Critical | ETWTI, ETW-Security, ETW-Process | techniques/T1003_credential_access.md |
| T1003.001 | LSASS Memory | Credential Access | Critical | ETWTI, ETW-Security | techniques/T1003_credential_access.md |
| T1082 | System Information Discovery | Discovery | Low | ETW-Process, ETW-Registry | techniques/T1082_T1005_discovery_collection.md |
| T1005 | Data from Local System | Collection | Medium | ETW-File, ETW-Process | techniques/T1082_T1005_discovery_collection.md |
| T1486 | Data Encrypted for Impact | Impact | Critical | ETW-File, ETW-Process, ETW-Network | techniques/T1486_ransomware.md |
| T1078 | Valid Accounts | Defense Evasion, Initial Access, Persistence, Privilege Escalation | Medium | ETW-Security, ETW-Process | techniques/T1134_access_token_manipulation.md |
