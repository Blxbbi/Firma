"""
Phase 2 (Idee A) - Step2: scope/protected verifier unit tests.

Run via: ./tools/safe_test.sh tests/test_phase2_scope_verifier.py
"""
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.services.baseline_manifest import build_manifest, save_manifest
from engine.services.verifiers.scope_verifier import verify_scope
from engine.settings import INGEST_EXCLUSIONS


def _seed(root, layout):
    for rel, content in layout.items():
        full = os.path.join(root, rel)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w", encoding="utf-8") as f:
            f.write(content)


def _blpath(ws):
    """Baseline manifest path OUTSIDE the workspace tree (so it is not itself verified)."""
    return os.path.join(os.path.dirname(ws), "baseline_" + os.path.basename(ws) + ".json")


def _make_baseline(ws):
    bl = _blpath(ws)
    m = build_manifest(ws)
    save_manifest(m, bl)
    return bl


def _mutate(root, rel, content):
    full = os.path.join(root, rel)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w", encoding="utf-8") as f:
        f.write(content)


def _delete(root, rel):
    full = os.path.join(root, rel)
    if os.path.islink(full) or os.path.exists(full):
        os.remove(full)


# 1) only scoped file changes -> pass ------------------------------------------------
def test_scope_verifier_passes_when_only_scoped_file_changes():
    ws = tempfile.mkdtemp()
    try:
        _seed(ws, {"index.html": "a", "style.css": "OLD", "app.js": "c"})
        bl = _make_baseline(ws)
        _mutate(ws, "style.css", "NEW")  # in scope
        r = verify_scope(ws, bl, scope_files=["style.css"],
                         protected_files=["index.html", "app.js"])
        assert r.ok is True, r
        assert r.code is None, r
        assert r.changed == ["style.css"], r
    finally:
        shutil.rmtree(ws)


# 2) protected file change -> fail --------------------------------------------------
def test_scope_verifier_fails_on_protected_file_change():
    ws = tempfile.mkdtemp()
    try:
        _seed(ws, {"index.html": "a", "style.css": "s", "app.js": "OLD"})
        bl = _make_baseline(ws)
        _mutate(ws, "app.js", "HACKED")  # protected
        r = verify_scope(ws, bl, scope_files=["style.css"],
                         protected_files=["index.html", "app.js"])
        assert r.ok is False, r
        assert r.code == "PROTECTED_VIOLATION", r
    finally:
        shutil.rmtree(ws)


# 3) out-of-scope change -> fail ----------------------------------------------------
def test_scope_verifier_fails_on_out_of_scope_change():
    ws = tempfile.mkdtemp()
    try:
        _seed(ws, {"index.html": "a", "style.css": "s", "app.js": "OLD"})
        bl = _make_baseline(ws)
        _mutate(ws, "app.js", "CHANGED")  # not in scope, not protected
        r = verify_scope(ws, bl, scope_files=["style.css"], protected_files=[])
        assert r.ok is False, r
        assert r.code == "SCOPE_VIOLATION", r
    finally:
        shutil.rmtree(ws)


# 4) unexpected new file -> fail (allowlist overrides) ------------------------------
def test_scope_verifier_fails_on_unexpected_new_file():
    ws = tempfile.mkdtemp()
    try:
        _seed(ws, {"index.html": "a", "style.css": "s"})
        bl = _make_baseline(ws)
        _mutate(ws, "new.js", "console.log(1)")  # new, not in scope
        r = verify_scope(ws, bl, scope_files=["style.css"], protected_files=[])
        assert r.ok is False, r
        assert r.code == "UNEXPECTED_NEW_FILE", r
        # allowlist permits it
        r2 = verify_scope(ws, bl, scope_files=["style.css"], protected_files=[],
                          allow_new_files=["new.js"])
        assert r2.ok is True, r2
        assert r2.new == ["new.js"], r2
    finally:
        shutil.rmtree(ws)


# 5) same exclusions as baseline (node_modules change ignored) ----------------------
def test_scope_verifier_uses_same_exclusions_as_baseline():
    ws = tempfile.mkdtemp()
    try:
        _seed(ws, {"index.html": "OLD", "node_modules/x.js": "lib"})
        bl = _make_baseline(ws)  # excludes node_modules (INGEST_EXCLUSIONS)
        _mutate(ws, "node_modules/x.js", "TAMPERED")  # must be ignored
        _mutate(ws, "index.html", "NEW")              # in scope, must be detected
        r = verify_scope(ws, bl, scope_files=["index.html"], protected_files=[])
        assert r.ok is True, r
        # node_modules change NOT in diff; only the scoped index.html changed
        assert r.changed == ["index.html"], r
    finally:
        shutil.rmtree(ws)


# 6) deleted files: in-scope allowed, out-of-scope fails ----------------------------
def test_scope_verifier_handles_deleted_file():
    # 6a) delete an in-scope file -> allowed
    ws_a = tempfile.mkdtemp()
    try:
        _seed(ws_a, {"a.txt": "a", "b.txt": "b"})
        bl_a = _make_baseline(ws_a)
        _delete(ws_a, "a.txt")  # in scope
        r_a = verify_scope(ws_a, bl_a, scope_files=["a.txt"], protected_files=[])
        assert r_a.ok is True, r_a
        assert r_a.deleted == ["a.txt"], r_a
    finally:
        shutil.rmtree(ws_a)
    # 6b) delete an out-of-scope file -> SCOPE_VIOLATION
    ws_b = tempfile.mkdtemp()
    try:
        _seed(ws_b, {"a.txt": "a", "b.txt": "b"})
        bl_b = _make_baseline(ws_b)
        _delete(ws_b, "b.txt")  # not in scope
        r_b = verify_scope(ws_b, bl_b, scope_files=["a.txt"], protected_files=[])
        assert r_b.ok is False, r_b
        assert r_b.code == "SCOPE_VIOLATION", r_b
    finally:
        shutil.rmtree(ws_b)


# extra: baseline missing -> BASELINE_MISSING ---------------------------------------
def test_scope_verifier_baseline_missing():
    ws = tempfile.mkdtemp()
    try:
        _seed(ws, {"index.html": "a"})
        r = verify_scope(ws, _blpath(ws) + ".missing",
                         scope_files=["index.html"], protected_files=[])
        assert r.ok is False, r
        assert r.code == "BASELINE_MISSING", r
    finally:
        shutil.rmtree(ws)


if __name__ == "__main__":
    failures = []
    for name, fn in [
        ("test_scope_verifier_passes_when_only_scoped_file_changes", test_scope_verifier_passes_when_only_scoped_file_changes),
        ("test_scope_verifier_fails_on_protected_file_change", test_scope_verifier_fails_on_protected_file_change),
        ("test_scope_verifier_fails_on_out_of_scope_change", test_scope_verifier_fails_on_out_of_scope_change),
        ("test_scope_verifier_fails_on_unexpected_new_file", test_scope_verifier_fails_on_unexpected_new_file),
        ("test_scope_verifier_uses_same_exclusions_as_baseline", test_scope_verifier_uses_same_exclusions_as_baseline),
        ("test_scope_verifier_handles_deleted_file", test_scope_verifier_handles_deleted_file),
        ("test_scope_verifier_baseline_missing", test_scope_verifier_baseline_missing),
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
