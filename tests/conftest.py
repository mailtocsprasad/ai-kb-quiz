import os
import pytest
from pathlib import Path


def pytest_collection_modifyitems(config, items):
    if os.environ.get("CI"):
        skip_local = pytest.mark.skip(reason="local marker skipped in CI")
        for item in items:
            if item.get_closest_marker("local"):
                item.add_marker(skip_local)


class MockAdapter:
    """Deterministic model adapter for tests — no live API calls."""

    def __init__(self, response: str = "mock response"):
        self.response = response
        self.calls: list[str] = []

    def generate(self, prompt: str) -> str:
        self.calls.append(prompt)
        return self.response


@pytest.fixture
def mock_adapter():
    return MockAdapter()


@pytest.fixture
def tiny_kb_dir(tmp_path):
    """Creates a minimal KB directory with two markdown files."""
    kb = tmp_path / "kb"
    kb.mkdir()
    (kb / "topic_a.md").write_text(
        "## SSDT Hooking\n\nThe SSDT (System Service Descriptor Table) maps syscall numbers "
        "to kernel function addresses. Rootkits overwrite entries to intercept calls.\n\n"
        "## Kernel Callbacks\n\nPsSetCreateProcessNotifyRoutine registers a callback "
        "invoked on process creation events.\n"
    )
    (kb / "topic_b.md").write_text(
        "## Dynamic Programming\n\nMemoization stores subproblem results to avoid recomputation. "
        "Key insight: overlapping subproblems + optimal substructure.\n\n"
        "## LIST_ENTRY\n\nWindows doubly-linked list. Traverse via Flink until back at head.\n"
    )
    return kb
