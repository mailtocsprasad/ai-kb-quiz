import hashlib
import json
from pathlib import Path


class ContextCache:
    """SHA-256 content-addressed cache for contextual embedding strings.

    Keyed by the hash of the chunk text so the same content never triggers
    more than one model call across index runs.
    """

    def __init__(self, cache_path: Path):
        self._path = cache_path
        self._data: dict[str, str] = {}
        if cache_path.exists():
            self._data = json.loads(cache_path.read_text(encoding="utf-8"))

    @staticmethod
    def _key(text: str) -> str:
        return hashlib.sha256(text.encode()).hexdigest()

    def get(self, text: str) -> str | None:
        return self._data.get(self._key(text))

    def set(self, text: str, context: str) -> None:
        self._data[self._key(text)] = context

    def save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(self._data, indent=2), encoding="utf-8")
