"""
Phase 2 (Idee A) — Step1: Ingest + Baseline-Manifest unit tests.

Run via: ./tools/safe_test.sh tests/test_phase2_ingest_baseline.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import hashlib
import json
import os
import shutil
import tempfile

from engine.services.baseline_manifest import (
    build_manifest,
    hash_file,
    save_manifest,
    load_manifest,
    diff_manifests,
)
from engine.services.ingest import copy_project_tree, ingest_project, _safe_join
from engine.settings import INGEST_EXCLUSIONS


def _make_tree(root, layout):
    """layout: dict rel_path -> content (str)."""
    for rel, content in layout.items():
        full = os.path.join(root, rel)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w", encoding="utf-8") as f:
            f.write(content)


# --- 1) Copy excludes build/cache dirs ------------------------------------------------
def test_copy_tree_excludes_dirs():
    src = tempfile.mkdtemp()
    try:
        _make_tree(src, {
            "index.html": "<html/>",
            "style.css": "body{}",
            ".git/config": "x",
            "node_modules/left-pad/index.js": "x",
            "dist/bundle.js": "x",
            "__pycache__/mod.cpython-314.pyc": "x",
            "sub/keep.txt": "keep",
        })
        dst = tempfile.mkdtemp()
        try:
            copy_project_tree(src, dst, INGEST_EXCLUSIONS)
            assert os.path.exists(os.path.join(dst, "index.html"))
            assert os.path.exists(os.path.join(dst, "sub", "keep.txt"))
            assert not os.path.exists(os.path.join(dst, ".git")), ".git copied!"
            assert not os.path.exists(os.path.join(dst, "node_modules")), "node_modules copied!"
            assert not os.path.exists(os.path.join(dst, "dist")), "dist copied!"
            assert not os.path.exists(os.path.join(dst, "__pycache__")), "__pycache__ copied!"
        finally:
            shutil.rmtree(dst)
    finally:
        shutil.rmtree(src)


# --- 2) Lockfiles are hash-relevant (NOT excluded) ------------------------------------
def test_manifest_hashes_lockfiles():
    src = tempfile.mkdtemp()
    try:
        _make_tree(src, {
            "package-lock.json": '{"lock":1}',
            "yarn.lock": "yarn",
            "requirements.txt": "flask",
            "app.js": "x",
        })
        m = build_manifest(src, INGEST_EXCLUSIONS)
        files = m["files"]
        assert "package-lock.json" in files, files
        assert "yarn.lock" in files
        assert "requirements.txt" in files
        expected = hashlib.sha256(b'{"lock":1}').hexdigest()
        assert files["package-lock.json"] == expected
    finally:
        shutil.rmtree(src)


# --- 3) Determinism: same tree -> same hash map ---------------------------------------
def test_manifest_is_deterministic_given_same_tree():
    src = tempfile.mkdtemp()
    try:
        _make_tree(src, {
            "a.txt": "a",
            "b/c.txt": "c",
            "d/e/f.txt": "f",
        })
        m1 = build_manifest(src, INGEST_EXCLUSIONS)
        m2 = build_manifest(src, INGEST_EXCLUSIONS)
        # determinism = hash map identical (created_at metadata may differ)
        assert m1["files"] == m2["files"], (m1["files"], m2["files"])
        # on-disk JSON is sorted/deterministic
        p1 = tempfile.mktemp(suffix=".json")
        p2 = tempfile.mktemp(suffix=".json")
        try:
            save_manifest(m1, p1)
            save_manifest(m2, p2)
            with open(p1) as f:
                s1 = f.read()
            with open(p2) as f:
                s2 = f.read()
            assert json.loads(s1)["files"] == json.loads(s2)["files"]
        finally:
            if os.path.exists(p1):
                os.remove(p1)
            if os.path.exists(p2):
                os.remove(p2)
    finally:
        shutil.rmtree(src)


# --- 4) No path traversal in copy ----------------------------------------------------
def test_no_path_traversal_in_copy():
    dst = tempfile.mkdtemp()
    try:
        # 4a) normalization guard (platform-independent)
        for bad in ("../escape.txt", "sub/../../escape.txt", "a/../../escape.txt"):
            try:
                _safe_join(dst, bad)
                raise AssertionError(f"expected ValueError for {bad!r}")
            except ValueError:
                pass
        # 4b) a symlink pointing OUTSIDE src must not leak content into dst
        src = tempfile.mkdtemp()
        try:
            outside = tempfile.mkdtemp()
            try:
                with open(os.path.join(outside, "secret.txt"), "w") as f:
                    f.write("TOPSECRET")
                os.makedirs(os.path.join(src, "linkdir"), exist_ok=True)
                link = os.path.join(src, "linkdir", "escape_link")
                try:
                    os.symlink(os.path.join(outside, "secret.txt"), link)
                except OSError:
                    return  # symlinks unsupported here; normalization guard already covers
                copy_project_tree(src, dst, INGEST_EXCLUSIONS)
                dst_secret = os.path.join(dst, "linkdir", "secret.txt")
                # symlink is copied AS a link (not followed); secret must not appear
                assert not os.path.exists(dst_secret), "symlink was followed outside dst!"
            finally:
                shutil.rmtree(outside)
        finally:
            shutil.rmtree(src)
    finally:
        shutil.rmtree(dst)


# --- extras ---------------------------------------------------------------------------
def test_hash_file_known_content():
    d = tempfile.mkdtemp()
    try:
        p = os.path.join(d, "f.txt")
        with open(p, "w") as f:
            f.write("hello")
        assert hash_file(p) == hashlib.sha256(b"hello").hexdigest()
    finally:
        shutil.rmtree(d)


def test_diff_manifests_changed_added_removed():
    baseline = {"files": {"a": "1", "b": "2", "c": "3"}}
    current = {"files": {"a": "1", "b": "9", "d": "4"}}
    diff = diff_manifests(baseline, current)
    assert diff["changed"] == ["b"], diff
    assert diff["added"] == ["d"], diff
    assert diff["removed"] == ["c"], diff


def test_save_load_roundtrip():
    src = tempfile.mkdtemp()
    try:
        _make_tree(src, {"x.txt": "x"})
        m = build_manifest(src, INGEST_EXCLUSIONS)
        p = tempfile.mktemp(suffix=".json")
        try:
            save_manifest(m, p)
            loaded = load_manifest(p)
            assert loaded["files"] == m["files"]
            assert loaded["version"] == m["version"]
        finally:
            if os.path.exists(p):
                os.remove(p)
    finally:
        shutil.rmtree(src)


def test_ingest_project_writes_manifest():
    src = tempfile.mkdtemp()
    ws = tempfile.mkdtemp()
    try:
        _make_tree(src, {
            "index.html": "<html/>",
            "style.css": "body{}",
            "app.js": "x",
        })
        m = ingest_project(src, "run-test-123", workspace_dir=ws)
        project_root = os.path.join(ws, "run-test-123", "project")
        manifest_path = os.path.join(ws, "run-test-123", "baseline_manifest.json")
        assert os.path.exists(os.path.join(project_root, "index.html"))
        assert os.path.exists(os.path.join(project_root, "app.js"))
        assert os.path.exists(manifest_path), "baseline_manifest.json not written"
        loaded = load_manifest(manifest_path)
        assert set(loaded["files"].keys()) == {"index.html", "style.css", "app.js"}
        assert m["run_id"] == "run-test-123"
        # source folder untouched (read-only ingest)
        assert os.path.exists(os.path.join(src, "index.html"))
    finally:
        shutil.rmtree(src)
        shutil.rmtree(ws)


if __name__ == "__main__":
    failures = []
    for name, fn in [
        ("test_copy_tree_excludes_dirs", test_copy_tree_excludes_dirs),
        ("test_manifest_hashes_lockfiles", test_manifest_hashes_lockfiles),
        ("test_manifest_is_deterministic_given_same_tree", test_manifest_is_deterministic_given_same_tree),
        ("test_no_path_traversal_in_copy", test_no_path_traversal_in_copy),
        ("test_hash_file_known_content", test_hash_file_known_content),
        ("test_diff_manifests_changed_added_removed", test_diff_manifests_changed_added_removed),
        ("test_save_load_roundtrip", test_save_load_roundtrip),
        ("test_ingest_project_writes_manifest", test_ingest_project_writes_manifest),
    ]:
        try:
            fn()
            print(f"PASS {name}")
        except Exception as e:  # noqa: BLE001
            print(f"FAIL {name}: {e}")
            failures.append(name)
    if failures:
        print(f"{len(failures)} FAILURES: {failures}")
        raise SystemExit(1)
    print("OK")
