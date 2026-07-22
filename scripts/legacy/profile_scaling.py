import asyncio
import logging
import time
import uuid
import psutil
import os
from typing import List, Dict, Any
from engine.db import DatabaseManager
from engine.models import Base, ExecutionPhase
from engine.services.flight_manager import FlightManager, FlightSpec
from engine.services.flight_worker import FlightWorker
from engine.providers.pi_provider import PiProvider
from engine.services.observability import ObservabilityService
from engine.services.telemetry import TelemetryManager

# --- Setup Logging ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger("SCALING-PROFILER")

class FlightGenerator:
    """Generates Class B Flights based on SRE specifications."""
    
    @staticmethod
    def generate_linear_dependency(flight_id: str) -> FlightSpec:
        """Type 1: Multi-File Linear Dependency (Imports chain)"""
        return FlightSpec(
            flight_id=flight_id,
            flight_class="B1",
            goal="Implement a tiered architecture: CLI -> Controller -> Service -> Model.",
            constraints=[
                "File 'cli.py' must import 'controller.py'",
                "File 'controller.py' must import 'service.py'",
                "File 'service.py' must import 'models.py'",
                "All files must be syntactically correct python"
            ],
            expected_artifacts=[
                {"path": "cli.py", "type": "CREATE"},
                {"path": "controller.py", "type": "CREATE"},
                {"path": "service.py", "type": "CREATE"},
                {"path": "models.py", "type": "CREATE"},
                {"path": "tests.py", "type": "CREATE"},
            ],
            acceptance_criteria=["All imports resolve", "tests.py executes without ImportError"],
            model_name="gpt-4o"
        )

    @staticmethod
    def generate_transition_heavy(flight_id: str) -> FlightSpec:
        """Type 2: State Transition Heavy (Forcing iterations)"""
        return FlightSpec(
            flight_id=flight_id,
            flight_class="B2",
            goal="Implement a complex validation engine with multiple edge cases.",
            constraints=[
                "Must handle nested JSON validation",
                "Must implement custom error types",
                "Must be refactored at least once to improve complexity"
            ],
            expected_artifacts=[
                {"path": "validator.py", "type": "CREATE"},
                {"path": "exceptions.py", "type": "CREATE"},
                {"path": "schema.json", "type": "CREATE"},
            ],
            acceptance_criteria=["Passes all nested validation tests"],
            model_name="gpt-4o"
        )

    @staticmethod
    def generate_artifact_density(flight_id: str) -> FlightSpec:
        """Type 3: Artifact Density (High IO)"""
        artifacts = [{"path": f"module_{i}.py", "type": "CREATE"} for i in range(20)]
        return FlightSpec(
            flight_id=flight_id,
            flight_class="B3",
            goal="Create a large modular library with 20 interconnected modules.",
            constraints=["Each module must have a unique purpose", "Modules must reference each other"],
            expected_artifacts=artifacts,
            acceptance_criteria=["All 20 files persist correctly"],
            model_name="gpt-4o"
        )

def get_system_usage():
    """Returns current CPU and Memory usage."""
    process = psutil.Process(os.getpid())
    return {
        "cpu_percent": psutil.cpu_percent(),
        "mem_rss_mb": process.memory_info().rss / (1024 * 1024)
    }

async def run_scaling_level(level: int, db_manager: DatabaseManager, manager: FlightManager, worker: FlightWorker):
    """Runs a specific concurrency level and returns the report."""
    # Unique run ID for this level to ensure hermetic isolation
    run_id = f"RUN-L{level}-{str(uuid.uuid4())[:8]}"
    logger.info(f"\n{'='*60}\n🚀 STARTING CONCURRENCY LEVEL: {level} | RUN_ID: {run_id}\n{'='*60}")
    
    specs = []
    for i in range(level):
        fid = f"B-L{level}-T{i}"
        if i % 3 == 0:
            specs.append(FlightGenerator.generate_linear_dependency(fid))
        elif i % 3 == 1:
            specs.append(FlightGenerator.generate_transition_heavy(fid))
        else:
            specs.append(FlightGenerator.generate_artifact_density(fid))
            
    # 1. Warmup Phase (SRE-Isolated run_id)
    warmup_run_id = f"WARMUP-{run_id}"
    logger.info(f"🔥 Warmup Phase: Priming caches (run_id: {warmup_run_id})...")
    await manager.run_batch(specs[:2], worker, run_id=warmup_run_id)
    await asyncio.sleep(2) # Settle
    
    # 2. Measurement Phase
    logger.info(f"⏱️ Measurement Phase: Launching {level} parallel flights (run_id: {run_id})...")
    results = await manager.run_batch(specs, worker, run_id=run_id)
    
    # 3. Post-Run Settle
    await asyncio.sleep(5)
    
    # 4. Snapshot
    async with db_manager.AsyncSessionLocal() as session:
        obs = ObservabilityService(session)
        report = await obs.generate_scaling_report(level, run_id=run_id)
        usage = get_system_usage()
        
        print(f"\n=== CONCURRENCY LEVEL: {level} ===")
        print(f"Run ID: {run_id}")
        print(f"Stability: {report['stability']*100:.2f}%")
        print(f"Avg Duration: {report['avg_duration']:.2f}ms")
        print(f"P95 Duration: {report['p95_duration']:.2f}ms")
        print(f"CAS Reject Rate: {report['cas_reject_rate']*100:.2f}%")
        print(f"Loop Lag P95: {report['loop_lag_p95']*1000:.2f}ms")
        print(f"DB Write P95: {report['db_write_p95']:.2f}ms")
        print(f"CPU Usage: {usage['cpu_percent']}%")
        print(f"Memory RSS: {usage['mem_rss_mb']:.2f} MB")
        print(f"KIPPPUNKT: {report['kipppunkt']}")
        print("="*30)
        
    return report

async def main():
    # Infrastructure Setup
    db_manager = DatabaseManager(db_url="sqlite+aiosqlite:///scaling_test.db")
    await db_manager.initialize_db()
    await db_manager.create_tables(Base)
    
    # Telemetry Setup
    telemetry = TelemetryManager(db_manager=db_manager)
    await telemetry.start_loop_monitor()
    
    # Baseline Measurement
    logger.info("📉 Measuring Loop Lag Baseline (0 Concurrency)...")
    await asyncio.sleep(2)
    baseline_lag = telemetry.get_metric_snapshot("loop_lag")
    if baseline_lag:
        p95_baseline = np.percentile(baseline_lag, 95)
        logger.info(f"✅ Loop Lag Baseline P95: {p95_baseline*1000:.2f}ms")
    else:
        logger.warning("Could not capture baseline lag")

    # Manager Setup
    manager = FlightManager(db_manager=db_manager, artifact_root="artifact_store/scaling")
    provider = PiProvider(simulate_delay=True) # CRITICAL: Simulate real-world latency
    worker = FlightWorker(provider)
    
    try:
        # Scaling Kaskade: 10 -> 20 -> 50
        for level in [10, 20, 50]:
            await run_scaling_level(level, db_manager, manager, worker)
            logger.info(f"💤 Cooling down for 10s after level {level}...")
            await asyncio.sleep(10)
            
    finally:
        await telemetry.stop()
        logger.info("Scaling profiling complete.")

if __name__ == "__main__":
    import numpy as np # Ensure numpy is available for baseline calc
    asyncio.run(main())
