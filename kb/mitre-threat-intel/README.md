# Threat Intelligence Knowledge Base — ai-procwatch-mcp

> Technique descriptions reference MITRE ATT&CK® (mitre.org/attack). ATT&CK® is a registered trademark of The MITRE Corporation. Content derived from ATT&CK is used under CC BY 4.0.

## Purpose

This knowledge base provides structured threat intelligence for the `ai-procwatch-mcp` LLM classifier. The classifier receives Windows process behavioral genomes (sequences of ETW, eBPF, and USN Journal events normalized to OCSF 1.5 / STIX 2.1) and must output MITRE ATT&CK technique IDs plus a verdict JSON. This KB enables the classifier to answer: "I see event sequence X in this genome — what technique does that map to, and how confident should I be?"

The KB is designed for **Retrieval-Augmented Generation (RAG)**: chunks are retrieved by semantic similarity, filtered by metadata, and injected into the classifier prompt as context.

---

## Directory Structure

```
threat_intel_kb/
├── README.md                          ← This file (overview, chunking strategy, metadata schema)
├── MITRE_INDEX.md                     ← Master index table of all techniques
│
├── techniques/                        ← Per-technique deep-dive files
│   ├── T1055_process_injection.md
│   ├── T1055_013_process_doppelganging.md
│   ├── T1134_access_token_manipulation.md
│   ├── T1562_impair_defenses.md
│   ├── T1014_rootkit.md
│   ├── T1106_native_api.md
│   ├── T1068_exploitation_privilege_escalation.md
│   ├── T1486_ransomware.md
│   ├── T1059_scripting.md
│   ├── T1003_credential_access.md
│   ├── T1027_obfuscation.md
│   ├── T1574_hijack_execution.md
│   ├── T1547_persistence.md
│   ├── T1070_indicator_removal.md
│   ├── T1218_lolbins.md
│   └── T1082_T1005_discovery_collection.md
│
├── evasion_patterns/                  ← Cross-technique evasion pattern files
│   ├── kernel_evasion.md
│   ├── process_evasion.md
│   ├── memory_evasion.md
│   ├── etw_evasion.md
│   └── driver_evasion.md
│
├── detection_engineering/             ← Sensor maps and behavioral indicators
│   ├── etw_telemetry_map.md
│   ├── behavioral_indicators.md
│   └── genome_analysis_guide.md
│
└── ocsf_stix_mappings/                ← OCSF and STIX cross-reference files
    ├── ocsf_to_mitre.md
    └── stix_indicator_patterns.md
```

---

## RAG Chunking Strategy

### Split Points
Split every file on `##` (H2) headers. Each chunk corresponds to one logical section (e.g., one technique sub-type, one detection rule, one ETW provider's events). Do **not** split on H3 or lower — keep subsections together so a chunk retains enough context to be self-contained.

### Chunk Self-Containment Rule
Every `##` section **must** include the technique ID (e.g., `T1055`) in its first sentence. This ensures that a chunk retrieved out of context still carries its identity. The YAML front matter (for technique files) is prepended to every chunk from that file during indexing.

### Recommended Chunk Size
400–700 tokens per chunk. Technique description sections tend to be 500–600 tokens. ETW signal sections tend to be 300–500 tokens. Behavioral indicator entries are 150–200 tokens each — group 3–4 per chunk.

### Overlap
Use 50-token overlap between adjacent chunks from the same file to preserve inter-section continuity (e.g., so that a Detection Logic chunk retains the tail of its Observable Artifacts section).

---

## Metadata Schema for Vector Store Entries

Each chunk stored in the vector database must carry this JSON metadata object:

```json
{
  "technique_id": "T1055",
  "technique_name": "Process Injection",
  "tactic": ["Defense Evasion", "Privilege Escalation"],
  "platform": "Windows",
  "severity": "High",
  "data_sources": ["ETW-Memory", "ETW-Process"],
  "content_type": "technique"
}
```

**Field definitions:**

| Field | Type | Values / Notes |
|-------|------|----------------|
| `technique_id` | string | MITRE ATT&CK ID (e.g., `T1055`, `T1055.003`) |
| `technique_name` | string | Official technique name |
| `tactic` | array[string] | One or more tactic names from the ATT&CK matrix |
| `platform` | string | Always `"Windows"` for this KB |
| `severity` | string | `"Critical"`, `"High"`, `"Medium"`, `"Low"` |
| `data_sources` | array[string] | ETW provider short names (e.g., `ETW-Process`, `ETW-Memory`, `ETW-File`, `ETW-Registry`, `ETW-Network`, `ETWTI`, `eBPF`, `USN`) |
| `content_type` | string | `"technique"`, `"evasion"`, `"detection"`, `"mapping"` |

### Metadata Filters for Hybrid Search
The recommended retrieval pattern combines semantic similarity with metadata filtering:

```python
# Example: retrieve T1055 technique + detection content for a classifier query
results = vectorstore.similarity_search(
    query=genome_event_description,
    filter={
        "technique_id": {"$in": candidate_technique_ids},
        "content_type": {"$in": ["technique", "detection"]}
    },
    k=8
)
```

Use `data_sources` filter when the genome only has certain sensor types active (e.g., filter to `ETW-Process` + `ETW-Memory` when kernel-file events are not present).

---

## Embedding Implementation

**This project uses Ollama + sqlite-vec** — no external vector database. The embedding and retrieval stack is self-contained within the service process.

**Offline indexing** (`tools/index_kb.py`):
- Walks all four KB subdirectories: `techniques/`, `evasion_patterns/`, `detection_engineering/`, `ocsf_stix_mappings/`
- Splits on `##` H2 headers; prepends YAML front matter to every chunk to anchor technique identity in the embedding
- Posts each chunk to `POST http://127.0.0.1:11435/api/embed` (isolated Ollama subprocess at `OLLAMA_HOST=:11435`)
- Upserts `(chunk_id, technique_id, tactic, severity, data_sources, content_type, text, embedding)` into the `kb_chunks` virtual table in `threat_intel_kb.db` (sqlite-vec extension)
- Idempotent — re-running updates only chunks whose content hash has changed

**Runtime retrieval** (per `classify_genome` call):
- `KbQueryEngine` embeds the query text via `OllamaEmbeddingClient` (backed by `EmbeddingCache`, cap 512)
- Executes a hybrid ANN + metadata SQL query against `threat_intel_kb.db`:

```sql
SELECT chunk_id, technique_id, text, distance
FROM   kb_chunks
WHERE  embedding MATCH ?
  AND  content_type IN ('technique', 'detection', 'evasion')
  AND  k = 5
ORDER  BY distance;
```

- Results cached in `KbQueryCache` (cap 128, session TTL) — same query within one capture window hits sqlite-vec only once
- Top-5 chunks injected into the Ollama/Claude system prompt as `## Relevant KB Context` blocks

**Embedding model:** Configured via `ServiceConfig.ollama_embed_model` (default: `nomic-embed-text`). The same isolated Ollama subprocess that serves classification also serves embedding.

---

## Attribution

> Technique descriptions reference MITRE ATT&CK® (mitre.org/attack). ATT&CK® is a registered trademark of The MITRE Corporation. Content derived from ATT&CK is used under CC BY 4.0.

All content in this KB is original synthesis derived from publicly available Windows documentation, MITRE ATT&CK framework descriptions, and the project owner's own research notes. No content is reproduced verbatim from copyrighted sources.
