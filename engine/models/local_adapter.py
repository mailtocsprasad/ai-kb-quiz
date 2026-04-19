"""Ollama local model adapter.

User story: 1.1 — Route to local model via Ollama HTTP API.
"""
import httpx


class LocalAdapter:
    def __init__(self, model: str, client: httpx.Client | None = None):
        self._model = model
        self._client = client or httpx.Client()
        self._url = "http://localhost:11434/api/generate"

    def generate(self, prompt: str) -> str:
        try:
            resp = self._client.post(
                self._url,
                json={"model": self._model, "prompt": prompt, "stream": False},
                timeout=60.0,
            )
            resp.raise_for_status()
            return resp.json().get("response", "")
        except Exception:
            return ""
