# Boot & Virtualization Security — VBS, HVCI, Secure Boot & Kernel Protections
> Domain: Windows virtualisation-based security, boot integrity, kernel data protection
> Load when: Implementing HVCI-compliant drivers, analysing VBS architecture, understanding Secure Boot chain, working with KDP/KACLS/CIG, or evaluating eBPF JIT constraints under HVCI

## Purpose & Scope
Complete reference for the Windows Virtualisation-Based Security (VBS) stack from firmware through the kernel: Secure Boot chain, VTL0/VTL1 architecture, Hypervisor-Protected Code Integrity (HVCI), Kernel Data Protection (KDP), Credential Guard, and the impact on driver development and EDR sensor design.

## Key Concepts

**Secure Boot Chain (Firmware → OS Loader)**
```
UEFI firmware (NVRAM keys: PK → KEK → db/dbx)
      │
      ▼
bootmgfw.efi  ← signed by Microsoft PCA
      │
      ▼
winload.efi   ← verified against db; dbx checked for revocations
      │
      ▼
ntoskrnl.exe  ← code integrity check on every loaded image
      │
      ▼
Drivers        ← must be WHQL or EV-signed; cross-signed certs revoked (2016)
```

- `PK` (Platform Key): OEM root, signs `KEK`.
- `KEK` (Key Exchange Key): Microsoft + OEM, signs `db`/`dbx` updates.
- `db` (Allowed Signatures): Hashes and certificates of allowed bootloaders.
- `dbx` (Forbidden Signatures): Revoked hashes — checked before `db`.
- **MOK** (Machine Owner Key): shim-based Linux dual-boot mechanism; separate namespace.

**Virtualisation-Based Security (VBS) Architecture**

VBS partitions the system into two Virtual Trust Levels using the hypervisor (Hyper-V Type-1):

```
┌────────────────────────────────────────────────────────────┐
│ VTL 1 — Secure World (Isolated User Mode + Secure Kernel)  │
│   IUM (Isolated User Mode): lsaiso.exe, key storage        │
│   Secure Kernel (sk.exe): enforces SLAT page permissions   │
│   VSM (Virtual Secure Mode) services                       │
└────────────────────────────────────────────────────────────┘
        ▲  VMCALL / hypercalls only
┌────────────────────────────────────────────────────────────┐
│ VTL 0 — Normal World (NT Kernel + drivers + user mode)     │
│   ntoskrnl.exe, all ring-0 drivers run here                │
│   Cannot access VTL 1 memory — SLAT enforces boundary      │
└────────────────────────────────────────────────────────────┘
        ▲  hardware virtualisation (Intel VT-x / AMD-V)
┌──────────────────────────────────────────────────────────┐
│ Hypervisor (hvix64.exe / hv.dll) — ring -1               │
│   Owns SLAT (EPT/NPT) tables; enforces all memory policy  │
└──────────────────────────────────────────────────────────┘
```

| Layer | Trust Level | Key Assets |
|-------|-------------|-----------|
| VTL 1 Secure Kernel | Highest | SLAT policies, IUM key material, UEFI runtime services |
| VTL 1 IUM | High | LSA secrets (NTLM hashes, Kerberos tickets), DPAPI master keys |
| VTL 0 NT Kernel | Medium | Driver execution, kernel pools, SSDT |
| VTL 0 User Mode | Low | Processes, heap, Win32 API |

**Hypervisor-Protected Code Integrity (HVCI)**

HVCI (also called Memory Integrity) enforces W^X for all kernel-mode pages via SLAT:
- A page can be writable OR executable in VTL 0, never both simultaneously.
- The Secure Kernel validates every driver image before VTL 0 executes it; unsigned or improperly signed drivers are rejected.
- Code page permissions are set at load time and cannot be changed from VTL 0 ring-0 code.

**HVCI Impact on Driver Development**

| Pattern | Without HVCI | With HVCI |
|---------|-------------|-----------|
| Dynamic code generation | Allowed (JIT, shellcode) | Blocked — execute-only pages cannot be written |
| `ExAllocatePool` + mark NX | Not enforced | `NonPagedPoolNx` required; `NonPagedPool` (executable) blocked |
| Inline hooking (SSDT patch) | Works (write to code page) | BSOD — SLAT denies write to executable page |
| `MmMapIoSpace` with exec | Works | Blocked for non-device pages |
| Unsigned driver load | Allowed in test-signing mode | Blocked even with test-signing (`bcdedit /set testsigning`) |

Key driver requirements for HVCI compatibility:
1. Use only `NonPagedPoolNx` (never `NonPagedPool`) for data.
2. No self-modifying code, no dynamic dispatch tables written at runtime.
3. EV code-signing certificate or WHQL signature.
4. No use of deprecated APIs: `MmGetSystemRoutineAddress` calls to overwrite function pointers blocked.

**Kernel Data Protection (KDP)**

KDP allows drivers to mark their own data read-only after initialisation, enforced by the Secure Kernel via SLAT:
```c
// Static KDP — mark a global struct read-only:
DECLARE_CONST_UNICODE_STRING(g_PortName, L"\\MyEDRPort");

// Dynamic KDP:
MM_COPY_ADDRESS src = { .VirtualAddress = &g_Config };
MmProtectDriverSection(&g_Config, sizeof(g_Config), MM_PROTECT_DRIVER_SECTION_READ_ONLY);
// After this call, VTL 0 ring-0 writes to g_Config → BSOD
```

Benefits for EDR: protect callback tables, configuration, and filter handles from kernel-mode tampering.

**Credential Guard**

Credential Guard moves LSA credential material into VTL 1 IUM (`lsaiso.exe`):
- NTLM hashes and Kerberos TGTs are stored and processed in IUM — never exposed to VTL 0.
- Mimikatz-style `lsass.exe` memory dumps are empty of credential material.
- `wdigest` cached credentials remain if `UseLogonCredential` registry key is set — still an attack vector.
- Bypass: requires either a VTL 1 compromise or social-engineering of credentials before they enter LSA.

**SLAT (Second Level Address Translation)**

Intel EPT / AMD NPT — the hypervisor's tool for enforcing VTL boundaries:
- Maps Guest Physical Address (GPA) → Host Physical Address (HPA).
- VTL 1 Secure Kernel populates EPT entries; VTL 0 kernel cannot modify EPT.
- `EPT_VIOLATION` VM-exit fires when VTL 0 code attempts to write an execute-only GPA or execute a write-only GPA.
- EDR relevance: HVCI enforcement is entirely SLAT-based — no software hook needed.

**Boot Measurement & TPM Integration**

```
PCR[0]  — UEFI firmware
PCR[2]  — option ROMs
PCR[4]  — boot manager (bootmgfw.efi)
PCR[7]  — Secure Boot policy state
PCR[11] — Windows Boot Manager measurements (BitLocker seal)
PCR[12] — BitLocker boot configuration (non-EFI)
```

- BitLocker seals the VMK (Volume Master Key) against PCR values; tampering with boot chain changes PCR[7]/[11] and prevents unseal.
- `Measured Boot` (Windows): each boot component measures the next, creating a chain of trust readable by remote attestation.
- `VBS` requires Secure Boot + TPM 2.0 for full attestation support.

**eBPF JIT Under HVCI**

Windows eBPF (`ebpf-for-windows`): JIT-compiled eBPF bytecode runs as kernel extensions.
- Under HVCI: JIT output cannot be placed in a writable page then executed.
- Solution: JIT compiler runs in a VTL 1 isolated context (or uses RO mapping): write JIT output in a writable mapping, call into Secure Kernel to mark it RX, then execute via RX-only VTL 0 mapping.
- Interpreted mode fallback: JIT disabled → bytecode interpreted by the eBPF runtime at PASSIVE_LEVEL; slower but HVCI-safe.
- See `windows-ebpf-overview.md` for full eBPF hook schema and extension registration detail.

**Driver Signing Requirements (Post-2016)**

| Scenario | Requirement |
|----------|------------|
| Production kernel-mode driver | EV certificate + WHQL or Attestation signing via Partner Center |
| Cross-signed certificates | Accepted only if signed before 2016 and certificate not revoked |
| Test-signing (`bcdedit /set testsigning on`) | Works on non-HVCI systems; blocked by HVCI |
| HVCI / Secure Boot enabled | Attestation or WHQL signing required — no test-signing bypass |
| Debug mode (`kernel debugging enabled`) | HVCI enforcement reduced; not a production bypass |

## Heuristics & Design Rules
- Always allocate with `NonPagedPoolNx` — HVCI will reject images using the executable `NonPagedPool` pool type.
- Use KDP for all global EDR configuration structs that are set once at load time — turns kernel-mode tampering into a system crash rather than a silent patch.
- Treat VTL 1 as an audit/attestation oracle only — do not build runtime EDR logic that depends on calling into IUM from a driver; the VMCALL path is high-latency.
- Check HVCI status at `DriverEntry` with `MmIsDriverVerifyingByAddress` + `SeCodeIntegrityQueryInformation`; log and degrade gracefully if KDP APIs are unavailable.
- Credential Guard does not protect SAM-database accounts or DPAPI blobs at rest — scope attestation claims accordingly.

## Critical Warnings / Anti-Patterns
- Never assume test-signing mode is available in EDR deployment — enterprise systems enable HVCI via Group Policy; test-only drivers will fail to load silently.
- `MmProtectDriverSection` is irreversible for the lifetime of the driver load — do not call it on writable buffers or regions that require later modification.
- PCR values are environment-specific: do not hardcode PCR[7] hash expectations — use remote attestation with an endorsement key instead.
- Inline patching of kernel functions (SSDT hooks) is permanently blocked under HVCI; use only approved callback APIs (PsSetCreateProcessNotifyRoutineEx2, ObRegisterCallbacks, FltRegisterFilter).
- VTL 1 IUM isolation protects LSA credentials but not SAM RID 500 password hashes on joined machines — credential theft via domain replication remains viable.

## Cross-References
- See also: `io-driver-overview.md` — HVCI impact on pool allocation and driver code integrity
- See also: `kernel-primitives-overview.md` — NonPagedPoolNx requirement and W^X pool allocation
- See also: `windows-ebpf-overview.md` — JIT constraint details under HVCI for eBPF extensions
- See also: `windows-internals.md` — VBS architecture overview and SLAT page table management
