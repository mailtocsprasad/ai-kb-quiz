"""ModelAdapter protocol and MockAdapter for testing.

User story: 1.1 — Shared interface for local and premium model backends.
"""
from typing import Protocol, runtime_checkable


@runtime_checkable
class ModelAdapter(Protocol):
    def generate(self, prompt: str) -> str: ...


class MockAdapter:
    """Deterministic adapter for tests — no live API calls."""

    def __init__(self, response: str = "mock response"):
        self.response = response
        self.calls: list[str] = []

    def generate(self, prompt: str) -> str:
        self.calls.append(prompt)
        return self.response
