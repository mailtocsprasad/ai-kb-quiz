from typing import Callable
import httpx

EmbedFn = Callable[[str], list[float]]

# gemini-embedding-001 enforces a 2048-token hard limit per chunk (~8000 chars)
_GEMINI_MAX_CHARS = 8000
_OLLAMA_MAX_CHARS = 2000  # nomic-embed-text context window (~512 tokens)


def make_embed_fn(
    model: str,
    backend: str = "sentence-transformers",
    ollama_base_url: str = "http://localhost:11434",
    task_type: str = "RETRIEVAL_DOCUMENT",
    api_key: str | None = None,
    output_dimensionality: int = 768,
) -> EmbedFn:
    """Return an EmbedFn for the given model and backend.

    backend="sentence-transformers": runs locally via sentence-transformers library
    backend="ollama": calls Ollama /api/embeddings (requires Ollama running)
    backend="gemini": calls Gemini embedding API (requires api_key)
      task_type: "RETRIEVAL_DOCUMENT" for indexing, "RETRIEVAL_QUERY" for search
      output_dimensionality: MRL truncation — 768 is the recommended sweet spot
    """
    if backend == "ollama":
        return _make_ollama_fn(model, ollama_base_url)
    if backend == "sentence-transformers":
        return _make_st_fn(model)
    if backend == "gemini":
        if not api_key:
            raise ValueError("api_key is required for backend='gemini'")
        return _make_gemini_fn(model, api_key, task_type, output_dimensionality)
    raise ValueError(
        f"Unknown embedding backend '{backend}'. "
        "Must be 'ollama', 'sentence-transformers', or 'gemini'."
    )


def _make_st_fn(model: str) -> EmbedFn:
    from sentence_transformers import SentenceTransformer
    _st = SentenceTransformer(model)

    def embed(text: str) -> list[float]:
        return _st.encode(text).tolist()

    return embed


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


def _make_gemini_fn(
    model: str,
    api_key: str,
    task_type: str,
    output_dimensionality: int,
) -> EmbedFn:
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=api_key)

    def embed(text: str) -> list[float]:
        response = client.models.embed_content(
            model=model,
            contents=text[:_GEMINI_MAX_CHARS],
            config=types.EmbedContentConfig(
                task_type=task_type,
                output_dimensionality=output_dimensionality,
            ),
        )
        return list(response.embeddings[0].values)

    return embed
