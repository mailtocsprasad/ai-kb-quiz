"""PTC (Process-Then-Communicate) compression pipeline.

User story: 3.1 — Developer-authored extraction scripts compress raw KB chunks
before any model call. Raw KB text never reaches a model directly.
"""
from engine.question import Chunk, PTCResult
from engine.ptc_scripts import summarize_chunk, extract_concepts, extract_code_context

_SCRIPT_MAP: dict[str, object] = {
    "summarize_chunk": summarize_chunk.run,
    "extract_concepts": extract_concepts.run,
    "extract_code_context": extract_code_context.run,
    "generate_question": extract_concepts.run,
    "evaluate_answer": summarize_chunk.run,
}


def _token_count(text: str) -> int:
    return max(1, len(text) // 4)


def compress(chunks: list[Chunk], task_type: str) -> PTCResult:
    """Run the PTC script for the given task_type and return a PTCResult."""
    if task_type not in _SCRIPT_MAP:
        raise ValueError(f"No PTC script for task_type '{task_type}'")

    raw_text = "\n\n".join(f"[{c.heading}]\n{c.text}" for c in chunks)
    raw_tokens = _token_count(raw_text)

    chunk_dicts = [
        {"heading": c.heading, "text": c.text, "source_file": c.source_file}
        for c in chunks
    ]
    compressed_text = _SCRIPT_MAP[task_type](chunk_dicts)
    compressed_tokens = min(_token_count(compressed_text), raw_tokens)

    return PTCResult(
        compressed_text=compressed_text,
        raw_tokens=raw_tokens,
        compressed_tokens=compressed_tokens,
    )
