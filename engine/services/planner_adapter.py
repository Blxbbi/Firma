from .plan_instantiator import PlanInstantiationService
from ..models import Message, MessageType, PlanDraftSchema, GuardResult
from ..repository import MessageRepository
import logging

logger = logging.getLogger(__name__)

class PlannerAdapter:
    """
    Bridges the gap between incoming PLAN_DRAFT_SUBMITTED messages 
    and the PlanInstantiationService.
    """

    def __init__(self, db_session):
        self.db_session = db_session
        self.instantiator = PlanInstantiationService(db_session)
        self.repo = MessageRepository(db_session)

    def handle_plan_submission(self, message: Message) -> GuardResult:
        """
        Extracts the draft from the message and triggers instantiation.
        """
        logger.info(f"Adapter handling plan submission for message {message.header.message_id}")
        
        # The validation is already done by the Guards in the workflow,
        # so we can safely assume the payload matches PlanDraftSchema.
        try:
            draft = PlanDraftSchema.model_validate(message.payload)
            self.instantiator.instantiate_plan(draft)
            return GuardResult(passed=True)
        except Exception as e:
            logger.error(f"Adapter failed to process plan: {str(e)}")
            return GuardResult(passed=False, error_code="ERR_ADAPTER_FAILURE", reason=str(e))
