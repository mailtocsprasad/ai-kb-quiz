from engine.chunker import chunk_markdown
from engine.question import Chunk


def test_splits_on_h2():
    md = "## Section A\n\nContent A.\n\n## Section B\n\nContent B.\n"
    chunks = chunk_markdown(md, source_file="test.md")
    assert len(chunks) == 2
    assert chunks[0].heading == "Section A"
    assert chunks[1].heading == "Section B"


def test_splits_on_h3():
    md = "## Parent\n\n### Child A\n\nContent A.\n\n### Child B\n\nContent B.\n"
    chunks = chunk_markdown(md, source_file="test.md")
    assert any(c.heading == "Child A" for c in chunks)
    assert any(c.heading == "Child B" for c in chunks)


def test_chunk_carries_source_file():
    md = "## Section\n\nContent.\n"
    chunks = chunk_markdown(md, source_file="windows-internals.md")
    assert chunks[0].source_file == "windows-internals.md"


def test_chunk_text_contains_content():
    md = "## SSDT\n\nSystem Service Descriptor Table maps syscalls.\n"
    chunks = chunk_markdown(md, source_file="f.md")
    assert "System Service Descriptor Table" in chunks[0].text


def test_empty_markdown_returns_no_chunks():
    assert chunk_markdown("", source_file="f.md") == []


def test_whitespace_only_returns_no_chunks():
    assert chunk_markdown("   \n\n  ", source_file="f.md") == []


def test_markdown_without_headings_returns_one_chunk():
    md = "Just some content without any headings.\n"
    chunks = chunk_markdown(md, source_file="f.md")
    assert len(chunks) == 1
    assert chunks[0].heading == ""


def test_skips_empty_sections():
    md = "## Empty\n\n## Full\n\nHas content.\n"
    chunks = chunk_markdown(md, source_file="f.md")
    assert len(chunks) == 1
    assert chunks[0].heading == "Full"


def test_h1_not_split_boundary():
    md = "# Title\n\nIntro text.\n\n## Section\n\nContent.\n"
    chunks = chunk_markdown(md, source_file="f.md")
    # H1 is not a split point — intro text should be absorbed or ignored,
    # Section should be its own chunk
    assert any(c.heading == "Section" for c in chunks)


def test_heading_text_stripped():
    md = "##   Padded Heading   \n\nContent.\n"
    chunks = chunk_markdown(md, source_file="f.md")
    assert chunks[0].heading == "Padded Heading"


def test_chunk_text_does_not_include_heading_line():
    md = "## SSDT\n\nDescribes the table.\n"
    chunks = chunk_markdown(md, source_file="f.md")
    assert "## SSDT" not in chunks[0].text


def test_multiple_h3_under_h2():
    md = (
        "## Parent\n\n"
        "### Alpha\n\nAlpha content.\n\n"
        "### Beta\n\nBeta content.\n\n"
        "### Gamma\n\nGamma content.\n"
    )
    chunks = chunk_markdown(md, source_file="f.md")
    headings = [c.heading for c in chunks]
    assert "Alpha" in headings
    assert "Beta" in headings
    assert "Gamma" in headings


def test_returns_list_of_chunk_instances():
    md = "## Section\n\nContent.\n"
    chunks = chunk_markdown(md, source_file="f.md")
    assert all(isinstance(c, Chunk) for c in chunks)
