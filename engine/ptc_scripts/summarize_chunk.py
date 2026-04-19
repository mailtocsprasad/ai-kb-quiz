"""PTC script: summarize_chunk — first 2 sentences per section."""


def run(chunks: list[dict]) -> str:
    lines = []
    for chunk in chunks:
        heading = chunk.get("heading", "")
        text = chunk.get("text", "").replace("\n", " ")
        sentences = [s.strip() for s in text.split(".") if s.strip()]
        summary = ". ".join(sentences[:2])
        if summary:
            lines.append(f"[{heading}] {summary}.")
    return "\n".join(lines)
