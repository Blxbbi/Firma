from pathlib import Path
import os

# Root directory of the project
BASE_DIR = Path(__file__).resolve().parent.parent

# Transport backend selection (non-invasive switch)
# "in-process" -> InternalTransport + WorkerSim (Happy-Path baseline, default)
# "pimesh"     -> PiMeshTransport + PiMeshReceiverLoop (pi-harness worker mesh)
FIRMA_TRANSPORT = os.environ.get("FIRMA_TRANSPORT", "in-process").lower()

# Data and State
DATA_DIR = BASE_DIR / "data"
DB_DIR = DATA_DIR / "db"
ARTIFACT_DIR = DATA_DIR / "artifacts"

# Logs and Archive
ARCHIVE_DIR = BASE_DIR / "archive"
LOG_DIR = ARCHIVE_DIR / "logs"
TEMP_DIR = ARCHIVE_DIR / "temp"
LEGACY_DIR = ARCHIVE_DIR / "legacy_scripts"

# --- Phase 6.1: Collaborative Mode (Session-ID Strategie) ---
# FIRMA_MODE: deterministic (Default) | collaborative (Session-Kontext bei Retries)
FIRMA_MODE = os.environ.get("FIRMA_MODE", "deterministic").lower()
# Scope der Session-ID (V1: per_task -- eine Session pro Task/Role)
FIRMA_COLLAB_SESSION_SCOPE = os.environ.get("FIRMA_COLLAB_SESSION_SCOPE", "per_task").lower()
# Basisverzeichnis fuer pi's Session-Files (pro Run ein Unterordner)
SESSION_DIR = DATA_DIR / "sessions"

# PiMesh crew project directories (relative to BASE_DIR)
PIMESH_CREWS = {
    "PLANNER": "pimesh/planning-crew",
    "CODER": "pimesh/coding-crew",
    "REVIEWER": "pimesh/reviewing-crew",
}

# Worker-Modelle pro Rolle. Default = KEIN Zwang -> pi-Subprozess nutzt seinen
# EIGENEN Default (beim User: kilo/kilo-auto/free). PiProvider ist Compute-Substrat,
# kein Modell-Selektor. Nur via ENV erzwingen: FIRMA_MODEL_CODER="kilo/..."
PIMESH_MODELS = {
    "PLANNER": os.environ.get("FIRMA_MODEL_PLANNER"),
    "CODER": os.environ.get("FIRMA_MODEL_CODER"),
    "REVIEWER": os.environ.get("FIRMA_MODEL_REVIEWER"),
}

# Reviewer-Verhalten (Wiring-Ebene, kein Kernel-Change):
# True  -> deterministischer Dummy-Bypass: REVIEW_APPROVED wird direkt in die Transport-Queue
#          gepublished (kein LLM-Spawn, kein Timeout). Semantisch = Verifier im Kernel:
#          ein deterministischer Check (immer wahr), KEIN probabilistischer LLM-Call.
# False -> echter Reviewer-Worker wird via PiProvider gespawnt (fuer 5.2 / echte Code-Qualitaet).
REVIEWER_IS_DUMMY = os.environ.get("FIRMA_REVIEWER_DUMMY", "false").lower() in ("1", "true", "yes", "on")
# Phase 6.2: deterministischer Loop-Trigger (nur Dummy-Reviewer, wiring-Ebene).
# Reviewer lehnt beim 1. Versuch ab (REVIEW_FAILURE + Feedback), approviert beim Retry.
REVIEWER_DUMMY_REJECT_ONCE = os.environ.get("FIRMA_REVIEWER_DUMMY_REJECT_ONCE", "false").lower() in ("1", "true", "yes", "on")
# Phase 6.2: Eskalations-Cap fuer Reviewer-Ablehnungen (Coder<->Reviewer Streit).
# Nach N Reviewer-Ablehnungen -> Task FAILED_ITERATION_LIMIT (Eskalation Mensch/Lead,
# kein endloses Re-Dispatch). Benign Double-Invocation wird im Guardian deduped.
MAX_REVIEWER_REJECTIONS = int(os.environ.get("FIRMA_MAX_REVIEWER_REJECTIONS", "3"))


def ensure_directories():
    """Initialize the directory structure for the platform."""
    directories = [
        DATA_DIR, DB_DIR, ARTIFACT_DIR,
        ARCHIVE_DIR, LOG_DIR, TEMP_DIR, LEGACY_DIR
    ]
    for dir_path in directories:
        dir_path.mkdir(parents=True, exist_ok=True)

# Initialize directories immediately on import
ensure_directories()
