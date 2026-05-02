import pytest
import httpx
from engine.models.adapter import ModelAdapter, MockAdapter
from engine.models.local_adapter import LocalAdapter
from engine.models.premium_adapter import PremiumAdapter
from engine.models.gemini_adapter import GeminiAdapter


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


# ── Gemini adapter ────────────────────────────────────────────────────────────

def _fake_gemini_client(text: str):
    """Build a minimal fake genai.Client that returns `text` from generate_content."""
    class _Response:
        pass

    class _Models:
        def generate_content(self, **kwargs):
            r = _Response()
            r.text = text
            return r

    class _Client:
        models = _Models()

    return _Client()


def test_gemini_adapter_generate_returns_response_text():
    adapter = GeminiAdapter(
        model="gemini-2.5-flash",
        client=_fake_gemini_client("gemini answer"),
    )
    assert adapter.generate("What is SSDT?") == "gemini answer"


def test_gemini_adapter_generate_returns_empty_on_none_text():
    class _NoneResponse:
        text = None

    class _Models:
        def generate_content(self, **kwargs):
            return _NoneResponse()

    class _Client:
        models = _Models()

    adapter = GeminiAdapter(model="gemini-2.5-flash", client=_Client())
    assert adapter.generate("prompt") == ""


def test_gemini_adapter_passes_model_and_prompt_to_client():
    calls = []

    class _Response:
        text = "ok"

    class _Models:
        def generate_content(self, **kwargs):
            calls.append(kwargs)
            return _Response()

    class _Client:
        models = _Models()

    adapter = GeminiAdapter(model="gemini-2.5-flash", client=_Client())
    adapter.generate("explain SSDT")

    assert len(calls) == 1
    assert calls[0]["model"] == "gemini-2.5-flash"
    assert calls[0]["contents"] == "explain SSDT"


def test_gemini_adapter_passes_system_instruction_in_config():
    from google.genai import types
    captured = {}

    class _Response:
        text = "ok"

    class _Models:
        def generate_content(self, **kwargs):
            captured["config"] = kwargs.get("config")
            return _Response()

    class _Client:
        models = _Models()

    adapter = GeminiAdapter(
        model="gemini-2.5-flash",
        client=_Client(),
        system_prompt="custom system",
    )
    adapter.generate("prompt")

    assert isinstance(captured["config"], types.GenerateContentConfig)
    assert captured["config"].system_instruction == "custom system"


def test_gemini_adapter_from_config_raises_without_key(tmp_path, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(EnvironmentError, match="No Gemini API key"):
        GeminiAdapter.from_config(
            model="gemini-2.5-flash",
            api_key_file=tmp_path / "nonexistent.txt",
        )


def test_gemini_adapter_from_config_reads_key_file(tmp_path, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    key_file = tmp_path / "Gemini-Key.txt"
    key_file.write_text("AIza-test-key-1234")
    # Constructing genai.Client with a fake key will not make network calls,
    # so construction should succeed.
    adapter = GeminiAdapter.from_config(
        model="gemini-2.5-flash",
        api_key_file=key_file,
    )
    assert adapter is not None


def test_gemini_adapter_from_config_prefers_env_var(monkeypatch, tmp_path):
    monkeypatch.setenv("GEMINI_API_KEY", "AIza-env-key")
    adapter = GeminiAdapter.from_config(
        model="gemini-2.5-flash",
        api_key_file=tmp_path / "nonexistent.txt",
    )
    assert adapter is not None


def test_gemini_adapter_from_config_skips_non_aiza_lines(tmp_path, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    key_file = tmp_path / "Gemini-Key.txt"
    key_file.write_text("# comment\n\nAIza-real-key\nsome-other-line")
    adapter = GeminiAdapter.from_config(
        model="gemini-2.5-flash",
        api_key_file=key_file,
    )
    assert adapter is not None


def test_gemini_adapter_implements_protocol():
    from engine.models.adapter import ModelAdapter
    adapter = GeminiAdapter(
        model="gemini-2.5-flash",
        client=_fake_gemini_client("x"),
    )
    assert isinstance(adapter, ModelAdapter)
