# Windows eBPF — Architecture, Hook Schemas & EDR Extension Patterns
> Domain: Windows eBPF, kernel extension programming, network and process monitoring
> Load when: Implementing eBPF programs on Windows, designing eBPF-based EDR sensors, understanding hook points, extension lifecycle, or JIT/verifier constraints

## Purpose & Scope
Full reference for the `ebpf-for-windows` framework: architecture layers, all supported hook programs with their context schemas, the verifier and JIT pipeline, map types, helper function catalogue, and EDR sensor patterns built on eBPF hooks. Complements the summary in `windows-ebpf.md`.

## Key Concepts

**Architecture Layers**

```
User-mode eBPF programs (libbpf / native API)
        │  bpf() syscall-equivalent (DeviceIoControl to EbpfCore)
        ▼
EbpfCore.sys  — program store, map manager, verifier orchestration
        │
        ├── JIT compiler  ─────────────────────► Kernel JIT code (RX page, HVCI-safe)
        │                                         (interpreted fallback if JIT disabled)
        └── Extension host (ebpf_ext_*.sys)  ──► Hook point registration via NMR
                │
                ▼
Hook provider (netiobind, ProcessMonitor, etc.)
        │
        ▼
eBPF program context (struct bpf_*_md) passed to program
```

**Network Module (NMR) Registration**

Extension providers register hook points via the Network Module Registrar:
```c
// Hook provider registers attachment point:
NPI_PROVIDER_CHARACTERISTICS providerChars = {
    .ProviderRegistrationContext = &g_HookContext,
    .ProviderAttachClient        = HookProviderAttachClient,
    .ProviderDetachClient        = HookProviderDetachClient,
};
NmrRegisterProvider(&NPI_EBPF_HOOK_GUID, &providerChars, &g_NmrHandle);

// EbpfCore attaches as client to execute programs at hook points:
// Program is stored as a function pointer chain in the attachment.
```

**Supported Hook Programs and Context Schemas**

### XDP (Express Data Path) — `BPF_PROG_TYPE_XDP`
Fires at the lowest network layer before any stack processing. Attachment: network interface.

```c
struct xdp_md {
    uint32_t data;           // offset to start of packet
    uint32_t data_end;       // offset to end of packet
    uint32_t data_meta;      // metadata region before data
    uint32_t ingress_ifindex;
    uint32_t rx_queue_index;
};
// Return values:
// XDP_PASS     — continue to network stack
// XDP_DROP     — drop packet silently
// XDP_TX       — retransmit on same interface
// XDP_REDIRECT — redirect to another interface or CPU queue
```

### Bind Monitor — `BPF_PROG_TYPE_BIND`
Fires on `bind()` system calls. Attachment: per-process or global.

```c
struct bind_md {
    uint64_t process_id;
    uint32_t socket_address_family;  // AF_INET or AF_INET6
    uint8_t  socket_address[16];     // sockaddr_in / sockaddr_in6
    uint8_t  socket_address_length;
    int      operation;              // BPF_SOCK_ADDR_BIND
};
// Return: BPF_SOCK_ADDR_VERDICT_PROCEED or BPF_SOCK_ADDR_VERDICT_REJECT
```

### Sock Address — `BPF_PROG_TYPE_SOCK_ADDR`
Fires on connect, recv-from, and send-to operations. Used to intercept outbound connections.

```c
struct bpf_sock_addr {
    uint32_t user_family;
    uint32_t user_ip4;    // network byte order
    uint32_t user_ip6[4];
    uint32_t user_port;   // network byte order
    uint32_t family;
    uint32_t type;        // SOCK_STREAM / SOCK_DGRAM
    uint64_t sk;          // socket cookie
};
// Programs can rewrite user_ip4/user_ip6/user_port for transparent proxy.
```

### Sample — `BPF_PROG_TYPE_SAMPLE`
Test hook for unit tests and extension development — fires via explicit ioctl. No production semantics.

**Map Types**

| Map Type | bpf_map_type | Use Case |
|----------|-------------|---------|
| Hash map | `BPF_MAP_TYPE_HASH` | Per-socket / per-PID state; O(1) lookup |
| Array map | `BPF_MAP_TYPE_ARRAY` | Fixed-size indexed config / counters |
| Per-CPU hash | `BPF_MAP_TYPE_PERCPU_HASH` | Lock-free per-CPU counters |
| Per-CPU array | `BPF_MAP_TYPE_PERCPU_ARRAY` | Per-CPU stats without synchronisation |
| Ring buffer | `BPF_MAP_TYPE_RINGBUF` | High-throughput event streaming to user mode |
| LRU hash | `BPF_MAP_TYPE_LRU_HASH` | Connection tracking with automatic eviction |
| Program array | `BPF_MAP_TYPE_PROG_ARRAY` | Tail-call dispatch; chain programs |

**Helper Function Catalogue (Windows-available subset)**

| Helper | Signature | Notes |
|--------|-----------|-------|
| `bpf_map_lookup_elem` | `(map, key) → value*` | Returns NULL on miss |
| `bpf_map_update_elem` | `(map, key, value, flags)` | flags: BPF_ANY / BPF_NOEXIST / BPF_EXIST |
| `bpf_map_delete_elem` | `(map, key)` | Atomic delete |
| `bpf_tail_call` | `(ctx, prog_array, index)` | Non-returning; stack reused |
| `bpf_get_current_pid_tgid` | `() → u64` | high 32 = TGID (process), low 32 = TID |
| `bpf_get_current_comm` | `(buf, len)` | Process name into buf |
| `bpf_ktime_get_ns` | `() → u64` | Monotonic ns since boot |
| `bpf_ringbuf_reserve` | `(map, size, flags) → ptr` | Reserve ring buffer slot |
| `bpf_ringbuf_submit` | `(ptr, flags)` | Publish reserved slot |
| `bpf_ringbuf_discard` | `(ptr, flags)` | Discard reserved slot |
| `bpf_csum_diff` | `(from, from_size, to, to_size, seed) → u32` | Incremental checksum update for packet rewrite |

**Verifier**

The verifier runs in EbpfCore at program load time and rejects any program that:
- Contains unbounded loops (loop bound must be provable at verification time).
- Dereferences a pointer without a prior NULL check.
- Accesses memory outside context/map bounds.
- Uses helper functions not whitelisted for the program type.
- Exceeds 1M instructions (complexity limit).

Verifier outputs a human-readable log on rejection via `bpf_prog_load` errno + verifier_log buffer.

**JIT Compiler and HVCI Constraint**

```
eBPF bytecode
    │
    ▼ EbpfCore JIT (LLVM-based, runs in VTL 0)
    │
    ▼ JIT output in writable non-exec page
    │
    ▼ Secure Kernel marks page RX (SLAT permission update via VMCALL)
    │
    ▼ EbpfCore receives RX mapping → installs in hook attachment
```

- If HVCI is enabled and JIT fails the signing ceremony, program load fails with `EBPF_NO_MEMORY`.
- Interpreted mode (controlled by `EbpfCore` registry key `JitEnabled=0`) bypasses JIT — safe under HVCI but ~10× slower.

**EDR Sensor Patterns**

### Outbound Connection Monitoring (Sock Address hook)
```c
SEC("sk_skb")
int monitor_connect(struct bpf_sock_addr *ctx) {
    struct connection_event ev = {};
    ev.pid  = bpf_get_current_pid_tgid() >> 32;
    ev.ip4  = ctx->user_ip4;
    ev.port = bpf_ntohs(ctx->user_port);
    bpf_get_current_comm(ev.comm, sizeof(ev.comm));

    void *rb = bpf_map_lookup_elem(&event_ringbuf, &zero);
    if (rb) {
        struct connection_event *slot = bpf_ringbuf_reserve(rb, sizeof(ev), 0);
        if (slot) {
            *slot = ev;
            bpf_ringbuf_submit(slot, 0);
        }
    }
    return BPF_SOCK_ADDR_VERDICT_PROCEED;
}
```

### Bind Denial (Bind hook)
```c
SEC("bind")
int deny_bind(struct bind_md *ctx) {
    uint16_t port = bpf_ntohs(*(uint16_t *)(ctx->socket_address + 2));
    // Block bind to reserved port range by unprivileged process
    if (port < 1024 && ctx->process_id > 4) {
        return BPF_SOCK_ADDR_VERDICT_REJECT;
    }
    return BPF_SOCK_ADDR_VERDICT_PROCEED;
}
```

**User-Mode Lifecycle**
```c
// Load and attach:
struct bpf_object *obj = bpf_object__open("my_sensor.o");
bpf_object__load(obj);

struct bpf_program *prog = bpf_object__find_program_by_name(obj, "monitor_connect");
struct bpf_link *link = bpf_program__attach(prog);  // attaches to hook

// Ring buffer polling:
struct ring_buffer *rb = ring_buffer__new(bpf_map__fd(rb_map), handle_event, NULL, NULL);
while (running) {
    ring_buffer__poll(rb, 100 /* timeout ms */);
}

// Cleanup:
bpf_link__destroy(link);
bpf_object__close(obj);
```

**ATT&CK Technique Coverage via eBPF**

| Technique | ATT&CK ID | eBPF Hook | Detection Signal |
|-----------|-----------|-----------|-----------------|
| Network exfiltration | T1041 | `SOCK_ADDR` connect | Large outbound volume to rare IP |
| C2 beaconing | T1071 | `SOCK_ADDR` connect | Periodic small connections, beacon pattern |
| Port binding by malware | T1571 | `BIND` | Unexpected port bind by non-service process |
| Packet injection | T1205 | `XDP` | Raw socket + crafted Ethernet frames |
| DNS tunnelling | T1071.004 | `XDP` (UDP/53) | Oversized DNS queries or high query rate |

## Heuristics & Design Rules
- Always check `bpf_map_lookup_elem` return for NULL before dereferencing — the verifier requires it and missed checks cause program rejection.
- Use `BPF_MAP_TYPE_RINGBUF` over `BPF_MAP_TYPE_PERF_EVENT_ARRAY` for event streaming — ring buffer has lower overhead and no CPU-pinning requirement.
- Use `bpf_tail_call` to split large programs across multiple functions and stay under the 1M-instruction complexity limit.
- Default to JIT-enabled mode; only fall back to interpreted if HVCI rejects the JIT mapping — log the fallback to alert operations teams to the performance impact.
- Attach eBPF programs at the most specific hook point available — `SOCK_ADDR` per-process attachment is less noisy than global XDP interception for connection monitoring.

## Critical Warnings / Anti-Patterns
- Never write to the eBPF context struct in read-only hooks — the verifier rejects writes to read-only context fields at load time.
- Never assume `bpf_get_current_comm` returns null-terminated output for all lengths — always enforce the buffer size limit.
- XDP programs that return `XDP_DROP` for malformed packets can silently discard legitimate traffic if the parse logic has an off-by-one error — test with malformed pcap inputs.
- `bpf_tail_call` is non-returning from the caller's perspective — any cleanup code after it in the caller is unreachable; the verifier will warn.
- Ring buffer `bpf_ringbuf_reserve` can return NULL under load — always check and handle gracefully; do not unconditionally dereference.

## Cross-References
- See also: `boot-virtualization-overview.md` — HVCI impact on eBPF JIT page permissions
- See also: `io-driver-overview.md` — WFP callout alternative for network interception at kernel level
- See also: `windows-internals.md` — Windows eBPF architecture overview and comparison with WFP
- See also: `edr-sensors.md` — eBPF sensors in the EDR sensor layer
