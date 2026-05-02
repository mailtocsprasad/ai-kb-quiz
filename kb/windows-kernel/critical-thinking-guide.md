# Critical Thinking for Security Engineering — Frameworks & Applied Techniques
> Domain: Systems thinking, engineering decision-making, security architecture reasoning
> Load when: Designing EDR architectures, evaluating tradeoffs, conducting design reviews, performing post-mortems, or applying structured reasoning to complex security problems

## Purpose & Scope
Applied critical thinking frameworks for security and systems engineers: Systems Thinking for analysing emergent behaviours in complex systems, Pre-Mortem for anticipating failures before they happen, Root-Cause Analysis (Fishbone / 5 Whys) for diagnosing incidents, Design Thinking for user-centred security tooling, and a meta-framework for choosing the right tool. Each section includes security-specific examples.

## Key Concepts

**Systems Thinking**

Systems Thinking models behaviour as emergent from relationships between components, not just component properties.

Core vocabulary:
| Term | Definition | Security Example |
|------|-----------|-----------------|
| **Stock** | Accumulated state (quantity) | Pending alert queue depth, unpatched host count |
| **Flow** | Rate of change into/out of a stock | Alerts generated per minute, patch deployment rate |
| **Feedback loop (reinforcing)** | Change amplifies itself | Alert fatigue: more alerts → analysts skip → more missed signals |
| **Feedback loop (balancing)** | Change is self-correcting | Detection tuning: FP rate rise → analyst tunes rule → FP rate falls |
| **Delay** | Time lag between cause and effect | Threat intel takes weeks to translate into rule coverage |
| **Leverage point** | Where a small change has large system effect | Raising analyst alert-review SLA by 10% can break a reinforcing loop |

Applied to EDR design:
- Model the detection pipeline as stocks (event buffer, alert queue, analyst workload) and flows (event rate, rule hit rate, mean-time-to-investigate).
- Identify reinforcing loops that create systemic problems: high FP rate → analyst desensitisation → missed TPs → pressure for more rules → higher FP rate.
- Find balancing loops to reinforce: automated scoring that reduces analyst load when volume spikes.

Causal Loop Diagram template for EDR alert pipeline:
```
Detection Coverage (+) ──[+]──► Alert Volume
Alert Volume (+) ────────[+]──► Analyst Workload
Analyst Workload (+) ────[+]──► Alert Fatigue
Alert Fatigue (+) ───────[-]──► Investigation Rate
Investigation Rate (-) ──[-]──► Detection Efficacy     (reinforcing: degraded loop)
Detection Efficacy (-) ──[-]──► Detection Coverage     (closes the loop)
```

**Pre-Mortem Analysis**

Pre-Mortem assumes the project has already failed (or succeeded) in the future and asks: *why?*

Process:
1. **Set the scenario**: "It's 6 months from now. Our EDR rollout failed — the SOC is blind to a real intrusion."
2. **Independent generation**: Each participant writes failure reasons individually (prevents groupthink).
3. **Round-robin share**: Each person reveals one reason per round until exhausted.
4. **Cluster**: Group similar failure modes (e.g., operational, technical, political).
5. **Prioritise by likelihood × impact**: Top 3–5 get mitigation actions added to the project plan.
6. **Success pre-mortem variant**: "It worked beautifully — what made it work?" Reveals non-obvious success factors.

Security-specific failure modes to prompt (use as seed list):
- Detection coverage gap in a specific subsystem (e.g., lateral movement via WMI not instrumented)
- Operational complexity caused sensors to be disabled (too many performance alerts)
- False positive rate caused alert fatigue; real incident was in the queue for 4 hours
- Sensor kernel driver caused system instability; IT forced uninstallation
- Privilege escalation bypassed EDR because rule was scoped to Win32 API, not direct syscall
- Key personnel leaving caused institutional knowledge loss mid-deployment

**Root Cause Analysis: 5 Whys**

Iterative "why" questions that move from symptom to root cause. Stop when you reach an actionable systemic cause.

Example — EDR missed a LSASS credential dump:
```
Symptom: LSASS memory read was not alerted

Why 1: The process access rule did not fire
Why 2: The rule only checked process name, not image path
Why 3: The attacker renamed their dump tool to "svchost.exe"
Why 4: The image-path validation was removed as a "performance optimisation"
Why 5: No regression test verified that image-path validation remained active
Root cause: Detection rule regression tests do not cover path-bypass evasion variants
Action: Add automated evasion-variant test suite to CI pipeline
```

Anti-pattern — stopping at Why 2 ("the rule only checked process name") leads to a band-aid fix (add image path check) without addressing why the regression appeared.

**Root Cause Analysis: Fishbone (Ishikawa)**

Fishbone diagrams organise causes into categories for complex incidents with multiple contributing factors.

Categories adapted for security incidents (the "6 Ms" → security variant):
| Bone | Category | Examples |
|------|----------|---------|
| **Detection** | Rules & coverage | Rule logic, scope, evasion gap |
| **People** | Human factors | Analyst fatigue, knowledge gap, process not followed |
| **Process** | Procedures | Incident response playbook missing step, escalation unclear |
| **Technology** | Tooling | Sensor blind spot, pipeline latency, logging gap |
| **Data** | Telemetry quality | Missing fields, high cardinality noise, sampling |
| **Environment** | Deployment context | OS version gap, EDR not deployed on critical asset |

Template (write effect on right, draw bones left):
```
Detection ──┐
People ─────┼── [Effect: Missed intrusion — T1003 not alerted]
Process ────┤
Technology ─┤
Data ───────┤
Environment ┘
```

**Design Thinking Applied to Security Tooling**

Five-phase framework for user-centred security tools (e.g., SOC analyst console, EDR management UI).

| Phase | Question | Security Tool Example |
|-------|----------|----------------------|
| **Empathise** | Who uses this, in what context, under what pressure? | Tier-1 analyst, 200 alerts/day, 4-min SLA, alert fatigue |
| **Define** | What is the real problem to solve? | "Analysts cannot distinguish real threats from noise in their alert queue" |
| **Ideate** | What are the solution approaches? | Automated triage scoring, context enrichment, alert clustering |
| **Prototype** | Build smallest testable version | Static mockup of enriched alert card; A/B with and without risk score |
| **Test** | Validate with real users | Analyst walks through 10 real alerts with prototype; measure time-to-decision |

Common trap: jumping from Empathise to Prototype without a Define step. Result: a beautiful tool that solves the wrong problem (e.g., building a better alert visualisation when the root problem is too many low-fidelity rules).

**Inversion Thinking**

Ask: *what would guarantee failure?* Then avoid those things.

For EDR design:
- "What would make our sensor completely useless?" → Attacker can disable it from user mode → solution: PPL protection + kernel self-defense.
- "What would cause SOC to stop trusting our alerts?" → Consistent FPs on known-good tools (e.g., sysinternals flagged daily) → solution: allowlist management workflow.
- "What would cause IT to uninstall the sensor?" → BSoD on patch Tuesday → solution: staged rollout + auto-rollback on crash loop.

**Choosing the Right Framework**

| Situation | Recommended Framework |
|-----------|--------------------|
| Planning a new system / feature | Systems Thinking (model feedback loops) + Pre-Mortem |
| Active incident investigation | 5 Whys (single root cause) or Fishbone (multi-factor) |
| Post-mortem / retrospective | 5 Whys → systemic fixes; Fishbone for culture/process |
| Designing tools for human operators | Design Thinking |
| Evaluating a technical decision | Inversion Thinking + Pre-Mortem |
| Architecture review | Systems Thinking causal loop + Pre-Mortem |

## Heuristics & Design Rules
- Start any architecture review with a causal loop diagram before diving into component design — emergent system behaviour is invisible without it.
- Pre-Mortem is most valuable when run *before* commitments are locked — run it at the end of the design phase, not after implementation begins.
- Always carry 5 Whys at least one level past the first technical fix — stopping at a technical patch misses the process or culture root cause.
- In Fishbone, the "Technology" bone is almost never the only cause for a security miss — People and Process bones usually co-contribute.
- Use Inversion Thinking as a pre-flight check before shipping detection rules — ask "how would I evade this rule?" before declaring it complete.

## Critical Warnings / Anti-Patterns
- **Groupthink in Pre-Mortem**: if the team brainstorms together without individual silent generation first, low-status members self-censor. Always write independently before sharing.
- **5 Whys cascading blame**: it is easy to end at "human error" and assign blame to an individual. If a "Why" answer is a person's name, go one level deeper to the system condition that enabled the error.
- **Design Thinking misapplication**: the empathise phase requires *observing real users*, not imagining them. A design based on assumed analyst behaviour will miss the key friction points.
- **Systems Thinking paralysis**: causal loop diagrams can become arbitrarily complex. Scope to 5–8 nodes for the primary loop; leave secondary loops as footnotes.
- **Inversion Thinking as negativity**: "everything could fail" is not useful. Constrain inversion to the specific feature or decision at hand; time-box it to 15 minutes.

## Cross-References
- See also: `edr-architecture-guide.md` — architectural design decisions and trade-offs in EDR systems
- See also: `edr-design-reference.md` — RAII patterns and code-level design considerations
- See also: `windows-internals.md` — system-level context for reasoning about Windows security architecture
