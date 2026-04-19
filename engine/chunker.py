import re
from engine.question import Chunk

_HEADING_RE = re.compile(r'^(#{2,3})\s+(.+)$', re.MULTILINE)
_BOLD_SPLIT_RE = re.compile(r'\n(?=\*\*[^*\n]+\*\*)')
_BOLD_TERM_RE = re.compile(r'^\*\*([^*]+)\*\*')
_MAX_CHARS = 800


def chunk_markdown(text: str, source_file: str) -> list[Chunk]:
    """Split markdown into Chunk list at H2/H3 boundaries, then sub-split
    large sections on bold headers and paragraph boundaries.

    - H1 headings are not split points.
    - Sections with no body text are skipped.
    - Text with no headings is returned as a single chunk with heading="".
    """
    if not text.strip():
        return []

    matches = list(_HEADING_RE.finditer(text))

    if not matches:
        return _sub_split(text.strip(), "", source_file)

    chunks = []
    for i, match in enumerate(matches):
        heading = match.group(2).strip()
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        content = text[start:end].strip()
        if content:
            chunks.extend(_sub_split(content, heading, source_file))

    return chunks


def _sub_split(text: str, heading: str, source_file: str) -> list[Chunk]:
    # Always split on bold section headers when multiple exist — they mark
    # distinct concepts regardless of total section size.
    parts = _BOLD_SPLIT_RE.split(text)
    if len(parts) > 1:
        chunks = []
        for part in parts:
            part = part.strip()
            if not part:
                continue
            bold_match = _BOLD_TERM_RE.match(part)
            sub_heading = f"{heading} › {bold_match.group(1)}" if bold_match else heading
            chunks.extend(_para_split(part, sub_heading, source_file))
        return chunks

    # No bold headers — return as-is if small, paragraph-split if large
    if len(text) <= _MAX_CHARS:
        return [Chunk(text=text, source_file=source_file, heading=heading)]
    return _para_split(text, heading, source_file)


def _para_split(text: str, heading: str, source_file: str) -> list[Chunk]:
    if len(text) <= _MAX_CHARS:
        return [Chunk(text=text, source_file=source_file, heading=heading)]

    paragraphs = [p.strip() for p in re.split(r'\n\n+', text) if p.strip()]
    chunks: list[Chunk] = []
    bucket: list[str] = []
    bucket_len = 0

    for para in paragraphs:
        # Hard-cut paragraphs that are themselves over the limit
        para_parts = _hard_cut(para)
        for part in para_parts:
            if bucket and bucket_len + len(part) + 2 > _MAX_CHARS:
                chunks.append(Chunk(
                    text="\n\n".join(bucket),
                    source_file=source_file,
                    heading=heading,
                ))
                bucket = [part]
                bucket_len = len(part)
            else:
                bucket.append(part)
                bucket_len += len(part) + 2

    if bucket:
        chunks.append(Chunk(
            text="\n\n".join(bucket),
            source_file=source_file,
            heading=heading,
        ))

    return chunks or [Chunk(text=text[:_MAX_CHARS], source_file=source_file, heading=heading)]


def _hard_cut(text: str) -> list[str]:
    """Split text that exceeds _MAX_CHARS on line boundaries, then hard-cut."""
    if len(text) <= _MAX_CHARS:
        return [text]
    # Try splitting on line boundaries first
    lines = text.split("\n")
    parts: list[str] = []
    bucket: list[str] = []
    bucket_len = 0
    for line in lines:
        if bucket and bucket_len + len(line) + 1 > _MAX_CHARS:
            parts.append("\n".join(bucket))
            bucket = [line]
            bucket_len = len(line)
        else:
            bucket.append(line)
            bucket_len += len(line) + 1
    if bucket:
        parts.append("\n".join(bucket))
    # Final pass: hard-cut any part still over limit
    result: list[str] = []
    for part in parts:
        while len(part) > _MAX_CHARS:
            result.append(part[:_MAX_CHARS])
            part = part[_MAX_CHARS:]
        if part:
            result.append(part)
    return result
