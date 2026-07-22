
import asyncio
import argparse
from benchmarks.benchmark_harness import BenchmarkHarness
from engine.services.concurrency import concurrency_controller

async def run_smoke_test():
    class Args:
        profile = "io"
        ramp = "5,15,30"  # Phase 1: Baseline, Phase 2: Expansion, Phase 3: Stress
        duration = 600     # 10 minutes per phase for realistic variance
        warmup = 10
        label = "llm_smoke_test_v1"
        seed = 42

    args = Args()
    
    # Initial Governor State
    concurrency_controller.min_limit = 5
    concurrency_controller.current_limit = 5
    concurrency_controller.max_limit = 60 # Give it room to expand
    
    print("="*60)
    print("STARTING REAL-WORLD LLM SMOKE TEST")
    print("="*60)
    print(f"Profile: {args.profile}")
    print(f"Phases: {args.ramp} (Duration: {args.duration}s each)")
    print(f"Initial Limit: {concurrency_controller.current_limit}")
    print(f"Max Limit: {concurrency_controller.max_limit}")
    print("="*60)
    
    harness = BenchmarkHarness(args)
    # The harness will run: 
    # 1. Baseline (L1) 
    # 2. L5 -> L15 -> L30 (controlled expansion)
    await harness.run()

if __name__ == "__main__":
    asyncio.run(run_smoke_test())
