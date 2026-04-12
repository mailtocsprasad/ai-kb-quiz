import re
from engine.question import Chunk


_HEADING_RE = re.compile(r'^(#{2,3})\s+(.+)$', re.MULTILINE)


def chunk_markdown(text: str, source_file: str) -> list[Chunk]:
    """Split markdown into Chunk list at H2/H3 boundaries.

    - H1 headings are not split points.
    - Sections with no body text are skipped.
    - Text with no headings is returned as a single chunk with heading="".
    """
    if not text.strip():
        return []

    matches = list(_HEADING_RE.finditer(text))

    if not matches:
        return [Chunk(text=text.strip(), source_file=source_file, heading="")]

    chunks = []
    for i, match in enumerate(matches):
        heading = match.group(2).strip()
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        content = text[start:end].strip()
        if content:
            chunks.append(Chunk(text=content, source_file=source_file, heading=heading))

    return chunks
