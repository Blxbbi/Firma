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
ARCHIVE_RUNS_DIR = ARCHIVE_DIR / "runs"
TEMP_DIR = ARCHIVE_DIR / "temp"
LEGACY_DIR = ARCHIVE_DIR / "legacy_scripts"

# Phase 2 (Idee A): Ingest + Baseline-Manifest
WORKSPACE_DIR = BASE_DIR / "workspace"
# Zentrale Exclusions (Dir-/Datei-Namen), damit Tests nicht hardcoden muessen.
# Lockfiles (package-lock.json, yarn.lock, requirements.txt, ...) sind BEWUSST NICHT
# exkludiert -> sie sind hash-relevant; Aenderung ausserhalb scope -> VERIFY_FAILURE (Step2).
INGEST_EXCLUSIONS = (
    ".git", ".pi", "node_modules", "__pycache__", "dist", "build",
    ".venv", "venv", ".mypy_cache", ".pytest_cache", ".idea", ".vscode",
)
# v1 Trigger (Prototyp): existierender Projektordner, der inkrementell bearbeitet wird.
# Wenn unset -> from-scratch Run (unveraendertes Verhalten).
INGEST_PROJECT_DIR = os.environ.get("FIRMA_PROJECT_DIR")

# Phase 7 (Idee D): Run-Archiv-Retention
KEEP_LAST_N = int(os.environ.get("FIRMA_ARCHIVE_KEEP_LAST_N", "20"))
KEEP_COMPRESSED_LAST_N = int(os.environ.get("FIRMA_ARCHIVE_KEEP_COMPRESSED_LAST_N", "100"))

# --- Phase 6.1: Collaborative Mode (Session-ID Strategie) ---
# FIRMA_MODE: deterministic (Default) | collaborative (Session-Kontext bei Retries)
FIRMA_MODE = os.environ.get("FIRMA_MODE", "deterministic").lower()
# Scope der Session-ID (V1: per_task -- eine Session pro Task/Role)
FIRMA_COLLAB_SESSION_SCOPE = os.environ.get("FIRMA_COLLAB_SESSION_SCOPE", "per_task").lower()
# Basisverzeichnis fuer pi's Session-Files (pro Run ein Unterordner)
SESSION_DIR = DATA_DIR / "sessions"

# --- Phase 6.3 Step 1: entkoppelte Modi-Achsen (reines Plumbing) ---
# Zwei unabhaengige Achsen statt "FIRMA_MODE == Semantik".
#   SESSION_MODE: off | task | persona_base   (Default: off == heute deterministic)
#       off          -> pi --no-session (ephemeral, keine Disk-Session)
#       task         -> Session pro (run, task, role); Retry-Continuity
#       persona_base -> Base-Session pro (department, persona) wird copy-on-start
#                       genutzt (6.3.a, spaeter; braucht Base-Seeding + Copy + Caps)
#   PROCESS_MODE: oneshot | resident         (Default: oneshot)
#       oneshot  -> pi -p fire-and-forget (Prozess stirbt nach Task)
#       resident -> pi bleibt am Leben, stdin-Feed (deferred, siehe Plan §12)
# FIRMA_MODE (deterministic|collaborative) bleibt unveraendert (Routing/Loop-Semantik),
# ist aber NICHT mehr alleiniger Schalter fuer Sessions.
_ALLOWED_SESSION_MODES = ("off", "task", "persona_base")
SESSION_MODE = os.environ.get("FIRMA_SESSION_MODE", "off").lower()
if SESSION_MODE not in _ALLOWED_SESSION_MODES:
    SESSION_MODE = "off"  # ungueltig -> sicherer Default (kein stilles Aktivieren)

_ALLOWED_PROCESS_MODES = ("oneshot", "resident")
PROCESS_MODE = os.environ.get("FIRMA_PROCESS_MODE", "oneshot").lower()
if PROCESS_MODE not in _ALLOWED_PROCESS_MODES:
    PROCESS_MODE = "oneshot"  # ungueltig -> sicherer Default

# Phase 6.3 Stufe 2: Disk-Guardrail (MVP). 0 = deaktiviert.
# Wenn die Session-Daten eines Runs das Cap ueberschreiten, werden weitere Spawns
# fail-safe OHNE Session ausgefuehrt (kein Crash, keine unkontrollierte Disk-Growth).
MAX_SESSION_DISK_MB_PER_RUN = int(os.environ.get("FIRMA_MAX_SESSION_DISK_MB_PER_RUN", "200"))

# Phase 6.3.a persona_base: Base-Session-Verzeichnis + Default-Persona
# _base/<department>/<persona_id>/<role>/ enthaelt die geseedete Warm-Base (nur Kontext,
# keine Task-Outputs). Immutable: nie in Base spawnen, nur copy-source.
BASE_SESSION_DIR = SESSION_DIR / "_base"
PERSONA_ID = os.environ.get("FIRMA_PERSONA_ID", "default")

# Phase 6.3 P1: Concurrency-Limiter fuer pimesh-Spawns (Free-tier Rate-Limit-Schutz).
# Default 2 (konservativ); fuer Free-Tier Dev auf 1 setzen (voll serialisiert).
MAX_CONCURRENT_SPAWNS = int(os.environ.get("FIRMA_MAX_CONCURRENT_SPAWNS", "2"))

# PiMesh crew project directories (relative to BASE_DIR)
PIMESH_CREWS = {
    "PLANNER": "pimesh/planning-crew",
    "CODER": "pimesh/coding-crew",
    "REVIEWER": "pimesh/reviewing-crew",
    # Phase 3 (Idee B): Researcher needs a crew too, otherwise pimesh cannot route it.
    # Reuses planning-crew's environment (the prompt defines the role, not the dir).
    "RESEARCHER": "pimesh/planning-crew",
}

# Worker-Modelle pro Rolle. Default = KEIN Zwang -> pi-Subprozess nutzt seinen
# EIGENEN Default (beim User: kilo/kilo-auto/free). PiProvider ist Compute-Substrat,
# kein Modell-Selektor. Nur via ENV erzwingen: FIRMA_MODEL_CODER="kilo/..."
PIMESH_MODELS = {
    "PLANNER": os.environ.get("FIRMA_MODEL_PLANNER"),
    "CODER": os.environ.get("FIRMA_MODEL_CODER"),
    "REVIEWER": os.environ.get("FIRMA_MODEL_REVIEWER"),
    "RESEARCHER": os.environ.get("FIRMA_MODEL_RESEARCHER"),
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

# R2 Web Research (opt-in, default off).
FIRMA_RESEARCH_WEB = os.environ.get("FIRMA_RESEARCH_WEB", "0").lower() in ("1", "true", "yes", "on")
FIRMA_RESEARCH_WEB_MAX_QUERIES = int(os.environ.get("FIRMA_RESEARCH_WEB_MAX_QUERIES", "3"))
FIRMA_RESEARCH_WEB_TIMEOUT_S = int(os.environ.get("FIRMA_RESEARCH_WEB_TIMEOUT_S", "30"))


def ensure_directories():
    """Initialize the directory structure for the platform."""
    directories = [
        DATA_DIR, DB_DIR, ARTIFACT_DIR,
        ARCHIVE_DIR, LOG_DIR, ARCHIVE_RUNS_DIR, TEMP_DIR, LEGACY_DIR,
        WORKSPACE_DIR,
    ]
    for dir_path in directories:
        dir_path.mkdir(parents=True, exist_ok=True)

# Initialize directories immediately on import
ensure_directories()
