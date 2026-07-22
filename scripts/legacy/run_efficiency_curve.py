import asyncio
import argparse
import sys
from benchmarks.benchmark_harness import BenchmarkHarness

async def run_efficiency_test():
    # Mocking the argparse Namespace
    class Args:
        profile = "io"
        ramp = "10,20,40,60"
        duration = 60
        warmup = 10
        label = "efficiency_curve_v1"
        seed = 42

    args = Args()
    print(f"Starting Efficiency Curve Analysis: {args.profile} | {args.ramp} | Duration: {args.duration}s")
    
    harness = BenchmarkHarness(args)
    await harness.run()

if __name__ == "__main__":
    asyncio.run(run_efficiency_test())
