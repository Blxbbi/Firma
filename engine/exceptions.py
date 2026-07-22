import logging

logger = logging.getLogger(__name__)

class FirmaEngineError(Exception):
    """Base exception for all Firma Engine errors."""
    def __init__(self, message: str, error_code: str = "INTERNAL_ERROR"):
        self.message = message
        self.error_code = error_code
        super().__init__(self.message)

class WorkerExecutionError(FirmaEngineError):
    """
    Raised when a worker fails to execute its task (e.g., LLM Timeout, API Error, Crash).
    This is a recoverable error that typically leads to a retry.
    """
    def __init__(self, message: str, error_code: str = "WORKER_EXECUTION_FAILED"):
        super().__init__(message, error_code)

class ValidationFailure(FirmaEngineError):
    """
    Raised when a worker's output fails structural or semantic validation.
    This is a 'logical' failure that requires the worker to correct the output.
    """
    def __init__(self, message: str, error_code: str = "VALIDATION_FAILED"):
        super().__init__(message, error_code)

class EngineConfigurationError(FirmaEngineError):
    """
    Raised when the engine is misconfigured (e.g., missing API keys, invalid governance matrix).
    This is typically a fatal error that requires human intervention.
    """
    def __init__(self, message: str, error_code: str = "CONFIG_ERROR"):
        super().__init__(message, error_code)
