"""Google Gemini premium model adapter.

Mirrors PremiumAdapter's interface so either can be selected via config.
Key resolution: GEMINI_API_KEY env var (read automatically by the SDK),
then Gemini-Key.txt (key starts with AIza).
"""
import os
from pathlib import Path

from google import genai
from google.genai import types

_DEFAULT_SYSTEM = (
    "You are a concise technical tutor. Explain accurately and directly. "
    "No filler phrases. No markdown headers. Plain prose only."
)
_DEFAULT_MODEL = "gemini-2.5-flash"


class GeminiAdapter:
    def __init__(
        self,
        model: str,
        client: genai.Client,
        system_prompt: str = _DEFAULT_SYSTEM,
        max_tokens: int = 4096,
    ):
        self._model = model
        self._client = client
        self._system = system_prompt
        self._max_tokens = max_tokens

    def generate(self, prompt: str) -> str:
        response = self._client.models.generate_content(
            model=self._model,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=self._system,
                max_output_tokens=self._max_tokens,
            ),
        )
        return response.text or ""

    @classmethod
    def from_config(
        cls,
        model: str = _DEFAULT_MODEL,
        api_key_file: Path | None = None,
        system_prompt: str = _DEFAULT_SYSTEM,
        max_tokens: int = 4096,
    ) -> "GeminiAdapter":
        key = os.environ.get("GEMINI_API_KEY")
        if not key and api_key_file and Path(api_key_file).exists():
            lines = Path(api_key_file).read_text().splitlines()
            key = next((l.strip() for l in lines if l.strip().startswith("AIza")), "").strip()
        if not key:
            raise EnvironmentError(
                "No Gemini API key found. Set GEMINI_API_KEY env var "
                "or create the file specified by gemini_api_key_file in config.yaml."
            )
        # genai.Client(api_key=key) works; env var GEMINI_API_KEY is also picked up automatically.
        return cls(model=model, client=genai.Client(api_key=key), system_prompt=system_prompt, max_tokens=max_tokens)
