import asyncio
import json
from engine.providers.nvidia_provider import NvidiaProvider
from workers.planner import PlannerWorker

async def test_planner_direct():
    api_key = "REDACTED_NVIDIA_KEY"
    model = "meta/llama-3.1-70b-instruct"
    provider = NvidiaProvider(api_key=api_key, model=model)
    planner = PlannerWorker(provider, model)
    
    prompt = "Schreibe ein Python CLI-Tool `main.py`, das eine CSV-Datei mit zwei Spalten `name,value` einliest und für jeden Namen die Summe der Werte ausgibt. Das Tool soll robust gegen leere Zeilen, ungültige Zahlen und fehlende Spalten sein."
    
    print("--- Sending Request to Planner (Direct NVIDIA) ---")
    try:
        msg = await planner.handle_request(project_id="test-project", user_prompt=prompt)
        print("\n--- RAW MESSAGE ---")
        print(f"Header: {msg.header}")
        print(f"Payload: {json.dumps(msg.payload, indent=2)}")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(test_planner_direct())
