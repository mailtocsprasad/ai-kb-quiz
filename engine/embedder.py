from typing import Callable
import httpx

EmbedFn = Callable[[str], list[float]]


def make_embed_fn(
    model: str,
    backend: str = "sentence-transformers",
    ollama_base_url: str = "http://localhost:11434",
) -> EmbedFn:
    """Return an EmbedFn for the given model and backend.

    backend="sentence-transformers": runs locally via sentence-transformers library
    backend="ollama": calls Ollama /api/embeddings (requires Ollama running)
    """
    if backend == "ollama":
        return _make_ollama_fn(model, ollama_base_url)
    if backend == "sentence-transformers":
        return _make_st_fn(model)
    raise ValueError(
        f"Unknown embedding backend '{backend}'. "
        "Must be 'ollama' or 'sentence-transformers'."
    )


def _make_st_fn(model: str) -> EmbedFn:
    from sentence_transformers import SentenceTransformer
    _st = SentenceTransformer(model)

    def embed(text: str) -> list[float]:
        return _st.encode(text).tolist()

    return embed


_OLLAMA_MAX_CHARS = 2000  # nomic-embed-text context window (~512 tokens)


def _make_ollama_fn(model: str, base_url: str) -> EmbedFn:
    url = f"{base_url.rstrip('/')}/api/embed"

    def embed(text: str) -> list[float]:
        resp = httpx.post(
            url,
            json={"model": model, "input": text[:_OLLAMA_MAX_CHARS]},
            timeout=30.0,
        )
        resp.raise_for_status()
        return resp.json()["embeddings"][0]

    return embed
