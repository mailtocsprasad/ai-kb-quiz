"""Anthropic Claude premium model adapter.

User story: 1.2 — Route to premium model; resolve API key from env var then file.
"""
import os
from pathlib import Path

import anthropic


class PremiumAdapter:
    def __init__(self, model: str, client: anthropic.Anthropic):
        self._model = model
        self._client = client

    def generate(self, prompt: str) -> str:
        msg = self._client.messages.create(
            model=self._model,
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )
        return msg.content[0].text

    @classmethod
    def from_config(
        cls, model: str, api_key_file: Path | None = None
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
        return cls(model=model, client=anthropic.Anthropic(api_key=key))
