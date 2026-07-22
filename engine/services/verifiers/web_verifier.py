import logging
from typing import Tuple, List, Dict, Any
from sqlalchemy.orm import Session
from engine.services.verification_registry import BaseVerifier
from engine.models import Task

logger = logging.getLogger(__name__)


class WebStructuralVerifier(BaseVerifier):
    """
    Generischer struktureller Web-Verifier.

    Nutzt die Task-eigenen `acceptance_criteria` (EXISTS:<pfad> / CONTAINS:<pfad>:<substr>)
    statt hartcodierter Snake-Annahmen. Damit funktionieren sowohl die Snake-App
    (Kriterien enthalten <canvas / requestAnimationFrame) als auch beliebige
    Web-Apps (z.B. Counter mit <button / addEventListener / innerHTML).
    """

    async def verify(
        self,
        session: Session,
        task_id: str,
        project_id: str,
        plan_version: int,
        artifacts: List[Dict[str, Any]],
    ) -> Tuple[bool, str]:
        if not artifacts:
            return False, "MISSING_CONTENT: No artifacts provided for verification."

        # Task-eigene Akzeptanzkriterien laden (pro Task, nicht global).
        task = await session.get(Task, task_id)
        criteria = []
        if task and task.acceptance_criteria:
            try:
                raw = task.acceptance_criteria
                criteria = raw if isinstance(raw, list) else (raw or [])
            except Exception:
                criteria = []

        # Pfad -> Inhalt (case-insensitive Pfad-Keys fuer den Abgleich).
        content_by_path = {}
        for a in artifacts:
            p = (a.get("path") or "").lower()
            content_by_path[p] = a.get("content") or ""

        if not criteria:
            # Keine Kriterien: lenient akzeptieren, sofern ueberhaupt Artefakte da sind.
            return True, "No acceptance criteria defined; artifacts present -> accepted."

        failures = []
        for crit in criteria:
            if not isinstance(crit, str):
                continue
            if crit.startswith("EXISTS:"):
                target = crit[len("EXISTS:"):].strip().lower()
                if target not in content_by_path:
                    failures.append(f"EXISTS {target} missing")
            elif crit.startswith("CONTAINS:"):
                rest = crit[len("CONTAINS:"):]
                if ":" in rest:
                    path_part, substr = rest.split(":", 1)
                else:
                    path_part, substr = rest, ""
                path_part = path_part.strip().lower()
                substr = substr.strip()
                if path_part not in content_by_path:
                    failures.append(f"CONTAINS path {path_part} missing")
                elif substr.lower() not in (content_by_path[path_part] or "").lower():
                    failures.append(f"CONTAINS {substr!r} not in {path_part}")
            else:
                logger.debug(f"[WebStructuralVerifier] ignoring unknown criterion: {crit}")
                continue

        if failures:
            return False, "ACCEPTANCE_FAILURE: " + "; ".join(failures)
        return True, "All acceptance criteria passed."
