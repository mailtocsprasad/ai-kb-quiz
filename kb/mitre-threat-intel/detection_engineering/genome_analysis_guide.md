---
content_type: detection
category: genome_analysis
platform: Windows
---

# Process Genome Analysis Guide

This guide explains how to analyze the OCSF-normalized process genome JSON produced by ai-procwatch-mcp, and how to use it as input to the Ollama pre-screening and Claude API classification pipeline. A "genome" is the complete behavioral record of a process — every ETW event, eBPF socket event, and USN Journal entry attributed to a specific PID, normalized to OCSF 1.5 and serialized as JSON.

---

## What Is a Process Genome?

A process genome is a time-ordered sequence of OCSF event objects captured for a single process during its lifetime (or a fixed time window). It records everything the process did that is observable via the instrumentation stack:

- **Process lifecycle**: creation, parent chain, command line, integrity level, token user
- **Memory operations**: allocations, writes, protections (via ETWTI)
- **File I/O**: creates, writes, reads, deletes, renames (via ETW-Kernel-File + USN Journal)
- **Registry activity**: key opens, value writes, key creates (via ETW-Kernel-Registry)
- **Network activity**: TCP connect/accept, UDP send/recv, DNS queries (via ETW-Kernel-Network + eBPF)
- **Module loads**: DLL image loads with path and timestamp (via PsSetLoadImageNotifyRoutine)
- **Child processes**: all processes spawned by this PID
- **Cross-process actions**: injection attempts, handle acquisitions on other processes

---

## Genome JSON Structure

```json
{
  "genome_id": "g-9f1a3d7b-...",
  "process": {
    "pid": 4821,
    "file": {"name": "powershell.exe", "path": "C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe"},
    "cmd_line": "powershell.exe -enc <base64>",
    "integrity_level": "Medium",
    "start_time": "2026-05-01T14:23:11.442Z",
    "parent_process": {
      "pid": 3901,
      "file": {"name": "WINWORD.EXE"}
    }
  },
  "events": [
    {
      "event_uid": "evt-9f1a",
      "class_uid": 1007,
      "class_name": "Process Activity",
      "activity_id": 1,
      "time": "2026-05-01T14:23:11.442Z",
      "severity_id": 3,
      "metadata": {"product": {"name": "ETW/Kernel-Process"}},
      "actor": {"process": {"pid": 3901, "file": {"name": "WINWORD.EXE"}}},
      "process": {"pid": 4821, "cmd_line": "powershell.exe -enc JAB..."}
    },
    {
      "event_uid": "evt-3d7b",
      "class_uid": 10099,
      "class_name": "Memory Activity",
      "activity_id": 1,
      "time": "2026-05-01T14:23:12.001Z",
      "metadata": {"product": {"name": "ETWTI"}},
      "actor": {"process": {"pid": 4821}},
      "memory": {
        "operation": "ALLOCVM_REMOTE",
        "target_process": {"pid": 7234, "file": {"name": "explorer.exe"}},
        "base_address": "0x1f0000000",
        "size": 4096,
        "protection": "PAGE_EXECUTE_READWRITE"
      }
    }
  ],
  "duration_ms": 8420,
  "event_count": 47
}
```

**Key structural elements:**

- `genome_id`: Unique ID for the genome snapshot. Used for correlation across classification stages.
- `process`: The focal process of this genome. All events are attributed to or initiated by this PID.
- `events[]`: Time-ordered array of OCSF event objects. Each event has a unique `event_uid` (short hex reference used in classifier output `reasons` field).
- `duration_ms`: How long the collection window was.
- `event_count`: Total events captured. Very high counts (> 500 in < 5 seconds) may indicate high-volume operations (ransomware, exfiltration).

---

## Classification Pipeline

### Stage 1: Local Pre-Screening (Ollama — llama3.2:3b)

The genome JSON is fed to the local Ollama model for fast pre-screening. The target is < 200ms p95 latency. The Ollama stage answers a binary question: **is this genome suspicious enough to warrant deep classification?**

**Input prompt structure (Ollama):**

```
You are a Windows EDR event analyzer. Review the following process genome events and determine if this process behavior is suspicious. Focus on:
- Cross-process memory operations (ALLOCVM_REMOTE, WRITEVM_REMOTE)
- Unexpected parent-child process relationships
- Network connections from scripting engines
- Registry writes to persistence locations
- High event volume (file write storms)

Genome (OCSF JSON):
<genome_json_truncated_to_2000_tokens>

Respond with JSON only:
{"suspicious": true|false, "pre_score": 0.0-1.0, "reason": "one sentence"}
```

**Truncation strategy for Ollama:**
- Include the full `process` object (process metadata, parent chain, cmd_line)
- Include the first 30 and last 20 events (captures startup behavior and final state)
- Include all ETWTI memory events (ALLOCVM_REMOTE, WRITEVM_REMOTE, READVM_REMOTE) regardless of position
- Include all cross-process events
- Summarize file write count and registry write count as metadata fields

If `pre_score >= 0.35`, forward to Stage 2. If `pre_score < 0.35`, log as benign with Ollama pre_score and skip Claude.

### Stage 2: Deep Classification (Claude API — claude-sonnet-4-6)

The full genome JSON is forwarded to Claude for detailed analysis. Claude outputs a structured verdict matching the schema defined in the project README:

```json
{
  "verdict": "suspicious",
  "score": 0.78,
  "mitre_techniques": ["T1059.001", "T1055"],
  "reasons": [
    "Encoded PowerShell spawned as child of WINWORD.EXE [evt-9f1a]",
    "Remote thread injection attempt detected [evt-3d7b]"
  ],
  "classifier": "claude-sonnet-4-6",
  "ollama_pre_score": 0.71
}
```

**System prompt for Claude classification stage:**

```
You are an expert Windows endpoint detection analyst. Analyze the following OCSF 1.5 process genome and classify it for malicious behavior.

Your output must be a JSON object with these exact fields:
- verdict: "benign" | "suspicious" | "malicious"
- score: float 0.0-1.0 (confidence the process is malicious)
- mitre_techniques: array of technique IDs (e.g., ["T1055.003", "T1059.001"])
- reasons: array of human-readable strings, each referencing a specific event by [evt-uid]
- classifier: always "claude-sonnet-4-6"
- ollama_pre_score: the score from the pre-screening stage (pass through)

Classification rules:
- score >= 0.80 → verdict = "malicious"
- score 0.40-0.79 → verdict = "suspicious"
- score < 0.40 → verdict = "benign"

Prioritize these high-signal events: ETWTI ALLOCVM_REMOTE/WRITEVM_REMOTE/READVM_REMOTE to lsass.exe, ETWTI SETTHREADCONTEXT_REMOTE, QUEUEAPCTHREAD_REMOTE, Registry writes to ASEP/UAC-bypass paths, Security log clearing events, Shadow copy deletion commands.
```

---

## Genome Analysis Heuristics

### High-Signal Event Combinations

These event combinations within a genome are near-definitive indicators:

| Event Combination | Technique | Genome Score Contribution |
|---|---|---|
| WINWORD.EXE → powershell.exe (cmd_line contains -enc) | T1059.001 + T1027.010 | +0.40 |
| ALLOCVM_REMOTE + WRITEVM_REMOTE → lsass.exe PID | T1003.001 | +0.55 |
| ALLOCVM_REMOTE + WRITEVM_REMOTE + CREATE_THREAD to same target | T1055.003 | +0.50 |
| RegSetValue HKCU UAC bypass key + fodhelper/eventvwr launch (High IL) | T1548.002 | +0.45 |
| FileWrite storm (> 50 files/5s) + extension changes | T1486 | +0.60 |
| wevtutil cl Security OR Event 1102 present in genome | T1070.001 | +0.30 |
| PROTECTVM_LOCAL on ntdll .text range | T1562.006 | +0.55 |
| NtUnmapViewOfSection → WRITEVM → SETTHREADCONTEXT to child process | T1055.012 | +0.55 |

Scores are additive; cap at 1.0. Multiple high-signal combinations increase overall confidence.

### Low-Signal Context (Modifiers)

These observations are not independently suspicious but raise or lower the score in context:

| Observation | Score Modifier |
|---|---|
| Process spawned from Office application (any Office binary) | +0.15 |
| Process running from %TEMP% or %APPDATA% | +0.10 |
| Process has no loaded DLLs beyond ntdll + kernel32 | +0.10 (packer/shellcode stub) |
| Command line contains encoded or obfuscated strings | +0.10 |
| Process is a known-good system binary (full path + valid hash) | -0.20 |
| Process has a valid Authenticode signature from Microsoft | -0.15 |
| Process is part of known installer sequence (parent = msiexec) | -0.25 |
| Zero network connections in the genome | -0.05 |
| Process lifetime < 500ms with no child processes | -0.10 (transient utility) |

### Genome Volume Thresholds

| Metric | Threshold | Implication |
|---|---|---|
| File write events | > 100 in < 10 seconds | Potential ransomware or data staging |
| READVM_REMOTE to lsass.exe | > 5 in 5 seconds | Active credential dump |
| ALLOCVM_REMOTE cross-process | > 3 distinct target PIDs | Injection worm or multi-target injector |
| Registry writes to ASEP keys | > 3 distinct ASEP paths | Persistence mechanism setup |
| Child process spawns | > 10 distinct children in 60s | Discovery burst or malware dropper |
| Network connections | > 20 distinct destination IPs | C2 beacon or network reconnaissance |

---

## Event Reference Fields Used in Reasons

When the classifier outputs `reasons` strings, each reason must reference the specific event(s) that support it using the `[evt-uid]` format. The following OCSF fields are the primary discriminators referenced in reason strings:

| Event Type | Key Fields to Reference |
|---|---|
| Process Activity (1007) | `process.file.name`, `process.cmd_line`, `process.integrity_level`, `actor.process.file.name` |
| Memory Activity (10099) | `memory.operation`, `memory.target_process.file.name`, `memory.base_address`, `memory.protection` |
| File Activity (1001) | `file.path`, `file.name`, `file.extension`, `activity_id` (Create/Write/Delete/Rename) |
| Registry Activity (201003) | `reg_key.path`, `reg_value.name`, `reg_value.data`, `activity_id` |
| Network Activity (4001) | `dst_endpoint.ip`, `dst_endpoint.port`, `actor.process.file.name`, `connection_info.protocol` |
| Module Activity (1008) | `module.file.path`, `module.file.name`, `process.file.name` |

---

## Genome Truncation for Context Windows

When feeding genomes to LLM classifiers, apply this priority ordering if the genome exceeds token limits:

1. **Always include** (never truncate): The `process` object, process start event, parent process chain, all ETWTI events (any operation), all cross-process events, Security log-clearing events, shadow copy deletion events.
2. **High priority**: File write events with extension changes, registry writes to ASEP/UAC paths, network connection events.
3. **Medium priority**: File read events targeting sensitive paths, registry read events for security keys.
4. **Low priority (truncatable)**: Routine file read events for loaded DLLs, registry reads for non-sensitive paths, module load events for well-known system DLLs.

Append a truncation metadata field when summarizing:

```json
"_truncation": {
  "original_event_count": 1842,
  "included_event_count": 312,
  "truncated": true,
  "file_write_summary": {"count": 1420, "unique_extensions": [".docx", ".encrypted"]},
  "file_read_summary": {"count": 87, "unique_paths": 45}
}
```

---

## RAG Query Integration

The threat_intel_kb RAG system is queried during Stage 2 classification to provide technique-specific context to Claude. Query construction:

1. Identify candidate techniques from Ollama pre-score reasons and high-signal events in the genome.
2. Query the vector store with the candidate technique IDs as metadata filters:
   ```python
   results = vector_store.query(
     query_text = "process injection remote thread ETWTI ALLOCVM_REMOTE VadNone executable",
     filter = {"technique_id": {"$in": ["T1055", "T1055.003"]}},
     n_results = 3
   )
   ```
3. Prepend retrieved chunks to the Claude classification prompt under a `## Threat Intelligence Context` section.
4. Cap retrieved context at 1500 tokens to leave room for the genome and classification instructions.

Prioritize retrieving chunks from: `ETW/eBPF Telemetry Signals`, `Detection Logic`, and `Evasion Variants` sections — these are the most operationally relevant for classification.
