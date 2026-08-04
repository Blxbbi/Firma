"""
PiProvider — Compute-Substrat fuer die PiMesh-Worker.

Firma (Orchestrator/State-Authority) spawned pro Assignment einen `pi`-Worker-Prozess
im jeweiligen Crew-Directory (cwd = Crew-Dir). Der Worker kennt seine Rolle ueber
den Prompt (der auf die von PiMeshTransport geschriebene task-N.md verweist) und
schreibt Artefakte + worker_response.<task_id>.response.json in sein Crew-cwd.

Dies ist exakt die Spawn-Mechanik von pi-messenger (crew/agents.ts: spawnAgents),
nur dass Firma den Spawn selbst uebernimmt -> kein pi_messenger-Tool-Aufruf noetig,
kein cwd-Problem (jeder Spawn hat sein eigenes cwd = Crew-Dir).

Verifiziert (14.07.2026): `pi --mode json -p "..."` im Crew-Dir erreicht das LLM
(kilo/kilo-auto/free) und arbeitet relativ zum Crew-cwd.
"""
import logging
import os
import shutil
import subprocess
import threading
from typing import Optional

from engine.settings import FIRMA_RESEARCH_WEB, FIRMA_RESEARCH_WEB_MAX_QUERIES, FIRMA_RESEARCH_WEB_TIMEOUT_S

logger = logging.getLogger(__name__)


def _close_log_when_done(proc: subprocess.Popen, log_f) -> None:
    """Wait for the child process to exit, then close the log file handle."""
    try:
        proc.wait()
    finally:
        try:
            log_f.close()
        except Exception:
            pass

# Phase 2/3 (Idee A + Idee B): exclusions for the ingest project copy into the crew
# workdir. We never copy .pi/ (worker metadata), .git/, or node_modules/ into the
# task workdir -- they are irrelevant for the worker and pollute the artifact scan.
_INGEST_COPY_IGNORES = {'.pi', '.git', 'node_modules', '__pycache__', '.gitignore', '.gitattributes'}


def _should_ignore_project_file(path: str) -> bool:
    """Return True if a project file/dir should be excluded from the ingest copy.

    Matches exact basename ignores (fast) and guards against absolute/ traversal
    paths (Security Boundary)."""
    if not path or path.startswith('/') or path.startswith('\\') or '..' in path:
        return True
    name = os.path.basename(path)
    return name in _INGEST_COPY_IGNORES



class PiProvider:
    """Spawned Pi als zustandsloser Worker-Prozess (Compute-Substrat)."""

    def __init__(
        self,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        tools: str = "read,write,edit,bash",
        extension_dir: Optional[str] = None,
    ):
        # provider/model = None -> pi-Subprozess nutzt seinen eigenen Default
        # (Compute-Substrat, kein Modell-Selektor). Nur explizit erzwingen.
        self.provider = provider
        self.model = model
        self.tools = tools
        self.extension_dir = self._normalize_extension_dir(extension_dir or self._find_extension()) if (extension_dir or self._find_extension()) else None

    @staticmethod
    def tools_for_role(role: str, mode: Optional[str] = None) -> str:
        """Return the default toolset for a given role/mode.

        - REVIEWER/PLANNER/RESEARCHER: read/write only (no bash/edit).
        - CODER from-scratch: read/write/edit (bash off).
        - CODER ingest/edit: read/write/edit (bash off).
        """
        role = (role or "").upper()
        if role in {"REVIEWER", "PLANNER", "RESEARCHER"}:
            return "read,write"
        if role == "CODER":
            return "read,write,edit"
        return "read,write,edit,bash"

    @staticmethod
    def _find_extension() -> Optional[str]:
        base = os.path.expanduser("~/.pi/agent/npm/node_modules/pi-messenger")
        if os.path.isdir(base):
            return base
        # fallback: global npm root
        try:
            out = subprocess.run(
                ["npm", "root", "-g"], capture_output=True, text=True, timeout=10
            )
            cand = os.path.join(out.stdout.strip(), "pi-messenger")
            if os.path.isdir(cand):
                return cand
        except Exception:
            pass
        return None

    def _resolve_exe(self) -> str:
        for exe in ("pi.cmd", "pi"):
            found = shutil.which(exe)
            if found:
                return found
        return "pi"

    def _normalize_extension_dir(self, path: str) -> str:
        """Convert backslashes to forward slashes for Windows paths used with pi.
        
        This prevents the shell args parser from interpreting escape sequences
        like \n and breaking the --extension argument.
        """
        return path.replace("\\", "/")

    def _normalize_exe_for_windows(self, exe: str) -> list:
        """Return executable args suitable for subprocess on Windows.

        `.cmd` / `.bat` need explicit shell execution on Windows; otherwise `Popen`
        can fail with `FileNotFoundError` even though the file exists.
        """
        if os.name == "nt" and isinstance(exe, str) and exe.lower().endswith((".cmd", ".bat")):
            return ["cmd.exe", "/c", exe]
        return [exe]

    def build_args(self, prompt: str, model: Optional[str] = None, provider: Optional[str] = None, session_id: Optional[str] = None, session_dir: Optional[str] = None) -> list:
        raw_exe = self._resolve_exe()
        exe_args = self._normalize_exe_for_windows(raw_exe)
        prov = provider or self.provider
        mdl = model or self.model
        args = exe_args + ["--mode", "json"]
        if session_id:
            # Collaborative (Phase 6.1): Session-Kontext tragen -- KEIN --no-session!
            args += ["--session-id", session_id, "--session-dir", str(session_dir)]
        else:
            # Deterministic: ephemeral, kein Session-Speicher
            args += ["--no-session"]
        # Nur erzwingen, wenn explicit gesetzt -- sonst nutzt pi seinen eigenen Default.
        if prov and mdl:
            args += ["--provider", prov, "--model", mdl]
        args += ["--tools", self.tools]
        if self.extension_dir:
            # Normalize extension dir to forward slashes to avoid shell escaping problems
            normalized_ext_dir = self._normalize_extension_dir(self.extension_dir)
            args += ["--extension", normalized_ext_dir]
        args += ["-p", prompt]
        return args

    @staticmethod
    def build_assignment_prompt(
        task_id: str,
        role: str = "CODER",
        correction_note: Optional[str] = None,
    ) -> str:
        """Prompt fuer den Worker: lies die Task-Spec und folge dem Vertrag.

        Kein eingebettetes JSON (wird von `pi -p` abgeschnitten) -- der Worker
        liest die vollstaendige Spec aus der task-N.md (von PiMeshTransport geschrieben).

        `correction_note` (nur bei CODER-Retry): zwingender OVERRIDE-Hinweis, der die
        durch Session-Kontinuitaet mitgeschleppte "Ich bin fertig"-Selbstaussage des
        Vorgaengers neutralisiert (Phase 6.2 Fix 1: Retry-Scrub).
        """
        role_verb = {
            "CODER": "implement the task by writing the required files",
            "REVIEWER": "review the coder's implementation and write your assessment",
            "PLANNER": "plan the task by creating a plan document",
            "RESEARCHER": "research the topic and write your findings",
            "VERIFIER": "verify the implementation against acceptance criteria",
        }.get(role.upper(), "implement the task by writing the required files")

        base = (
            f"Read the file `.pi/messenger/crew/tasks/{task_id}.md` in the current working "
            f"directory and follow its instructions EXACTLY: {role_verb}, then write the "
            f"worker_response file named in the spec, then stop. "
            f"Do not ask questions and do not call any mesh/pi_messenger tools."
        )
        if correction_note:
            base += "\n\n" + correction_note
        return base

    def spawn_for_assignment(
        self,
        role: str,
        task_id: str,
        run_id: str,
        state_revision: int,
        crew_cwd: str,
        model: Optional[str] = None,
        session_id: Optional[str] = None,
        session_dir: Optional[str] = None,
        correction_note: Optional[str] = None,
        tools: Optional[str] = None,
    ):
        prov = None
        mdl = model
        if model and "/" in model:
            prov, mdl = model.split("/", 1)

        effective_tools = tools if tools is not None else PiProvider.tools_for_role(role)
        provider = PiProvider(provider=prov, model=mdl, tools=effective_tools, extension_dir=self.extension_dir)
        print('DEBUG_SPAWN extension_dir=', repr(provider.extension_dir), flush=True)
        project_workdir = provider._stage_ingest_project_if_needed(role, run_id, task_id, crew_cwd)

        prompt = provider.build_assignment_prompt(task_id, role=role, correction_note=correction_note)
        if project_workdir:
            if role == "CODER":
                prompt = (
                    f"INGEST MODE: the existing project files are staged under "
                    f"`.pi/work/{run_id}/{task_id}/project/` (relative to this working directory). "
                    f"Read them from there to perform a surgical edit. Write your edited files "
                    f"to the top level of `.pi/messenger/crew/` (e.g. `style.css`, not "
                    f"`project/style.css`) so the kernel can pick them up. Do NOT modify the "
                    f"staged copy under `.pi/work/` -- it is read-only reference only.\n\n"
                    + prompt
                )
            elif role == "RESEARCHER":
                web_rules = ""
                if FIRMA_RESEARCH_WEB:
                    web_rules = (
                        f"\n\n[Web Research] You MAY perform web research (max "
                        f"{FIRMA_RESEARCH_WEB_MAX_QUERIES} queries, "
                        f"{FIRMA_RESEARCH_WEB_TIMEOUT_S}s timeout per query) to supplement your findings. "
                        f"Use `curl` or `wget` for HTTP requests only. For every external claim, add a source URL. "
                        f"If web research is unavailable or fails, continue with local findings only and note "
                        f"'Web research unavailable: <reason>' in your brief.\n\n"
                        f"[Contract] You MUST include the section "
                        f"'## External research (sources)' in your brief. "
                        f"If you cannot provide sources, write exactly: "
                        f"'Web research unavailable: <reason>'. "
                        f"Missing this section is non-fatal and will be logged as non-compliance, not as task failure.\n\n"
                    )
                prompt = (
                    f"INGEST MODE: the existing project files are staged under "
                    f"`.pi/work/{run_id}/{task_id}/project/` (relative to this working directory). "
                    f"Read them from there to understand the project. You are STRICT READ-ONLY: "
                    f"do NOT modify any file in `.pi/work/` or anywhere else. Write your findings "
                    f"to `research/brief.md` (under `.pi/messenger/crew/`). For every claim about "
                    f"the code, add a citation with `file: <relative path>`, `line: <N or range>`, "
                    f"and `evidence: <exact snippet or search term>`."
                    f"{web_rules}\n\n"
                    + prompt
                )
        # V1: write the full prompt to a file to avoid shell argument limits.
        # The worker reads the file instead of receiving a potentially huge -p argument.
        prompt_file = os.path.join(crew_cwd, ".pi", "work", run_id, task_id, "prompt.txt")
        os.makedirs(os.path.dirname(prompt_file), exist_ok=True)
        with open(prompt_file, "w", encoding="utf-8") as f:
            f.write(prompt)

        # Short, deterministic prompt referencing the file.
        # NOTE: do NOT inline the full prompt here — on Windows, the command line
        # limit (~8191 chars) is easily exceeded by large prompts, causing
        # "Die Befehlszeile ist zu lang" before the worker even starts.
        # Use an absolute path so the worker cannot hallucinate a wrong relative path.
        abs_prompt_path = os.path.abspath(prompt_file)
        short_prompt = (
            f"Read your complete assignment from the file at path: {abs_prompt_path}\n"
            f"Follow its instructions EXACTLY. Do not ask questions and do not call any mesh/pi_messenger tools."
        )
        # Per-task log to avoid collision across concurrent spawns.
        log_path = os.path.join(crew_cwd, ".pi", "work", run_id, task_id, "worker.log")
        return provider.spawn_worker(
            crew_cwd, short_prompt, model=mdl, provider=prov, session_id=session_id, session_dir=session_dir, log_path=log_path
        )

    @staticmethod
    def _stage_ingest_project_if_needed(role: str, run_id: str, task_id: str, crew_cwd: str) -> Optional[str]:
        """Copy the ingest project tree into a task-specific workdir for CODER/RESEARCHER.

        Returns the absolute workdir path if staging happened, else None.
        """
        if role not in ("CODER", "RESEARCHER"):
            return None
        try:
            from engine.services.ingest_context import get_ingest
            from engine.settings import WORKSPACE_DIR
        except Exception:
            return None
        ing = get_ingest(run_id)
        if not ing:
            return None
        src = ing.get("workspace_root")
        if not src or not os.path.isdir(src):
            return None
        # Task-specific workdir inside the crew cwd (clean separation per run/task).
        dst = os.path.join(crew_cwd, ".pi", "work", run_id, task_id, "project")
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        if os.path.exists(dst):
            shutil.rmtree(dst)
        # Deterministic, exclusion-aware copy (small projects -> copytree is fine).
        shutil.copytree(
            src,
            dst,
            ignore=lambda d, names: [n for n in names if _should_ignore_project_file(os.path.join(d, n))],
        )
        logger.info("[PiProvider] staged ingest project for %s/%s -> %s", run_id, task_id, dst)
        return dst

    def spawn_worker(self, crew_cwd: str, prompt: str, model: Optional[str] = None, provider: Optional[str] = None, session_id: Optional[str] = None, session_dir: Optional[str] = None, log_path: Optional[str] = None):
        """Spawned einen Pi-Worker in `crew_cwd`. Gibt das Popen-Objekt zurueck.

        Der Worker liest die task-N.md (von PiMeshTransport geschrieben), folgt dem
        Worker-Vertrag, schreibt Artefakte + worker_response und kehrt zurueck.

        WICHTIG: stdout/stderr werden in eine Log-Datei umgeleitet (NICHT PIPE),
        sonst blockiert der Worker, sobald der OS-Pipe-Puffer voll ist (Deadlock).
        """
        args = self.build_args(prompt, model=model, provider=provider, session_id=session_id, session_dir=session_dir)
        if not log_path:
            log_path = os.path.join(crew_cwd, ".pi", "worker.log")
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        # Append mode: safer across retries/restarts; per-task log avoids collision.
        log_f = open(log_path, "a", encoding="utf-8")
        model_label = f"{self.provider}/{self.model}" if (self.provider and self.model) else "pi-default"
        logger.info(f"[PiProvider] spawn worker in {crew_cwd} (model={model_label}); log={log_path}")
        print('DEBUG_SPAWN_ARGS', args, flush=True)
        proc = subprocess.Popen(
            args,
            cwd=crew_cwd,
            stdout=log_f,
            stderr=subprocess.STDOUT,
        )
        # Keep the log file handle alive for the lifetime of the child process.
        # Without this, the handle can be closed/garbage-collected on Windows,
        # causing the worker to die silently before it can write a response.
        try:
            proc._log_f = log_f  # type: ignore[attr-defined]
        except Exception:
            pass
        # Ensure the log file is closed when the child process exits, to avoid
        # ResourceWarning: unclosed file warnings from asyncio.
        try:
            _waiter = threading.Thread(
                target=_close_log_when_done,
                args=(proc, log_f),
                daemon=True,
            )
            _waiter.start()
        except Exception:
            pass
        return proc
