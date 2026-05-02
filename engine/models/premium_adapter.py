"""Anthropic Claude premium model adapter.

User story: 1.2 — Route to premium model; resolve API key from env var then file.
"""
import os
from pathlib import Path

import anthropic

_DEFAULT_SYSTEM = (
    "You are a concise technical tutor. Explain accurately and directly. "
    "No filler phrases. No markdown headers. Plain prose only."
)


class PremiumAdapter:
    def __init__(
        self,
        model: str,
        client: anthropic.Anthropic,
        system_prompt: str = _DEFAULT_SYSTEM,
        max_tokens: int = 4096,
    ):
        self._model = model
        self._client = client
        self._system = system_prompt
        self._max_tokens = max_tokens

    def generate(self, prompt: str) -> str:
        msg = self._client.messages.create(
            model=self._model,
            max_tokens=self._max_tokens,
            system=[
                {
                    "type": "text",
                    "text": self._system,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[{"role": "user", "content": prompt}],
        )
        return msg.content[0].text

    @classmethod
    def from_config(
        cls,
        model: str,
        api_key_file: Path | None = None,
        system_prompt: str = _DEFAULT_SYSTEM,
        max_tokens: int = 4096,
    ) -> "PremiumAdapter":
        key = os.environ.get("ANTHROPIC_API_KEY")
        if not key and api_key_file and Path(api_key_file).exists():
            lines = Path(api_key_file).read_text().splitlines()
            key = next((l.strip() for l in lines if l.strip().startswith("sk-ant-")), "").strip()
        if not key:
            raise EnvironmentError(
                "No API key found. Set ANTHROPIC_API_KEY env var "
                "or create the file specified by api_key_file in config.yaml."
            )
        return cls(model=model, client=anthropic.Anthropic(api_key=key), system_prompt=system_prompt, max_tokens=max_tokens)
