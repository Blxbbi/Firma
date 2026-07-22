"""Phase 6.1 — leichtgewichtige SessionRegistry.

Kein Process-Handle: wir speichern nur die deterministische Mapping
(run_id, task_id, role) -> session_id sowie den deterministischen
Session-Ordner fuer ``pi --session-dir``. Das ermoeglicht Context-Retention
ueber Retries derselben Task, OHNE live-gehaltene Prozesse (Windows-freundlich).

Strategie (vom User ratifiziert): *stateless processes, stateful session on disk*.
Jeder Retry spawned einen frischen ``pi -p --session-id <id> --session-dir <dir>``;
``pi`` laedt den Kontext aus der Session-Datei.
"""
import json
import shutil
from pathlib import Path
from typing import Optional

from engine.settings import FIRMA_MODE, SESSION_DIR, BASE_SESSION_DIR, PERSONA_ID


class SessionRegistry:
    """Mapping + Cleanup fuer pi-Sessions (pro Run)."""

    # Klassen-Attribute: bei Import aus Settings gelesen (env zur Laufzeit stabil).
    FIRMA_MODE = FIRMA_MODE
    SESSION_DIR = SESSION_DIR
    BASE_SESSION_DIR = BASE_SESSION_DIR
    PERSONA_ID = PERSONA_ID

    # Rollen -> Abteilung (fuer persona_base Base-Pfad)
    ROLE_DEPARTMENT = {"PLANNER": "planning", "CODER": "coding", "REVIEWER": "reviewing"}
    # Kanonische Session-ID der Base (beim Seeding in Ziel-Session-ID umbenannt)
    BASE_SESSION_ID = "base"
    BASE_SESSION_JSONL_SUFFIX = f"_{BASE_SESSION_ID}.jsonl"

    @classmethod
    def is_collaborative(cls) -> bool:
        """True wenn FIRMA_MODE=collaborative."""
        return cls.FIRMA_MODE == "collaborative"

    @staticmethod
    def session_id_for(run_id: str, task_id: str, role: str) -> str:
        """Deterministische, stabile Session-ID. Idempotent bei gleichen Inputs.

        Scope: pro (run_id, task_id, role) -> keine Leaks zwischen Runs,
        besser auditierbar, Cleanup pro Run moeglich.
        """
        return f"firma_{run_id}_{task_id}_{role}"

    @classmethod
    def session_dir_for(cls, run_id: str) -> Path:
        """Deterministischer Ordner fuer pi's --session-dir (pro Run)."""
        return Path(cls.SESSION_DIR) / str(run_id)

    @classmethod
    def base_session_dir_for(cls, department: str, persona_id: str, role: str) -> Path:
        """Deterministischer Ordner der Warm-Base fuer (department, persona, role)."""
        return Path(cls.BASE_SESSION_DIR) / department / persona_id / role

    @classmethod
    def session_dir_size_mb(cls, run_id: str) -> float:
        """Groesse des Session-Verzeichnisses eines Runs in MB (0.0 wenn nicht existent).

        Stufe 2 Disk-Guard: ermoeglicht fail-safe Spawn OHNE Session bei Ueberschreitung
        von MAX_SESSION_DISK_MB_PER_RUN, ohne den Run crashen zu lassen.
        """
        d = cls.session_dir_for(run_id)
        if not d.exists():
            return 0.0
        total = 0
        for p in d.rglob("*"):
            if p.is_file():
                total += p.stat().st_size
        return total / (1024 * 1024)

    @classmethod
    def _dir_size_mb(cls, path) -> float:
        """Groesse eines beliebigen Verzeichnisses in MB (0.0 wenn nicht existent)."""
        p = Path(path)
        if not p.exists():
            return 0.0
        total = 0
        for f in p.rglob("*"):
            if f.is_file():
                total += f.stat().st_size
        return total / (1024 * 1024)

    @classmethod
    def _find_base_session_file(cls, base_dir):
        """Findet die Base-Session-Datei (pi-Format: <ts>_<id>.jsonl, interne id=BASE_SESSION_ID)."""
        base_dir = Path(base_dir)
        if not base_dir.exists():
            return None
        # 1) Dateiname-Suffix (pi speichert als <ts>_<session-id>.jsonl)
        cands = list(base_dir.glob(f"*{cls.BASE_SESSION_JSONL_SUFFIX}"))
        if cands:
            return sorted(cands, reverse=True)[0]  # neueste Base (Reseed/Update)
        # 2) Fallback: interne id in erster JSONL-Zeile
        for f in base_dir.iterdir():
            if f.is_file() and f.suffix == ".jsonl":
                try:
                    first = f.read_text(encoding="utf-8").splitlines()[0]
                    if json.loads(first).get("id") == cls.BASE_SESSION_ID:
                        return f
                except Exception:
                    pass
        return None

    @staticmethod
    def _rewrite_session_id(path, new_id):
        """Schreibt die interne Session-id in der ersten JSONL-Zeile um (base -> target).
        pi matched Sessions ueber die interne id, nicht den Dateinamen."""
        p = Path(path)
        lines = p.read_text(encoding="utf-8").splitlines()
        if lines:
            try:
                obj = json.loads(lines[0])
                obj["id"] = new_id
                lines[0] = json.dumps(obj)
                p.write_text("\n".join(lines), encoding="utf-8")
            except Exception:
                pass

    @classmethod
    def _task_session_file(cls, task_dir, target_session_id):
        """Findet die bereits geseedete Task-Session-Datei (oder None)."""
        task_dir = Path(task_dir)
        if not task_dir.exists():
            return None
        cands = list(task_dir.glob(f"*_{target_session_id}.jsonl"))
        return cands[0] if cands else None

    @classmethod
    def copy_base_to_task(cls, base_dir, task_dir, target_session_id, cap_mb: int = 0) -> bool:
        """Seeded die Task-Session aus der Base (copy-on-start, atomar, cap-aware, pi-konform).

        Kopiert die Base-Session-Datei in ``task_dir`` und schreibt deren interne
        Session-id von BASE_SESSION_ID auf ``target_session_id`` um, damit ``pi`` den
        Warm-Context ueber ``--session-id <target>`` laden kann. Bestehende Task-Sessions
        (Retry) werden NICHT ueberschrieben (Continuity). Base bleibt immutable
        (nur copy-source, keine Mutation der Base).

        Return: True wenn geseedet, False bei Fallback (kein Base / Cap / bereits vorhanden).
        """
        base_dir = Path(base_dir)
        task_dir = Path(task_dir)
        if not base_dir.exists():
            return False  # kein Base -> Fallback auf task-mode (leere Task-Session)
        src = cls._find_base_session_file(base_dir)
        if src is None:
            return False  # keine Base-Session-Datei -> Fallback
        if cls._task_session_file(task_dir, target_session_id) is not None:
            return False  # bereits geseedet (Retry) -> Continuity erhalten
        if cap_mb and cls._dir_size_mb(base_dir) > cap_mb:
            return False  # Cap ueberschritten -> Fail-safe (kein Crash)
        task_dir.mkdir(parents=True, exist_ok=True)
        import datetime
        ts = datetime.datetime.now().strftime("%Y-%m-%dT%H-%M-%S-%fZ")
        dst_name = f"{ts}_{target_session_id}.jsonl"
        tmp = task_dir / (dst_name + ".seed_tmp")
        if tmp.exists():
            tmp.unlink()
        shutil.copyfile(str(src), str(tmp))
        cls._rewrite_session_id(tmp, target_session_id)  # pi matched ueber interne id
        final = task_dir / dst_name
        if final.exists():
            tmp.unlink()
            return False
        shutil.move(str(tmp), str(final))
        return True

    @staticmethod
    def touch(run_id: str, task_id: str, role: str) -> str:
        """Session-ID holen (idempotent). Alias fuer session_id_for."""
        return SessionRegistry.session_id_for(run_id, task_id, role)

    @classmethod
    def cleanup_run(cls, run_id: str) -> None:
        """Loescht den Session-Ordner des Runs.

        Wir haben KEINE persistenten Prozesse, daher reicht Datei-Cleanup
        (kein Kill noetig).
        """
        d = cls.session_dir_for(run_id)
        if d.exists():
            shutil.rmtree(d, ignore_errors=True)
