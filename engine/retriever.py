import random
from pathlib import Path

from engine.embedder import EmbedFn
from engine.question import Chunk
from engine.store import VectorStore


class IndexNotFoundError(Exception):
    pass


class Retriever:
    """Encodes a query and returns the top-K most semantically similar KB chunks.

    Fetches a wider candidate pool (top_n) then randomly samples top_k from it,
    ensuring varied chunks are returned across sessions on the same topic.
    """

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

    def search(
        self,
        query: str,
        top_k: int = 5,
        top_n: int | None = 20,
        threshold: float = 0.0,
        seed: int | None = None,
    ) -> list[Chunk]:
        """Return up to top_k chunks semantically similar to the query.

        Fetches top_n candidates, filters by threshold, then randomly samples
        top_k. When top_n is None or <= top_k, returns deterministic top-K.
        seed pins the RNG for reproducible sampling in tests.
        """
        vec = self._embed_fn(query)
        fetch = top_n if (top_n and top_n > top_k) else top_k
        results = self._store.query(vec, n_results=fetch)
        filtered = [r for r in results if r["score"] >= threshold]
        if top_n and top_n > top_k and len(filtered) > top_k:
            rng = random.Random(seed)
            filtered = rng.sample(filtered, top_k)
        else:
            filtered = filtered[:top_k]
        return [
            Chunk(
                text=r["document"],
                source_file=(r["metadata"] or {}).get("source_file", ""),
                heading=(r["metadata"] or {}).get("heading", ""),
            )
            for r in filtered
        ]
