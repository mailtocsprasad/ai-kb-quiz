import json
from pathlib import Path
from typing import NamedTuple


class FileDiff(NamedTuple):
    new: list[Path]
    changed: list[Path]
    deleted: list[Path]

    def is_empty(self) -> bool:
        return not (self.new or self.changed or self.deleted)


class Manifest:
    """mtime-based file change tracker.

    Persists a JSON map of {abs_path: mtime} to disk. diff() compares the
    stored state against the current KB directory to produce a FileDiff.
    """

    def __init__(self, manifest_path: Path):
        self._path = manifest_path
        self._data: dict[str, float] = {}
        if manifest_path.exists():
            self._data = json.loads(manifest_path.read_text(encoding="utf-8"))

    def diff(self, kb_dir: Path) -> FileDiff:
        current: dict[str, float] = {
            str(p): p.stat().st_mtime
            for p in sorted(kb_dir.rglob("*.md"))
        }
        new, changed, deleted = [], [], []
        for key, mtime in current.items():
            if key not in self._data:
                new.append(Path(key))
            elif self._data[key] != mtime:
                changed.append(Path(key))
        for key in self._data:
            if key not in current:
                deleted.append(Path(key))
        return FileDiff(new=new, changed=changed, deleted=deleted)

    def update(self, path: Path) -> None:
        self._data[str(path)] = path.stat().st_mtime
        self._save()

    def remove(self, path: Path) -> None:
        self._data.pop(str(path), None)
        self._save()

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(self._data, indent=2), encoding="utf-8")
