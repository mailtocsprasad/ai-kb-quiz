"""PTC script: extract_concepts — capitalised domain terms per section."""
import re


def run(chunks: list[dict]) -> str:
    lines = []
    for chunk in chunks:
        heading = chunk.get("heading", "")
        text = chunk.get("text", "")
        terms = re.findall(r'\b[A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+)*\b', text)
        unique_terms = list(dict.fromkeys(terms))[:8]
        if unique_terms:
            lines.append(f"[{heading}] Concepts: {', '.join(unique_terms)}")
    return "\n".join(lines)
