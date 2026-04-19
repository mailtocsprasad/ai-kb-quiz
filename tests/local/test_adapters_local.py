"""Module tests for model adapters — require real local dependencies.

Marked @pytest.mark.local: run by default locally, skipped in CI.
Ollama must be running with the configured model pulled.
ANTHROPIC_API_KEY must be set for the premium adapter test.
"""
import os
import pytest
from engine.models.local_adapter import LocalAdapter
from engine.models.premium_adapter import PremiumAdapter

_LOCAL_MODEL = "phi4:14b"
_PREMIUM_MODEL = "claude-haiku-4-5-20251001"


@pytest.mark.local
def test_local_adapter_real_ollama_responds():
    """LocalAdapter gets a non-empty response from a running Ollama instance."""
    adapter = LocalAdapter(model=_LOCAL_MODEL)
    response = adapter.generate("In one sentence: what is the SSDT?")
    assert isinstance(response, str)
    assert len(response) > 10, f"Expected a real answer, got: {response!r}"


@pytest.mark.local
def test_local_adapter_real_ollama_model_name_in_response():
    """LocalAdapter doesn't crash on a simple factual prompt."""
    adapter = LocalAdapter(model=_LOCAL_MODEL)
    response = adapter.generate("Reply with only the word: pong")
    assert isinstance(response, str)


@pytest.mark.local
@pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_API_KEY"),
    reason="ANTHROPIC_API_KEY not set",
)
def test_premium_adapter_real_api_responds():
    """PremiumAdapter gets a real response from the Anthropic API."""
    adapter = PremiumAdapter.from_config(model=_PREMIUM_MODEL)
    response = adapter.generate("In one sentence: what is the SSDT?")
    assert isinstance(response, str)
    assert len(response) > 10, f"Expected a real answer, got: {response!r}"
