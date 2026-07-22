import asyncio
import logging
from engine.models import Base
from engine.services.flight_manager import FlightManager, FlightSpec
from engine.services.flight_worker import FlightWorker
from engine.providers.pi_provider import PiProvider
from engine.services.observability import ObservabilityService
from engine.db import DatabaseManager

# --- Setup Logging ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger("FLIGHT-PROGRAM")

async def main():
    # 1. Initialize Infrastructure
    db_manager = DatabaseManager(db_url="sqlite+aiosqlite:///flight_program.db")
    await db_manager.initialize_db()
    await db_manager.create_tables(Base)
    
    manager = FlightManager(db_manager=db_manager, artifact_root="artifact_store/flights")
    provider = PiProvider()
    worker = FlightWorker(provider)
    
    # 2. Define Flight Class A (Deterministic Coding Tasks)
    class_a_specs = [
        FlightSpec(
            flight_class="A",
            goal="Create a CLI tool that calculates the nth Fibonacci number.",
            constraints=["Must be a single python file", "Must use argparse"],
            expected_artifacts=[{"path": "fib.py", "type": "CREATE"}],
            acceptance_criteria=["Returns correct fib(10)=55"],
            model_name="gpt-4o"
        ),
        FlightSpec(
            flight_class="A",
            goal="Create a script that calculates the sum of all primes up to N.",
            constraints=["Must be optimized for N=100,000"],
            expected_artifacts=[{"path": "primes.py", "type": "CREATE"}],
            acceptance_criteria=["Correctly calculates sum for N=100"],
            model_name="gpt-4o"
        ),
        FlightSpec(
            flight_class="A",
            goal="Implement a simple FastAPI health check endpoint.",
            constraints=["One GET endpoint /health", "Returns {'status': 'ok'}"],
            expected_artifacts=[{"path": "main.py", "type": "CREATE"}],
            acceptance_criteria=["Endpoint returns 200 OK"],
            model_name="gpt-4o"
        ),
        FlightSpec(
            flight_class="A",
            goal="Create a CSV parser that reads a file 'data.csv' and prints the sum of the second column.",
            constraints=["Handle missing values as 0"],
            expected_artifacts=[{"path": "parser.py", "type": "CREATE"}],
            acceptance_criteria=["Correct sum for provided test CSV"],
            model_name="gpt-4o"
        ),
        FlightSpec(
            flight_class="A",
            goal="Implement a basic API key authentication middleware for a Python app.",
            constraints=["Check 'X-API-KEY' header", "Return 403 if missing or invalid"],
            expected_artifacts=[{"path": "auth.py", "type": "CREATE"}],
            acceptance_criteria=["Blocks requests without valid key"],
            model_name="gpt-4o"
        ),
    ]
    
    # --- SMOKE TEST ---
    logger.info("🔍 Running Internal API Smoke Test...")
    try:
        test_resp = await provider.generate("Return a simple greeting", "Hello!", timeout=10)
        logger.info(f"✅ Smoke Test Passed: {test_resp}")
    except Exception as e:
        logger.error(f"❌ Smoke Test Failed: {str(e)}")
        return

    # 3. Run Flights
    logger.info("🚀 Starting Flight Program: Class A (Baseline)")
    results = await manager.run_batch(class_a_specs, worker)
    
    # 4. KPI Extraction (Use async session)
    async with db_manager.AsyncSessionLocal() as session:
        obs = ObservabilityService(session)
        
        # Need to handle that the existing ObservabilityService is sync
        # Since we just migrated everything, we should probably make ObservabilityService async too
        # But for a quick check, let's see if it works or if we need to refactor it.
        # Actually, it uses session.query() which is sync.
        # I'll make a quick async version of the KPIs or refactor the service.
        
        # For now, since we are in main(), I can just manually do the async queries.
        from sqlalchemy import func, select
        from engine.models import SubmissionLog, SubmissionOutcome

        # Schema Compliance
        total_res = await session.execute(select(func.count()).select_from(SubmissionLog))
        total = total_res.scalar() or 0
        
        err_res = await session.execute(
            select(func.count()).select_from(SubmissionLog).filter(SubmissionLog.outcome == SubmissionOutcome.SCHEMA_ERROR.value)
        )
        errors = err_res.scalar() or 0
        compliance = 1.0 - (errors / total) if total > 0 else 1.0

        # Convergence
        conv_res = await session.execute(
            select(func.avg(SubmissionLog.iteration_number)).filter(SubmissionLog.outcome == SubmissionOutcome.SUCCESS.value)
        )
        convergence = conv_res.scalar() or 0.0

        # Failure Distribution
        fail_res = await session.execute(
            select(SubmissionLog.error_code, func.count(SubmissionLog.id))
            .filter(SubmissionLog.error_code != None)
            .group_by(SubmissionLog.error_code)
        )
        failures = {code: count for code, count in fail_res.all()}
        
        logger.info("\n" + "="*50)
        logger.info("📊 FLIGHT PROGRAM: CLASS A KPI SNAPSHOT")
        logger.info("="*50)
        logger.info(f"Total Flights:     {len(class_a_specs)}")
        logger.info(f"Success Rate:      {(sum(1 for r in results if r.success)/len(results))*100:.2f}%")
        logger.info(f"Schema Compliance: {compliance*100:.2f}%")
        logger.info(f"Avg Convergence:   {convergence:.2f} iterations")
        logger.info(f"Failure Dist:      {failures}")
        logger.info("="*50)
    
if __name__ == "__main__":
    asyncio.run(main())
