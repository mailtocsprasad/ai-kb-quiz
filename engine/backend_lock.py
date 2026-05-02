"""Detection cache for the 'auto' embedding backend setting.

Written once when embedding_backend: auto is first used. Read on every
subsequent call so auto-detection (which makes an HTTP probe to Ollama)
only runs once per machine setup. Each backend maintains its own separate
index directory, so switching backends never requires a rebuild.
"""
import json
from pathlib import Path

_LOCK_PATH = Path("kb_index/backend_lock.json")


def read_lock() -> dict | None:
    if _LOCK_PATH.exists():
        return json.loads(_LOCK_PATH.read_text(encoding="utf-8"))
    return None


def write_lock(backend: str, model: str, dimensions: int | None = None) -> None:
    _LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    _LOCK_PATH.write_text(
        json.dumps({"backend": backend, "model": model, "dimensions": dimensions}, indent=2),
        encoding="utf-8",
    )


def clear_lock() -> None:
    if _LOCK_PATH.exists():
        _LOCK_PATH.unlink()
