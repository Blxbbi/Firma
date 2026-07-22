import asyncio
import argparse
from benchmarks.benchmark_harness import BenchmarkHarness

async def run_sanity_check():
    class Args:
        profile = "io"
        ramp = "2"  # Small ramp for sanity check
        duration = 10
        warmup = 1
        label = "sanity_check_v1"
        seed = 42

    args = Args()
    print(f"Running Telemetry Sanity Check: L2 | Duration: {args.duration}s")
    
    harness = BenchmarkHarness(args)
    await harness.run()
    print("\nSanity Run Finished. Checking snapshots...")

if __name__ == "__main__":
    asyncio.run(run_sanity_check())
