import psutil
import time
import json
import asyncio
from pathlib import Path
from typing import Dict, Any
from benchmarks.config import config

class SystemProbe:
    """
    High-resolution system resource probe.
    """
    def __init__(self, output_file: Path):
        self.output_file = output_file
        self.process = psutil.Process()

    async def sample(self):
        """Captures a single snapshot of system resources."""
        try:
            cpu_percent = psutil.cpu_percent(interval=None)
            mem_info = self.process.memory_info()
            rss_mb = mem_info.rss / (1024 * 1024)
            fds = self.process.num_fds() if hasattr(self.process, 'num_fds') else 0
            
            sample = {
                "timestamp": time.time(),
                "cpu_percent": cpu_percent,
                "rss_mb": rss_mb,
                "fds": fds,
                "ctx_switches": self.process.num_ctx_switches().voluntary if hasattr(self.process, 'num_ctx_switches') else 0
            }
            
            with open(self.output_file, "a") as f:
                f.write(json.dumps(sample) + "\n")
                
            return sample
        except Exception as e:
            print(f"Probe error: {e}")
            return {}

    async def run_loop(self, stop_event: asyncio.Event):
        """Continuously samples resources every second."""
        while not stop_event.is_set():
            await self.sample()
            await asyncio.sleep(1)
