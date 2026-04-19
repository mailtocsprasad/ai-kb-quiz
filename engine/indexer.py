import hashlib
from pathlib import Path
from typing import Callable

from engine.chunker import chunk_markdown
from engine.context_cache import ContextCache
from engine.embedder import EmbedFn
from engine.manifest import Manifest
from engine.store import VectorStore

_CONTEXT_PROMPT = (
    "You are helping index a knowledge base.\n"
    "Provide a 1-2 sentence description of what the following section is about,\n"
    "for use as retrieval context. Be specific about the topic domain.\n\n"
    "File: {file_path}\n"
    "Section: {heading}\n\n"
    "{excerpt}"
)


def _chunk_id(source_file: str, index: int, heading: str) -> str:
    raw = f"{source_file}::{index}::{heading}"
    return hashlib.sha256(raw.encode()).hexdigest()[:24]


class Indexer:
    """Orchestrates full and incremental KB indexing: chunk → contextualise → embed → store."""

    def __init__(
        self,
        kb_dir: Path,
        index_dir: Path,
        embed_fn: EmbedFn,
        context_adapter=None,
        chunker_fn: Callable = chunk_markdown,
        collection_name: str = "kb_chunks",
    ):
        self._kb_dir = kb_dir
        self._embed_fn = embed_fn
        self._context_adapter = context_adapter
        self._chunker_fn = chunker_fn
        index_dir.mkdir(parents=True, exist_ok=True)
        self._store = VectorStore(index_dir / "chroma", collection_name=collection_name)
        self._manifest = Manifest(index_dir / "manifest.json")
        self._cache = ContextCache(index_dir / "context_cache.json")

    def build_full(self) -> None:
        self._store.delete_by_source("generated")
        for path in sorted(self._kb_dir.glob("*.md")):
            self._index_file(path)
        self._cache.save()

    def build_incremental(self) -> None:
        diff = self._manifest.diff(self._kb_dir)
        for path in diff.deleted:
            self._store.delete_by_source(str(path))
            self._manifest.remove(path)
        for path in diff.new + diff.changed:
            self._store.delete_by_source(str(path))
            self._index_file(path)
        self._cache.save()

    def _index_file(self, path: Path) -> None:
        text = path.read_text(encoding="utf-8")
        chunks = self._chunker_fn(text, str(path))
        if not chunks:
            self._manifest.update(path)
            return
        ids, embeddings, documents, metadatas = [], [], [], []
        for i, chunk in enumerate(chunks):
            prepared = self._prepare(chunk, str(path))
            ids.append(_chunk_id(str(path), i, chunk.heading))
            embeddings.append(self._embed_fn(prepared))
            documents.append(chunk.text)
            metadatas.append({"source_file": str(path), "heading": chunk.heading})
        self._store.add(ids=ids, embeddings=embeddings, documents=documents, metadatas=metadatas)
        self._manifest.update(path)

    def _prepare(self, chunk, file_path: str) -> str:
        if self._context_adapter is None:
            return chunk.text
        ctx = self._cache.get(chunk.text)
        if ctx is None:
            prompt = _CONTEXT_PROMPT.format(
                file_path=file_path,
                heading=chunk.heading,
                excerpt=chunk.text[:1500],
            )
            ctx = self._context_adapter.generate(prompt)
            self._cache.set(chunk.text, ctx)
        return f"{ctx}\n\n{chunk.text}" if ctx else chunk.text
