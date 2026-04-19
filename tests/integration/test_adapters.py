import pytest
import httpx
from engine.models.adapter import ModelAdapter, MockAdapter
from engine.models.local_adapter import LocalAdapter
from engine.models.premium_adapter import PremiumAdapter


def test_mock_adapter_returns_configured_response():
    adapter = MockAdapter(response="test output")
    assert adapter.generate("any prompt") == "test output"


def test_mock_adapter_records_calls():
    adapter = MockAdapter(response="x")
    adapter.generate("prompt one")
    adapter.generate("prompt two")
    assert len(adapter.calls) == 2


def test_mock_adapter_implements_protocol():
    adapter = MockAdapter()
    assert isinstance(adapter, ModelAdapter)


def test_local_adapter_calls_ollama(respx_mock):
    respx_mock.post("http://localhost:11434/api/generate").mock(
        return_value=httpx.Response(200, json={"response": "kernel answer"})
    )
    adapter = LocalAdapter(model="phi4-mini")
    assert adapter.generate("What is SSDT?") == "kernel answer"


def test_local_adapter_returns_empty_on_connection_error():
    def raise_connect(request):
        raise httpx.ConnectError("refused")

    client = httpx.Client(transport=httpx.MockTransport(raise_connect))
    adapter = LocalAdapter(model="phi4-mini", client=client)
    assert adapter.generate("any prompt") == ""


def test_local_adapter_returns_empty_on_http_error(respx_mock):
    respx_mock.post("http://localhost:11434/api/generate").mock(
        return_value=httpx.Response(500)
    )
    client = httpx.Client(transport=respx_mock)
    adapter = LocalAdapter(model="phi4-mini", client=client)
    assert adapter.generate("any prompt") == ""


def test_premium_adapter_from_config_raises_without_key(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(EnvironmentError, match="No API key"):
        PremiumAdapter.from_config(
            model="claude-sonnet-4-6",
            api_key_file=tmp_path / "nonexistent.txt",
        )


def test_premium_adapter_from_config_reads_key_file(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    key_file = tmp_path / "Claude-Key.txt"
    key_file.write_text("sk-ant-test-key")
    # from_config should not raise when key file exists
    # (we can't call generate without a live API, so just verify construction)
    adapter = PremiumAdapter.from_config(
        model="claude-sonnet-4-6",
        api_key_file=key_file,
    )
    assert adapter is not None


def test_premium_adapter_from_config_prefers_env_var(monkeypatch, tmp_path):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-env-key")
    adapter = PremiumAdapter.from_config(
        model="claude-sonnet-4-6",
        api_key_file=tmp_path / "nonexistent.txt",
    )
    assert adapter is not None


def test_premium_adapter_generate_uses_client():
    class _FakeMsg:
        content = [type("B", (), {"text": "premium answer"})()]

    class _FakeMessages:
        def create(self, **kwargs):
            return _FakeMsg()

    class _FakeClient:
        messages = _FakeMessages()

    adapter = PremiumAdapter(model="claude-sonnet-4-6", client=_FakeClient())
    assert adapter.generate("prompt") == "premium answer"
