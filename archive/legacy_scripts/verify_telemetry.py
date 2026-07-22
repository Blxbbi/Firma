import sys
import asyncio
from engine.services.telemetry import telemetry as t1

# Attempt to import using a potentially different path if it exists
try:
    # This is a common source of double-imports in Python
    from services.telemetry import telemetry as t2
except ImportError:
    # If it doesn't exist, we just import it again from the same place
    from engine.services.telemetry import telemetry as t2

def check_singleton():
    print("=== Singleton Validation ===")
    print(f"T1 ID: {id(t1)}")
    print(f"T2 ID: {id(t2)}")
    print(f"T1 Module: {t1.__class__.__module__}")
    print(f"T2 Module: {t2.__class__.__module__}")
    print(f"Same Object: {t1 is t2}")
    
    print("\n=== sys.modules check ===")
    telemetry_mods = [k for k in sys.modules.keys() if "telemetry" in k]
    print(f"Telemetry related modules: {telemetry_mods}")

def test_flow():
    print("\n=== Flow Validation ===")
    t1.reset()
    print("Reset called.")
    
    print("Incrementing 'test_counter'...")
    t1.increment("test_counter", 10)
    
    print("Snapshotting from t2...")
    snap = t2.snapshot()
    print(f"Snapshot counters: {snap.get('counters')}")
    
    if snap.get('counters', {}).get('test_counter') == 10:
        print("✅ Flow SUCCESS: Increment on T1 visible in T2 snapshot.")
    else:
        print("❌ Flow FAILURE: Increment not visible in snapshot.")

if __name__ == "__main__":
    check_singleton()
    test_flow()
