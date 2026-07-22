import logging
from abc import ABC, abstractmethod
from typing import Tuple, List, Dict, Any, Type
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

class BaseVerifier(ABC):
    """
    Base class for all deterministic verifiers.
    """
    @abstractmethod
    async def verify(self, session: Session, task_id: str, project_id: str, plan_version: int, artifacts: List[Dict[str, Any]]) -> Tuple[bool, str]:
        """
        Performs verification and returns (success, logs/report).
        """
        pass

class VerificationRegistry:
    """
    Registry for mapping verification keys (from config) to Verifier implementations.
    """
    _verifiers: Dict[str, Type[BaseVerifier]] = {}

    @classmethod
    def register(cls, name: str, verifier_cls: Type[BaseVerifier]):
        logger.info(f"[VerificationRegistry] Registering verifier: {name}")
        cls._verifiers[name] = verifier_cls

    @classmethod
    def get(cls, name: str) -> BaseVerifier:
        if name not in cls._verifiers:
            raise RuntimeError(f"Plattform-Bootstrap unvollständig: Verifizierer '{name}' wurde nicht registriert. Prüfen Sie die Initialisierungssequenz in platform_main oder run_snake.")
        return cls._verifiers[name]()
