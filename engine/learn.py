"""LearnSession — interactive KB study loop.

User story: 7.3 / 7.4 — explain a topic, suggest follow-ups, answer questions.
Raw KB text never reaches a model; all content passes through PTC first.

When refine_adapter + embed_fn + store are provided, the premium model sanitizes
each response and the result is embedded and stored back in ChromaDB so future
retrievals for the same topic surface the clean summary.
"""
import hashlib
import logging
import re
import time

from engine.models.adapter import ModelAdapter
from engine.ptc import compress
from engine.question import Chunk

log = logging.getLogger(__name__)

_EMBED_MAX_CHARS = 2000


def _strip_markdown(text: str) -> str:
    text = re.sub(r"```[\s\S]*?```", "", text)
    text = re.sub(r"`[^`]+`", "", text)
    text = re.sub(r"^\s*[#>|*-]+ ?", "", text, flags=re.MULTILINE)
    text = re.sub(r"\*{1,2}([^*]+)\*{1,2}", r"\1", text)
    text = re.sub(r"\n{2,}", "\n", text)
    return text.strip()


def _t() -> float:
    return time.perf_counter()


class LearnSession:
    def __init__(
        self,
        topic: str,
        retriever,
        adapter: ModelAdapter,
        suggest_adapter: ModelAdapter | None = None,
        refine_adapter: ModelAdapter | None = None,
        embed_fn=None,
        store=None,
    ):
        self._topic = topic
        self._retriever = retriever
        self._adapter = adapter
        self._suggest_adapter = suggest_adapter or adapter
        self._refine_adapter = refine_adapter
        self._embed_fn = embed_fn
        self._store = store

    def explain(self, top_k: int = 4) -> tuple[str, list[Chunk]]:
        t0 = _t()
        chunks = self._retriever.search(self._topic, top_k=top_k, top_n=None)
        log.debug("[retrieve] %.2fs — %d chunks for '%s'", _t() - t0, len(chunks), self._topic)
        if not chunks:
            return "", []

        t0 = _t()
        ptc_result = compress(chunks, "summarize_chunk")
        log.debug("[ptc] %.2fs — %d→%d tokens", _t() - t0, ptc_result.raw_tokens, ptc_result.compressed_tokens)

        prompt = (
            f"Explain the topic '{self._topic}' using this content:\n\n"
            f"{ptc_result.compressed_text}"
        )
        t0 = _t()
        draft = self._adapter.generate(prompt)
        log.debug("[generate:draft] %.2fs — %d chars", _t() - t0, len(draft))

        result = self._refine_and_store(draft, self._topic, chunks)
        return result, chunks

    def suggest(self, chunks: list[Chunk], query: str, context: str = "") -> list[str]:
        if context:
            snippet = _strip_markdown(context)[:500]
            prompt = (
                f"A student just read this explanation about '{query}':\n\n"
                f"{snippet}\n\n"
                "List exactly 3 specific follow-up questions they might ask. "
                "Stay on topic. One question per line, no numbering."
            )
            t0 = _t()
            try:
                raw = self._suggest_adapter.generate(prompt)
                log.debug("[suggest:context] %.2fs — raw=%r", _t() - t0, raw[:80] if raw else "")
                lines = [l.strip() for l in raw.strip().splitlines() if l.strip()]
                if lines:
                    return lines[:3]
                log.debug("[suggest:context] empty response — falling back to headings")
            except Exception as exc:
                log.debug("[suggest:context] failed (%.2fs): %s — falling back to headings", _t() - t0, exc)

        topic_lower = self._topic.lower()
        relevant = [
            c for c in chunks
            if topic_lower in c.heading.lower() or topic_lower in c.text.lower()
        ]
        use_chunks = relevant if relevant else chunks
        log.debug("[suggest:headings] %d relevant / %d total chunks", len(relevant), len(chunks))
        headings = "\n".join(f"- {c.heading}" for c in use_chunks)
        prompt = (
            f"Given these KB sections about '{query}':\n{headings}\n\n"
            "List exactly 3 follow-up questions a student might ask. "
            "Stay on topic. One question per line, no numbering."
        )
        t0 = _t()
        try:
            raw = self._suggest_adapter.generate(prompt)
            log.debug("[suggest:headings] %.2fs — raw=%r", _t() - t0, raw[:80] if raw else "")
            lines = [l.strip() for l in raw.strip().splitlines() if l.strip()]
            return lines[:3]
        except Exception as exc:
            log.debug("[suggest:headings] failed (%.2fs): %s", _t() - t0, exc)
            return []

    def follow_up(self, question: str, top_k: int = 4) -> tuple[str, list[Chunk]]:
        query = f"{self._topic}: {question}"
        t0 = _t()
        chunks = self._retriever.search(query, top_k=top_k, top_n=None)
        log.debug("[retrieve] %.2fs — %d chunks for '%s'", _t() - t0, len(chunks), query)
        if not chunks:
            return "", []

        t0 = _t()
        ptc_result = compress(chunks, "summarize_chunk")
        log.debug("[ptc] %.2fs — %d→%d tokens", _t() - t0, ptc_result.raw_tokens, ptc_result.compressed_tokens)

        prompt = (
            f"Answer this question: '{question}'\n\n"
            f"Using this content:\n\n{ptc_result.compressed_text}"
        )
        t0 = _t()
        draft = self._adapter.generate(prompt)
        log.debug("[generate:draft] %.2fs — %d chars", _t() - t0, len(draft))

        result = self._refine_and_store(draft, f"{self._topic}: {question}", chunks)
        return result, chunks

    def _refine_and_store(self, draft: str, heading: str, chunks: list[Chunk]) -> str:
        if not self._refine_adapter:
            return draft
        if chunks and all(c.source_file == "generated" for c in chunks):
            log.debug("[refine] skipped — all chunks already generated")
            return draft
        t0 = _t()
        refine_prompt = (
            f"Rewrite this explanation to focus strictly on '{self._topic}'.\n"
            f"Remove any unrelated content. Keep all accurate technical details.\n\n"
            f"Draft:\n{draft}"
        )
        refined = self._refine_adapter.generate(refine_prompt)
        log.debug("[generate:refine] %.2fs — %d chars", _t() - t0, len(refined))
        if refined and self._embed_fn and self._store:
            self._store_generated(refined, heading)
        return refined

    def _store_generated(self, text: str, heading: str) -> None:
        t0 = _t()
        chunk_id = "generated:" + hashlib.sha256(
            f"{heading}:{text}".encode()
        ).hexdigest()[:16]
        embedding = self._embed_fn(text[:_EMBED_MAX_CHARS])
        log.debug("[embed] %.2fs — %d chars → %d dims", _t() - t0, len(text), len(embedding))
        t0 = _t()
        self._store.add(
            ids=[chunk_id],
            embeddings=[embedding],
            documents=[text],
            metadatas=[{
                "source_file": "generated",
                "heading": heading,
                "generated": "true",
            }],
        )
        log.debug("[store] %.2fs — chunk_id=%s", _t() - t0, chunk_id)
