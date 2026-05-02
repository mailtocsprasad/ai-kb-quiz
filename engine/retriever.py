import random
import re
from pathlib import Path

from engine.embedder import EmbedFn
from engine.question import Chunk
from engine.store import VectorStore


class IndexNotFoundError(Exception):
    pass


def _tokenize(text: str) -> list[str]:
    return re.findall(r'\b\w+\b', text.lower())


class Retriever:
    """Hybrid BM25 + semantic retriever with Reciprocal Rank Fusion.

    Semantic search captures meaning; BM25 catches exact keyword matches that
    semantic embeddings miss (e.g. "prompt caching" in an LLM context vs a
    file-system context). RRF merges both rankings without needing score
    normalisation.

    BM25 index is built lazily on first search and cached for the session.
    """

    _RRF_K = 60  # standard RRF constant — dampens the impact of rank differences

    def __init__(
        self,
        index_dir: Path,
        embed_fn: EmbedFn,
        collection_name: str = "kb_chunks",
    ):
        if not index_dir.exists():
            raise IndexNotFoundError(
                f"Index not found at '{index_dir}'. "
                "Run: python cli/main.py kb index"
            )
        self._embed_fn = embed_fn
        self._store = VectorStore(index_dir / "chroma", collection_name=collection_name)
        self._bm25 = None
        self._bm25_corpus: list[dict] = []

    # ── BM25 lazy init ───────────────────────────────────────────────────────

    def _ensure_bm25(self) -> None:
        if self._bm25 is not None:
            return
        from rank_bm25 import BM25Okapi
        self._bm25_corpus = self._store.get_all()
        if not self._bm25_corpus:
            return
        tokenized = [_tokenize(doc["document"]) for doc in self._bm25_corpus]
        self._bm25 = BM25Okapi(tokenized)

    def _bm25_search(self, query: str, n: int) -> list[dict]:
        self._ensure_bm25()
        if not self._bm25 or not self._bm25_corpus:
            return []
        scores = self._bm25.get_scores(_tokenize(query))
        top_idx = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:n]
        return [
            {**self._bm25_corpus[i], "bm25_score": float(scores[i])}
            for i in top_idx
            if scores[i] > 0
        ]

    # ── RRF merge ────────────────────────────────────────────────────────────

    def _rrf_merge(
        self,
        semantic: list[dict],
        bm25: list[dict],
    ) -> list[dict]:
        by_id: dict[str, dict] = {}
        k = self._RRF_K

        for rank, result in enumerate(semantic):
            id_ = result["id"]
            by_id[id_] = result.copy()
            by_id[id_]["rrf_score"] = 1.0 / (k + rank + 1)

        for rank, result in enumerate(bm25):
            id_ = result["id"]
            rrf = 1.0 / (k + rank + 1)
            if id_ in by_id:
                by_id[id_]["rrf_score"] += rrf
            else:
                entry = result.copy()
                entry["rrf_score"] = rrf
                by_id[id_] = entry

        return list(by_id.values())

    # ── Generated-chunk cap ──────────────────────────────────────────────────

    @staticmethod
    def _cap_generated(results: list[dict], max_generated: int) -> list[dict]:
        """Keep at most max_generated chunks whose source_file == 'generated'.

        Called on the sorted candidate pool before top_k slicing so that freed
        slots are filled by real KB chunks rather than leaving gaps.
        """
        out, count = [], 0
        for r in results:
            if (r.get("metadata") or {}).get("source_file", "") == "generated":
                if count >= max_generated:
                    continue
                count += 1
            out.append(r)
        return out

    # ── Public API ───────────────────────────────────────────────────────────

    def search(
        self,
        query: str,
        top_k: int = 5,
        top_n: int | None = 20,
        threshold: float = 0.0,
        seed: int | None = None,
        max_generated: int = 1,
    ) -> list[Chunk]:
        """Return up to top_k chunks via hybrid BM25 + semantic search (RRF).

        threshold applies to semantic scores before merging — filters chunks
        with no semantic relevance at all. seed pins the RNG for reproducible
        sampling when the candidate pool exceeds top_k. max_generated caps how
        many stored generated chunks can appear in the results.
        """
        fetch = top_n if (top_n and top_n > top_k) else top_k

        vec = self._embed_fn(query)
        semantic = self._store.query(vec, n_results=fetch)
        semantic = [r for r in semantic if r["score"] >= threshold]

        bm25 = self._bm25_search(query, n=fetch)

        merged = self._rrf_merge(semantic, bm25)
        merged.sort(key=lambda r: r["rrf_score"], reverse=True)
        merged = self._cap_generated(merged, max_generated)

        if top_n and top_n > top_k and len(merged) > top_k:
            rng = random.Random(seed)
            merged = rng.sample(merged, top_k)
        else:
            merged = merged[:top_k]

        return [
            Chunk(
                text=r["document"],
                source_file=(r.get("metadata") or {}).get("source_file", ""),
                heading=(r.get("metadata") or {}).get("heading", ""),
            )
            for r in merged
        ]
