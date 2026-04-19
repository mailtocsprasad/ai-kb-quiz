import pytest
from engine.ptc import compress
from engine.question import Chunk, PTCResult


@pytest.fixture
def chunks():
    return [
        Chunk(
            text=(
                "The SSDT maps syscall numbers to kernel function addresses. "
                "Rootkits overwrite entries to intercept system calls. "
                "PatchGuard detects unauthorized modifications."
            ),
            source_file="windows-internals.md",
            heading="SSDT Hooking",
        ),
        Chunk(
            text=(
                "Kernel callbacks: PsSetCreateProcessNotifyRoutine registers "
                "a callback invoked on process creation."
            ),
            source_file="windows-internals.md",
            heading="Kernel Callbacks",
        ),
    ]


def test_compress_returns_ptc_result(chunks):
    result = compress(chunks, task_type="summarize_chunk")
    assert isinstance(result, PTCResult)
    assert result.compressed_text


def test_compress_reduces_tokens(chunks):
    result = compress(chunks, task_type="summarize_chunk")
    assert result.compressed_tokens <= result.raw_tokens


def test_compress_extract_concepts(chunks):
    result = compress(chunks, task_type="extract_concepts")
    assert isinstance(result, PTCResult)
    assert result.compressed_text


def test_compress_code_context(chunks):
    result = compress(chunks, task_type="extract_code_context")
    assert isinstance(result, PTCResult)


def test_compress_unknown_task_raises(chunks):
    with pytest.raises(ValueError, match="No PTC script for task_type"):
        compress(chunks, task_type="unknown_task")


def test_compression_ratio_in_range(chunks):
    result = compress(chunks, task_type="summarize_chunk")
    assert 0.0 <= result.compression_ratio <= 1.0


def test_summarize_includes_heading(chunks):
    result = compress(chunks, task_type="summarize_chunk")
    assert "SSDT Hooking" in result.compressed_text


def test_extract_concepts_includes_heading(chunks):
    result = compress(chunks, task_type="extract_concepts")
    assert "SSDT Hooking" in result.compressed_text


def test_compress_single_chunk(chunks):
    result = compress(chunks[:1], task_type="summarize_chunk")
    assert result.compressed_text
    assert result.raw_tokens > 0
