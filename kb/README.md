# Knowledge Base

This directory contains the KB files used for quiz question generation.
All files are original synthesis — safe for public distribution.

## Topics

| File | Domain |
|------|--------|
| `edr-architecture-guide.md` | EDR component architecture (C++, kernel/user-mode) |
| `edr-critical-thinking.md` | Cognitive frameworks for C++ systems and EDR engineering |
| `edr-design-reference.md` | EDR design patterns and interfaces |
| `edr-enhancement.md` | Advanced EDR: C++26, BYOVD, concurrency, agentic AI |
| `windows-debugging.md` | WinDbg, kernel debugging, crash analysis |
| `windows-ebpf.md` | Windows eBPF ecosystem — summary (uBPF, PREVAIL, netebpfext, WFP) |
| `windows-ebpf-overview.md` | Windows eBPF full reference — hook schemas, maps, helpers, EDR patterns |
| `windows-internals.md` | Windows kernel architecture and EDR telemetry |
| `ai-kd.md` | AI-augmented kernel debugging (AI-KD project design) |
| `kernel-primitives-overview.md` | Object Manager, dispatcher objects, synchronization, pool allocation, APC |
| `process-thread-overview.md` | EPROCESS/ETHREAD, process creation pipeline, PS/image callbacks, PPL, injection |
| `io-driver-overview.md` | IRP lifecycle, minifilter framework, IOCTL patterns, WFP callout registration |
| `boot-virtualization-overview.md` | Secure Boot, VBS/VTL architecture, HVCI, KDP, Credential Guard, TPM/PCR |
| `critical-thinking-guide.md` | Systems Thinking, Pre-Mortem, 5 Whys, Fishbone, Design Thinking for security |

## Adding new topics

```bash
python cli/main.py kb add kb/my-new-topic.md
python cli/main.py kb index
```

Only `.md` files are supported. After adding, run `kb index` to make
the new content available for quiz question generation.

## IP policy

Files in this directory must be original content or distilled from
public/open-source sources. Do not add summaries derived from
commercial books or proprietary documents.
