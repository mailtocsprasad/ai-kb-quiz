# Windows eBPF Architecture & Use Cases — Summary
> Source: `KnowledgeBase\EDR-Windows-Internals\10-windows-ebpf-overview.md`
> Domain: Windows eBPF, verified kernel programs, network telemetry, XDP, cybersecurity, IT management
> Load when: Designing eBPF-based EDR sensors, implementing network-layer telemetry, evaluating eBPF as WFP/minifilter alternative, analyzing eBPF evasion techniques, or planning IT management instrumentation on Windows

## Purpose & Scope

Covers the Microsoft **ebpf-for-windows** project (open-source, Apache 2.0): architecture of
the Windows eBPF runtime, all supported hook points, EDR sensor patterns, cybersecurity and IT
management use cases, and the offensive/defensive eBPF threat surface.

## Key Concepts

**Core Architecture Components**
- **EbpfCore.sys**: kernel-mode eBPF runtime; manages program lifecycle, map storage (NonPagedPool
  tagged `eBPF`), Platform Abstraction Layer (PAL) over Windows kernel APIs, extension registration.
- **NetEbpfExt.sys**: network hook extension; provides XDP (NDIS), bind, connect4/6, sock_ops,
  cgroup_sock_addr hooks; integrates with NDIS and WFP layers.
- **PREVAIL Verifier** (user-space, pre-load): formally proves safety — no OOB access, no null deref,
  no unbounded loops, no uninitialized reads. Runs in user mode so verifier bugs cannot BSOD.
- **eBPF JIT Compiler** (ubpf-based): verifier-approved bytecode → native x86-64 kernel code.
- **EbpfApi.dll**: libbpf-compatible user-mode API for program load, map CRUD, pin, link management.

**Hook Points**

| Hook | Trigger | Key Context |
|------|---------|-------------|
| `XDP` | Inbound packet at NIC (pre-TCP/IP stack) | Full Ethernet frame, IP/TCP headers |
| `bind` | Winsock bind() syscall | PID, local address/port, protocol |
| `connect4/6` | IPv4/IPv6 connection initiation | PID, src/dst IP, src/dst port |
| `sock_ops` | TCP state machine events | RTT, bytes, connection duration |
| `cgroup_sock_addr` | Socket address manipulation | PID, addr/port for redirection |

**eBPF Maps — Kernel/User Shared State**
- `BPF_MAP_TYPE_RINGBUF`: lock-free ring buffer for high-throughput event streaming (EDR primary)
- `BPF_MAP_TYPE_LPM_TRIE`: CIDR-granular blocklist/allowlist at line rate (O(log n) lookup)
- `BPF_MAP_TYPE_PERCPU_HASH`: per-CPU flow state without locks (C2 beacon tracking)
- `BPF_MAP_TYPE_HASH`: general-purpose key-value (IP blocklists, PID tracking)
- `BPF_MAP_TYPE_PROG_ARRAY`: tail-call dispatch table (chained eBPF program logic)

**Comparison: eBPF vs Traditional Kernel Driver for Telemetry**

| Dimension | Traditional Driver | eBPF Program |
|-----------|-------------------|--------------|
| BSOD risk | Medium | Very low (PREVAIL-verified) |
| Kernel signing required | Yes (PatchGuard) | Reduced (EbpfCore.sys pre-signed) |
| BYOVD attack surface | High (driver = BYOVD target) | Lower (smaller, verifiable) |
| Update without reboot | No | Yes (hot-swap program) |
| Map-based shared state | Manual (IoCtl) | Native (BPF maps, atomic) |
| Telemetry latency | IRP round-trip | Ringbuf direct → IOCP |

## Cybersecurity Use Cases

**Network Security Monitoring (NSM)**
- XDP: full frame visibility before any kernel filter; JA3/JA4 TLS fingerprinting; DNS monitoring
- connect4: per-connection PID attribution; C2 beacon detection via PERCPU_HASH rate tracking
- sock_ops: RTT measurement, bytes-per-flow exfiltration volume tracking

**Threat Detection Patterns**
- **C2 beaconing**: connect4 hook + PERCPU_HASH map; count periodic connections to same external IP within sliding window; alert when count > threshold
- **RAT listener**: bind hook alert on unexpected port bind from non-service processes
- **Lateral movement**: rapid SMB (445), WMI (135), RDP (3389) connect4 sequences from unusual PIDs
- **Exfiltration**: sock_ops byte accumulation per PID per external destination; threshold alert
- **DDoS mitigation**: XDP DROP at wire speed before CPU stack involvement; stateless CIDR rules via LPM_TRIE

**Zero-Trust Enforcement**
- `LPM_TRIE` for CIDR allowlists/denylists at XDP (pre-WFP) and connect4 (PID-aware)
- Microsegmentation: block inter-service connections not in policy map; user-space agent updates map

## EDR Integration Pattern

```
eBPF hook (kernel) → BPF_MAP_TYPE_RINGBUF → User-mode EDR agent (IOCP consumer)
                                                     ↓
                                        Half-Sync/Half-Async pipeline
                                        (ML, correlation, alert, block)
```

EDR agent pushes threat intel updates (C2 IPs, IOCs) to BPF map at runtime — kernel program
enforces updated policy without reload. Policy changes take effect in microseconds.

## IT Management Use Cases

- **Latency monitoring**: sock_ops `BPF_SOCK_OPS_RTT_CB` → per-connection RTT histogram in map
- **Bandwidth accounting**: per-process bytes sent/received via sock_ops byte counters
- **Rate limiting**: XDP token-bucket algorithm for per-source rate limiting
- **QoS marking**: XDP DSCP field marking for enterprise traffic prioritization
- **L4 load balancing**: XDP direct server return (DSR) — stateless, near line-rate
- **Service mesh**: connect4 hook + map DNAT table for transparent service proxy (Cilium-on-Windows)
- **Packet capture**: XDP-based selective capture by IP/port filter — no libpcap overhead

## Offensive / Evasion Threat Surface

| Threat | Mechanism | Detection Approach |
|--------|-----------|-------------------|
| EDR telemetry suppression | XDP DROP on EDR cloud endpoint IPs | Compare NDIS RX counters vs socket-visible RX; alert discrepancy |
| Map poisoning | Admin process overwrites EDR policy map | Audit map FD handle opens from non-EDR processes |
| XDP rootkit | Magic-byte trigger at XDP; drop packet after processing | NDIS counter vs TCP stack counter differential analysis |
| eBPF persistence | eBPF loader as auto-start service | Monitor EbpfCore program load ETW events; audit unknown programs |
| eBPF-based MitM | XDP intercept + retransmit of auth traffic | Correlate packet counts at adapter vs application layer |

**Observable Artifacts for Threat Hunting**
- ETW: provider `{EbpfCore-GUID}` emits program load/unload, verification failure events
- Kernel pool: `!poolused eBPF` in WinDbg — nonzero indicates loaded eBPF programs
- Netsh: `netsh ebpf show programs` / `show maps` / `show links` — full inventory
- Services: `EbpfCore`, `NetEbpfExt` in SCM — presence indicates eBPF runtime installed
- WFP: NetEbpfExt registers WFP callouts for socket hooks — visible in `netsh wfp show filters`

## ATT&CK Mapping

| ID | Technique | eBPF Vector |
|----|-----------|-------------|
| T1014 | Rootkit | XDP-layer traffic hidden from OS |
| T1205.001 | Port Knocking | XDP magic-byte backdoor trigger |
| T1562.001 | Impair Defenses | XDP drop EDR upload; map poisoning |
| T1041 | Exfiltration Over C2 | sock_ops byte tracking for detection |
| T1110 | Brute Force | connect4 rate detection (SMB/RDP) |
| T1543.003 | Create/Modify System Process | eBPF loader as auto-start service |
| T1557 | Adversary-in-the-Middle | XDP packet intercept + retransmit |

## Heuristics & Design Rules

- Inventory all loaded eBPF programs; alert on any not in EDR allowlist — treat unexpected programs as high-severity
- Protect eBPF map FDs with strict ACLs (admin-only write); unprivileged write access = policy bypass
- Use `RINGBUF` for telemetry streaming; it is lock-free, IOCP-compatible, and does not drop events under burst (bounded)
- Place DENY at XDP (before TCP stack) and ALLOW at connect4 (with PID context) for defense-in-depth
- Never trust `netstat`/WFP alone for network visibility — XDP traffic is invisible to both
- Correlate eBPF ETW silence + unexpected program load as active BYOVD/evasion indicator
- For JIT-compiled programs: verify HVCI compatibility — HVCI requires JIT pages to be allocated
  via `VirtualAllocEx` with `PAGE_EXECUTE_READ` only; EbpfCore.sys handles this internally

## Critical Warnings / Anti-Patterns

- Avoid storing secrets (keys, credentials) in eBPF maps — admin-accessible and enumerable
- Avoid XDP DROP-all fallback in production without a tested allow-path bypass mechanism
- Avoid trusting eBPF telemetry as sole network sensor — XDP adversarial interception can silence it
- Avoid loading eBPF programs with broad XDP scope in high-throughput environments without benchmarking
- Do not assume eBPF absence = eBPF safe — EbpfCore.sys may be dormant, ready for malicious program load

## Cross-References

- See also: `windows-ebpf-overview.md` — full reference (hook schemas, code sketches, ATT&CK detail)
- See also: `edr-enhancement.md` — eBPF as BYOVD attack surface reduction, telemetry migration
- See also: `windows-internals.md` — WFP architecture that eBPF socket hooks integrate with
- See also: `edr-architecture-guide.md` — Half-Sync/Half-Async pipeline for eBPF ringbuf consumption
- See also: `io-driver-overview.md` — WFP callout layer above which eBPF XDP hooks operate
- See also: `boot-virtualization-overview.md` — HVCI constraints on eBPF JIT memory
