import os
import signal
import psutil

def kill_python_processes():
    current_pid = os.getpid()
    for proc in psutil.process_iter(['pid', 'name']):
        if 'python' in proc.info['name'].lower() and proc.info['pid'] != current_pid:
            try:
                print(f"Killing {proc.info['pid']}...")
                os.kill(proc.info['pid'], signal.SIGTERM)
            except Exception as e:
                print(f"Could not kill {proc.info['pid']}: {e}")

if __name__ == "__main__":
    kill_python_processes()
