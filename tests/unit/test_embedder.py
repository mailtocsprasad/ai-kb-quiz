import numpy as np
import pytest
import respx
import httpx

from engine.embedder import make_embed_fn


# --- Ollama backend (httpx mocked via respx — no live Ollama needed) ---

@respx.mock
def test_ollama_returns_embedding():
    respx.post("http://localhost:11434/api/embed").mock(
        return_value=httpx.Response(200, json={"embeddings": [[0.1, 0.2, 0.3]]})
    )
    fn = make_embed_fn("nomic-embed-text", backend="ollama")
    assert fn("hello") == [0.1, 0.2, 0.3]


@respx.mock
def test_ollama_sends_correct_model_and_prompt():
    import json
    route = respx.post("http://localhost:11434/api/embed").mock(
        return_value=httpx.Response(200, json={"embeddings": [[0.5]]})
    )
    fn = make_embed_fn("phi4:14b", backend="ollama")
    fn("kernel callbacks")
    payload = json.loads(route.calls[0].request.content)
    assert payload["model"] == "phi4:14b"
    assert payload["input"] == "kernel callbacks"


@respx.mock
def test_ollama_custom_base_url():
    respx.post("http://myhost:9999/api/embed").mock(
        return_value=httpx.Response(200, json={"embeddings": [[1.0]]})
    )
    fn = make_embed_fn("nomic-embed-text", backend="ollama", ollama_base_url="http://myhost:9999")
    assert fn("test") == [1.0]


@respx.mock
def test_ollama_raises_on_http_error():
    respx.post("http://localhost:11434/api/embed").mock(
        return_value=httpx.Response(500)
    )
    fn = make_embed_fn("nomic-embed-text", backend="ollama")
    with pytest.raises(httpx.HTTPStatusError):
        fn("oops")


# --- sentence-transformers backend (SentenceTransformer mocked — no model download) ---
# Skipped automatically on machines where sentence-transformers is not installed.

st = pytest.importorskip("sentence_transformers", reason="sentence-transformers not installed")


def test_st_returns_embedding(mocker):
    mock_cls = mocker.patch("sentence_transformers.SentenceTransformer")
    mock_cls.return_value.encode.return_value = np.array([0.1, 0.2, 0.3])
    fn = make_embed_fn("all-MiniLM-L6-v2", backend="sentence-transformers")
    assert fn("hello") == pytest.approx([0.1, 0.2, 0.3])


def test_st_encode_called_with_text(mocker):
    mock_cls = mocker.patch("sentence_transformers.SentenceTransformer")
    mock_cls.return_value.encode.return_value = np.array([0.0])
    fn = make_embed_fn("all-MiniLM-L6-v2", backend="sentence-transformers")
    fn("EDR architecture")
    mock_cls.return_value.encode.assert_called_once_with("EDR architecture")


# --- unknown backend ---

def test_unknown_backend_raises():
    with pytest.raises(ValueError, match="Unknown embedding backend"):
        make_embed_fn("some-model", backend="auto")


# --- live Ollama tests (skipped if Ollama unreachable or model not pulled) ---

def _ollama_has_model(model: str) -> bool:
    try:
        resp = httpx.get("http://localhost:11434/api/tags", timeout=2.0)
        names = [m["name"] for m in resp.json().get("models", [])]
        return any(n == model or n.startswith(model.split(":")[0]) for n in names)
    except Exception:
        return False


@pytest.mark.parametrize("model", ["nomic-embed-text", "all-minilm", "qwen3-embedding"])
def test_ollama_live_embedding(model):
    if not _ollama_has_model(model):
        pytest.skip(f"Ollama model '{model}' not available on this machine")
    fn = make_embed_fn(model, backend="ollama")
    result = fn("Windows kernel callbacks")
    assert isinstance(result, list)
    assert len(result) > 0
    assert all(isinstance(v, float) for v in result)
