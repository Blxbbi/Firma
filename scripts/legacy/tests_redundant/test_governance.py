import logging
from engine.models import ExecutionPhase, AssignedRole, TaskEvent
from engine.governance import GovernanceMatrix, IllegalTransitionError

logging.basicConfig(level=logging.INFO)

def test_governance_fsm():
    print("--- Testing Governance FSM ---")
    
    # Scenario 1: Standard Success Path
    # CODING -> CODE_SUBMITTED -> VERIFYING -> VERIFY_SUCCESS -> REVIEWING
    try:
        phase = ExecutionPhase.CODING
        print(f"Start: {phase}")
        
        # Event: Code submitted
        res = GovernanceMatrix.transition(phase, TaskEvent.CODE_SUBMITTED)
        print(f"Event CODE_SUBMITTED -> Next Phase: {res.next_phase}, Next Role: {res.next_role}")
        assert res.next_phase == ExecutionPhase.VERIFYING
        assert res.next_role == AssignedRole.SYSTEM
        
        phase = res.next_phase
        
        # Event: Verification success
        res = GovernanceMatrix.transition(phase, TaskEvent.VERIFY_SUCCESS)
        print(f"Event VERIFY_SUCCESS -> Next Phase: {res.next_phase}, Next Role: {res.next_role}")
        assert res.next_phase == ExecutionPhase.REVIEWING
        assert res.next_role == AssignedRole.REVIEWER
        
        print("Standard Success Path verified")
    except Exception as e:
        print(f"Success Path failed: {e}")
        return

    # Scenario 2: Verification Failure Path
    # VERIFYING -> VERIFY_FAILURE -> CODING
    try:
        phase = ExecutionPhase.VERIFYING
        print(f"\nStart: {phase}")
        
        res = GovernanceMatrix.transition(phase, TaskEvent.VERIFY_FAILURE)
        print(f"Event VERIFY_FAILURE -> Next Phase: {res.next_phase}, Next Role: {res.next_role}")
        assert res.next_phase == ExecutionPhase.CODING
        assert res.next_role == AssignedRole.CODER
        
        print("Verification Failure Path verified")
    except Exception as e:
        print(f"Failure Path failed: {e}")
        return

    # Scenario 3: Illegal Transition
    # CODING -> VERIFY_SUCCESS (Impossible, must submit first)
    try:
        phase = ExecutionPhase.CODING
        print(f"\nStart: {phase}")
        GovernanceMatrix.transition(phase, TaskEvent.VERIFY_SUCCESS)
        print("Illegal transition was NOT caught!")
    except IllegalTransitionError:
        print("Illegal transition correctly caught")

    print("\nGovernance FSM tests passed!")

if __name__ == "__main__":
    test_governance_fsm()
