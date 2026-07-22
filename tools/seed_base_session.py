#!/usr/bin/env python3
"""P2 — Seed-Utility fuer reproduzierbare persona_base Warm-Bases.

Erzeugt/Aktualisiert eine pi-Base-Session fuer (department, persona_id, role) und
verifiziert optional, dass die Base geladen wird (Sanity-Check via Marker).

Nutz den GLEICHEN PiProvider-Spawnpfad wie Firma (oneshot, -p), aber mit:
  --session-id base
  --session-dir <BASE_SESSION_DIR>/<dept>/<persona>/<role>

Keine produktive Run-Logik wird veraendert. Reine Base-Erzeugung + Verifikation.

Beispiel:
  python tools/seed_base_session.py --department coding --persona default --role CODER \
      --provider kilo --model kilo/kilo-auto/free --id base \
      --seed-prompt-file tools/seeds/coder_base.md
  python tools/seed_base_session.py --verify --department coding --persona default --role CODER \
      --provider kilo --model kilo/kilo-auto/free --id base --expect BASE_CONTEXT_OK
"""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine.session_registry import SessionRegistry
from engine.providers.pi_provider import PiProvider

SEED_DEFAULT_TIMEOUT = int(os.environ.get("FIRMA_SEED_TIMEOUT", "340"))

_DEFAULT_VERIFY_PROMPT = (
    "Check your session context. If the Firma CODER grounding/style conventions from the "
    "base session are present (this base is loaded), reply with exactly the token "
    "BASE_CONTEXT_OK on its own line. Otherwise reply NO_BASE."
)


def compute_base_dir(department: str, persona_id: str, role: str, session_dir=None) -> Path:
    """Deterministischer Base-Ordner.

    Ohne ``session_dir`` wird der kanonische Pfad aus Settings abgeleitet
    (BASE_SESSION_DIR/<dept>/<persona>/<role>); mit Override wird dieser genutzt
    (Tests/Isolation).
    """
    if session_dir:
        return Path(session_dir)
    return SessionRegistry.base_session_dir_for(department, persona_id, role)


def ensure_base_dir(base_dir: Path) -> Path:
    Path(base_dir).mkdir(parents=True, exist_ok=True)
    return Path(base_dir)


def _read_internal_id(path) -> object:
    try:
        first = Path(path).read_text(encoding="utf-8").splitlines()[0]
        return json.loads(first).get("id")
    except Exception:
        return None


def _split_model(model):
    if model and "/" in model:
        return model.split("/", 1)
    return None, model


def run_pi(base_dir, prompt, provider, model, session_id="base", dry_run=False, timeout=SEED_DEFAULT_TIMEOUT):
    """Spawned pi oneshot im Base-Ordner. Gibt (rc, stdout, stderr) zurueck.

    Nutzt denselben Build-Pfad wie Firma; stdout wird gecaptured (statt in eine
    Log-Datei umgeleitet), damit der Verify-Marker aus der Antwort gegreppt werden kann.
    """
    prov, mdl = _split_model(model)
    if provider:
        prov = provider
    provider_obj = PiProvider(provider=prov, model=mdl)
    args = provider_obj.build_args(
        prompt, model=mdl, provider=prov, session_id=session_id, session_dir=str(base_dir)
    )
    if dry_run:
        print("[seed] DRY-RUN pi args:", args)
        return 0, "", ""
    try:
        proc = subprocess.run(args, cwd=str(base_dir), capture_output=True, encoding="utf-8", errors="replace", timeout=timeout)
    except subprocess.TimeoutExpired as e:
        print(f"[seed] pi timeout nach {timeout}s", file=sys.stderr)
        return 124, getattr(e, "stdout", "") or "", getattr(e, "stderr", "") or ""
    return proc.returncode, proc.stdout, proc.stderr


def _print_result(base_dir, sfile, internal_id, success=None, dry_run=False):
    print("=== Ergebnis ===")
    print(f"base_dir    : {base_dir}")
    print(f"session_file: {sfile}")
    print(f"internal_id : {internal_id}")
    if dry_run:
        print("mode        : DRY-RUN (kein pi-Spawn)")
    elif success is not None:
        print(f"result      : {'SUCCESS' if success else 'FAIL'}")


def seed_session(args) -> int:
    base_dir = ensure_base_dir(compute_base_dir(args.department, args.persona, args.role, args.session_dir))
    prompt = Path(args.seed_prompt_file).read_text(encoding="utf-8")
    rc, out, err = run_pi(base_dir, prompt, args.provider, args.model, session_id=args.id,
                           dry_run=args.dry_run, timeout=args.timeout)
    if args.dry_run:
        _print_result(base_dir, None, None, dry_run=True)
        return 0
    if rc != 0:
        print(f"[seed] pi exited {rc}; stderr tail:\n{err[-600:]}", file=sys.stderr)
        _print_result(base_dir, None, None, success=False)
        return 1
    sfile = SessionRegistry._find_base_session_file(base_dir)
    if sfile is None:
        print("[seed] FEHLER: keine Base-Session-Datei erzeugt", file=sys.stderr)
        _print_result(base_dir, None, None, success=False)
        return 1
    internal_id = _read_internal_id(sfile)
    ok = (internal_id == args.id)
    _print_result(base_dir, sfile, internal_id, success=ok)
    return 0 if ok else 1


def verify_session(args) -> int:
    base_dir = compute_base_dir(args.department, args.persona, args.role, args.session_dir)
    sfile = SessionRegistry._find_base_session_file(base_dir)
    if sfile is None:
        print("[verify] FEHLER: keine Base-Session vorhanden (zuerst seeden)", file=sys.stderr)
        return 1
    prompt = args.verify_prompt or _DEFAULT_VERIFY_PROMPT
    rc, out, err = run_pi(base_dir, prompt, args.provider, args.model, session_id=args.id,
                           dry_run=args.dry_run, timeout=args.timeout)
    if args.dry_run:
        print("[verify] DRY-RUN")
        return 0
    if rc != 0:
        print(f"[verify] pi exited {rc}; stderr tail:\n{err[-600:]}", file=sys.stderr)
        return 1
    found = args.expect in out
    print("=== Verify-Ergebnis ===")
    print(f"base_dir: {base_dir}")
    print(f"expect  : {args.expect}")
    print(f"found   : {found}")
    print(f"result  : {'SUCCESS' if found else 'FAIL'}")
    return 0 if found else 1


def main():
    ap = argparse.ArgumentParser(description="Seed/Verify persona_base Warm-Base Sessions")
    ap.add_argument("--department", required=True, choices=["coding", "planning", "reviewing"])
    ap.add_argument("--persona", default="default")
    ap.add_argument("--role", required=True, choices=["CODER", "PLANNER", "REVIEWER"])
    ap.add_argument("--id", default="base")
    ap.add_argument("--seed-prompt-file", default=None)
    ap.add_argument("--provider", default=None)
    ap.add_argument("--model", default=None)
    ap.add_argument("--session-dir", default=None)
    ap.add_argument("--verify", action="store_true")
    ap.add_argument("--expect", default="BASE_CONTEXT_OK")
    ap.add_argument("--verify-prompt", default=None)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--timeout", type=int, default=SEED_DEFAULT_TIMEOUT)
    args = ap.parse_args()
    if args.verify:
        return verify_session(args)
    if not args.seed_prompt_file:
        ap.error("--seed-prompt-file required for seed mode")
    return seed_session(args)


if __name__ == "__main__":
    sys.exit(main())
