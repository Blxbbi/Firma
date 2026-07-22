
import asyncio
import argparse
from benchmarks.benchmark_harness import BenchmarkHarness
from engine.services.concurrency import concurrency_controller

async def run_validation():
    class Args:
        profile = "io"
        ramp = "60" # Set to 60 to ensure a large enough Task Pool
        duration = 600 # 10 minutes for multiple AIMD cycles
        warmup = 5
        label = "governor_protective_ceiling_test"
        seed = 42

    args = Args()
    
    # LIFT THE CEILING: Allow governor to expand beyond hardware capacity to test safety reflex
    concurrency_controller.max_limit = 60
    
    print(f"Starting Protective-Ceiling Validation Run: {args.profile} | Duration: {args.duration}s | Pool-Ramp: {args.ramp}")
    print(f"SAFETY CONFIG: max_limit={concurrency_controller.max_limit}, min_limit={concurrency_controller.min_limit}")
    
    harness = BenchmarkHarness(args)
    # The harness will run: 
    # 1. Baseline (L1) 
    # 2. L60 (where the Governor will actually control concurrency starting from min_limit)
    await harness.run()

if __name__ == "__main__":
    asyncio.run(run_validation())
