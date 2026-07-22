
import asyncio
import time
import os
import tempfile
from pathlib import Path
from engine.services.sandbox import LocalPythonSandbox, ExecutionResult

async def profile_sandbox():
    sandbox = LocalPythonSandbox()
    files = [{"path": "test.py", "content": "print('hello')\nimport time\ntime.sleep(0.05)"}]
    command = "python test.py"
    
    # Wir messen 10 Runs, um den Durchschnitt zu bekommen
    startups = []
    execs = []
    fs_setups = []
    
    for i in range(10):
        # 1. FS Setup
        t0 = time.perf_counter_ns()
        with tempfile.TemporaryDirectory() as tmp_dir:
            for f in files:
                with open(os.path.join(tmp_dir, f["path"]), "w") as file:
                    file.write(f["content"])
            t1 = time.perf_counter_ns()
            fs_setups.append(t1 - t0)
            
            # 2. Spawn
            t2 = time.perf_counter_ns()
            process = await asyncio.create_subprocess_exec(
                "python", *command.split(),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=tmp_dir
            )
            t3 = time.perf_counter_ns()
            startups.append(t3 - t2)
            
            # 3. Execution
            await process.communicate()
            t4 = time.perf_counter_ns()
            execs.append(t4 - t3)

    print(f"--- Sandbox Anatomy (Average of 10 runs) ---")
    print(f"FS Setup:        {(sum(fs_setups)/10)/1e6:>10.2f} ms")
    print(f"OS Spawn:        {(sum(startups)/10)/1e6:>10.2f} ms")
    print(f"Code Execution:  {(sum(execs)/10)/1e6:>10.2f} ms")
    print(f"Total Window:    {(sum(fs_setups+startups+execs)/10)/1e6:>10.2f} ms")

if __name__ == "__main__":
    asyncio.run(profile_sandbox())
