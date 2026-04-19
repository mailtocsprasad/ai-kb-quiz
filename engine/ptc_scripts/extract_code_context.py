"""PTC script: extract_code_context — lines mentioning APIs, structs, typedefs."""
import re

_CODE_RE = re.compile(
    r'\b(struct|function|API|typedef|define|return|void|int|NTSTATUS|PVOID|HANDLE)\b',
    re.IGNORECASE,
)


def run(chunks: list[dict]) -> str:
    lines = []
    for chunk in chunks:
        heading = chunk.get("heading", "")
        text = chunk.get("text", "")
        code_lines = [l.strip() for l in text.split("\n") if _CODE_RE.search(l)]
        if code_lines:
            lines.append(f"[{heading}]\n" + "\n".join(code_lines[:5]))
        else:
            first = text.split(".")[0].strip()
            if first:
                lines.append(f"[{heading}] {first}.")
    return "\n".join(lines)
