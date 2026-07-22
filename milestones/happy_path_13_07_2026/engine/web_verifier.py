import logging
from typing import Tuple, List, Dict, Any
from sqlalchemy.orm import Session
from engine.services.verification_registry import BaseVerifier

logger = logging.getLogger(__name__)

class WebStructuralVerifier(BaseVerifier):
    """
    Verifies web-based products by checking for critical structural elements.
    """
    async def verify(self, session: Session, task_id: str, project_id: str, plan_version: int, artifacts: List[Dict[str, Any]]) -> Tuple[bool, str]:
        if not artifacts:
            return False, "MISSING_CONTENT: No artifacts provided for verification."
        
        html_files = [a for a in artifacts if a['path'].endswith('.html')]
        js_files = [a for a in artifacts if a['path'].endswith('.js')]
        
        # Per-file structural checks (lenient: only verify what the task produced)
        # 1. If HTML is provided, it MUST contain a <canvas> element
        if html_files:
            html_content = "\n".join((h.get('content', '') or '') for h in html_files).lower()
            if '<canvas' not in html_content:
                return False, "MISSING_CANVAS: No <canvas> element found in provided HTML."
        
        # 2. If JS is provided, it MUST contain a game loop and input handling
        if js_files:
            js_content = "\n".join((j.get('content', '') or '') for j in js_files).lower()
            if not ('requestanimationframe' in js_content or 'setinterval' in js_content or 'settimeout' in js_content):
                return False, "MISSING_GAME_LOOP: No timing mechanism (requestAnimationFrame/setInterval/setTimeout) found in provided JS."
            if not ('addeventlistener' in js_content or 'onkeydown' in js_content):
                return False, "MISSING_INPUT: No keyboard input handling found in provided JS."
        
        # 3. If a task produced neither HTML nor JS (e.g. CSS-only), we accept it.
        #    The game-loop/canvas checks above cover the logic-bearing files.
        if not html_files and not js_files:
            return True, "No HTML/JS produced (e.g. CSS-only task); structural checks skipped."
        
        return True, "All structural web acceptance criteria passed."
