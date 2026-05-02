"""Tests for fine-grained sub-heading chunking (Task 20)."""
import pytest
from engine.chunker import chunk_markdown
from engine.question import Chunk


_BOLD_SECTION_MD = (
    "## Key Concepts\n\n"
    "**SSDT Hooking**: The SSDT maps syscall numbers to kernel function addresses.\n"
    "Rootkits overwrite entries to intercept calls.\n\n"
    "**Kernel Callbacks**: PsSetCreateProcessNotifyRoutine registers a callback "
    "invoked on process creation events. Used by EDR for telemetry.\n\n"
    "**VAD Tree**: Virtual Address Descriptor tracks memory regions per process. "
    "Walk with VadRoot in EPROCESS.\n\n"
    "**EPROCESS**: Core kernel structure representing a process. Contains token, "
    "VAD root, thread list, and handle table.\n\n"
)


def test_bold_section_splits_into_multiple_chunks():
    chunks = chunk_markdown(_BOLD_SECTION_MD, "test.md")
    assert len(chunks) >= 4


def test_bold_subchunk_heading_contains_parent():
    chunks = chunk_markdown(_BOLD_SECTION_MD, "test.md")
    assert all("Key Concepts" in c.heading for c in chunks)


def test_bold_subchunk_heading_contains_term():
    chunks = chunk_markdown(_BOLD_SECTION_MD, "test.md")
    headings = [c.heading for c in chunks]
    assert any("SSDT Hooking" in h for h in headings)
    assert any("Kernel Callbacks" in h for h in headings)


def test_ssdt_content_in_its_own_chunk():
    chunks = chunk_markdown(_BOLD_SECTION_MD, "test.md")
    ssdt_chunks = [c for c in chunks if "SSDT" in c.heading]
    assert len(ssdt_chunks) >= 1
    assert "syscall" in ssdt_chunks[0].text.lower()


def test_chunks_respect_max_size():
    long_text = "detail " * 200
    md = (
        "## Big Section\n\n"
        f"**Term A**: {long_text}\n\n"
        f"**Term B**: {long_text}\n\n"
        f"**Term C**: {long_text}\n\n"
    )
    chunks = chunk_markdown(md, "test.md")
    assert all(len(c.text) <= 1200 for c in chunks)


def test_small_sections_not_split():
    md = "## Section A\n\nShort content.\n\n## Section B\n\nAlso short.\n"
    chunks = chunk_markdown(md, "test.md")
    assert len(chunks) == 2


def test_paragraph_fallback_when_no_bold_headers():
    para = "Sentence one. Sentence two. " * 15  # ~420 chars each paragraph
    md = f"## Big Section\n\n{para}\n\n{para}\n\n{para}\n\n"
    chunks = chunk_markdown(md, "test.md")
    assert len(chunks) >= 2
    assert all(len(c.text) <= 1200 for c in chunks)


def test_windows_internals_key_concepts_splits():
    """Regression: the real KB file that triggered Task 20."""
    from pathlib import Path
    path = Path("kb/windows-internals.md")
    if not path.exists():
        pytest.skip("kb/windows-internals.md not present")
    chunks = chunk_markdown(path.read_text(encoding="utf-8"), str(path))
    key_chunks = [c for c in chunks if "Key Concepts" in c.heading]
    assert len(key_chunks) >= 5
    ssdt_chunks = [c for c in key_chunks if "SSDT" in c.text or "Syscall" in c.heading]
    assert len(ssdt_chunks) >= 1
    assert all(len(c.text) <= 1200 for c in key_chunks)
