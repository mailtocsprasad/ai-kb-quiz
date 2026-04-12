import chromadb
from pathlib import Path


class VectorStore:
    """ChromaDB-backed vector store with cosine similarity.

    Wraps a single ChromaDB collection. All operations are upsert-safe —
    adding an existing ID updates it rather than duplicating it.
    """

    def __init__(self, persist_dir: Path, collection_name: str = "kb_chunks"):
        self._client = chromadb.PersistentClient(path=str(persist_dir))
        self._col = self._client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"},
        )

    def add(self, ids: list[str], embeddings: list[list[float]],
            documents: list[str], metadatas: list[dict]) -> None:
        """Upsert chunks into the collection.

        ChromaDB 0.6+ rejects empty metadata dicts — normalize to None.
        """
        normalised = [m if m else None for m in metadatas]
        self._col.upsert(
            ids=ids,
            embeddings=embeddings,
            documents=documents,
            metadatas=normalised,
        )

    def delete(self, ids: list[str]) -> None:
        """Remove chunks by ID. No-op for empty list."""
        if ids:
            self._col.delete(ids=ids)

    def query(self, embedding: list[float], n_results: int) -> list[dict]:
        """Return up to n_results chunks sorted by cosine similarity descending.

        Each result dict: {"id": str, "document": str, "metadata": dict, "score": float}
        Score = 1.0 - cosine_distance, in range [0.0, 1.0] for normalised vectors.
        """
        total = self.count()
        if total == 0:
            return []
        n = min(n_results, total)
        results = self._col.query(
            query_embeddings=[embedding],
            n_results=n,
            include=["documents", "metadatas", "distances"],
        )
        return [
            {
                "id": results["ids"][0][i],
                "document": results["documents"][0][i],
                "metadata": results["metadatas"][0][i],
                "score": 1.0 - results["distances"][0][i],
            }
            for i in range(len(results["ids"][0]))
        ]

    def count(self) -> int:
        return self._col.count()

    def get_ids(self) -> list[str]:
        """Return all stored IDs."""
        if self.count() == 0:
            return []
        return self._col.get()["ids"]
