import time
import pytest
from pathlib import Path
from engine.manifest import Manifest, FileDiff


@pytest.fixture
def kb(tmp_path):
    d = tmp_path / "kb"
    d.mkdir()
    return d


@pytest.fixture
def manifest_path(tmp_path):
    return tmp_path / "manifest.json"


def test_diff_all_new_on_empty_manifest(kb, manifest_path):
    (kb / "a.md").write_text("hello")
    (kb / "b.md").write_text("world")
    diff = Manifest(manifest_path).diff(kb)
    assert len(diff.new) == 2
    assert diff.changed == []
    assert diff.deleted == []


def test_diff_no_changes_after_update(kb, manifest_path):
    f = kb / "a.md"
    f.write_text("hello")
    m = Manifest(manifest_path)
    m.update(f)
    diff = m.diff(kb)
    assert diff.is_empty()


def test_diff_detects_changed_file(kb, manifest_path):
    f = kb / "a.md"
    f.write_text("hello")
    m = Manifest(manifest_path)
    m.update(f)
    time.sleep(0.01)
    f.write_text("changed")
    import os
    os.utime(f, (f.stat().st_atime, f.stat().st_mtime + 1))
    diff = m.diff(kb)
    assert Path(str(f)) in diff.changed or len(diff.changed) == 1


def test_diff_detects_deleted_file(kb, manifest_path):
    f = kb / "a.md"
    f.write_text("hello")
    m = Manifest(manifest_path)
    m.update(f)
    f.unlink()
    diff = m.diff(kb)
    assert len(diff.deleted) == 1


def test_remove_clears_entry(kb, manifest_path):
    f = kb / "a.md"
    f.write_text("hello")
    m = Manifest(manifest_path)
    m.update(f)
    m.remove(f)
    diff = m.diff(kb)
    assert len(diff.new) == 1


def test_manifest_persists_across_instances(kb, manifest_path):
    f = kb / "a.md"
    f.write_text("hello")
    m1 = Manifest(manifest_path)
    m1.update(f)
    m2 = Manifest(manifest_path)
    assert m2.diff(kb).is_empty()


def test_diff_is_empty_returns_false_when_changes(kb, manifest_path):
    (kb / "a.md").write_text("new")
    diff = Manifest(manifest_path).diff(kb)
    assert not diff.is_empty()


def test_non_md_files_ignored(kb, manifest_path):
    (kb / "notes.txt").write_text("ignore me")
    diff = Manifest(manifest_path).diff(kb)
    assert diff.is_empty()
