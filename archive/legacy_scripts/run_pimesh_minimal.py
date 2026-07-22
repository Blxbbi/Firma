"""
run_pimesh_minimal.py — Phase-4 Proof: Firma dispatches -> PiProvider spawns pi worker
im Crew-Dir -> Worker schreibt Datei + worker_response -> PiMeshReceiverLoop konsumiert.

Beweis der vollstaendigen PiMesh-Pipeline (ohne schweres Snake-Szenario):
  PiMeshTransport.dispatch()  -> task-N.json + .md im Crew-Dir
  PiProvider.spawn_worker()   -> pi.cmd --mode json im Crew-Dir (cwd=crew-cwd)
  Worker schreibt hello.txt + worker_response.task-1.response.json
  (Runner markiert task done zur Simulation von task.done)
  PiMeshReceiverLoop.scan_once() -> inlined + validiert + publish
"""
import asyncio
import json
import logging
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from engine.settings import PIMESH_CREWS, BASE_DIR
from engine.transport.pi_mesh_transport import PiMeshTransport, WORKER_RESPONSE_SUFFIX
from run_pi_mesh import PiMeshReceiverLoop
from engine.providers.pi_provider import PiProvider

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("run_pimesh_minimal")

CREW = "pimesh/coding-crew"  # CODER crew
TASK_ID = "task-1"


def _mark_done(task_path):
    try:
        t = json.load(open(task_path))
        t["status"] = "done"
        json.dump(t, open(task_path, "w"), indent=2)
    except Exception as e:
        logger.warning("cannot mark done: %s", e)


def main():
    crew_cwd = os.path.join(str(BASE_DIR), CREW)
    transport = PiMeshTransport(crew_cwds=PIMESH_CREWS, project_root=str(BASE_DIR))

    # 1) Dispatch (materialisiert Assignment als task-N.json + .md)
    asyncio.run(transport.dispatch({
        "event": "TASK_ASSIGNMENT",
        "run_id": "run-min",
        "task_id": TASK_ID,
        "role": "CODER",
        "state_revision": 1,
        "prompt": "write hello.txt",
        "task_definition": {"description": "write hello.txt", "acceptance_criteria": ["file exists"]},
    }))
    logger.info("✅ Dispatched %s to %s", TASK_ID, crew_cwd)

    # 2) Spawn pi worker (cwd = crew_cwd). Lieat task-N.md und folgt dem Vertrag.
    provider = PiProvider(extension_dir=None)
    prompt = (
        f"Read the file `.pi/messenger/crew/tasks/{TASK_ID}.md` in the current directory and "
        f"follow its instructions EXACTLY: implement the task by writing the required files, "
        f"then write the worker_response file named in the spec, then stop. Do not ask questions."
    )
    proc = provider.spawn_worker(crew_cwd, prompt)

    # 3) Warten bis worker_response.<task_id>.response.json existiert
    resp_path = os.path.join(crew_cwd, f"worker_response.{TASK_ID}{WORKER_RESPONSE_SUFFIX}")
    task_path = os.path.join(crew_cwd, ".pi", "messenger", "crew", "tasks", f"{TASK_ID}.json")
    deadline = time.time() + 150
    found = False
    while time.time() < deadline:
        if os.path.isfile(resp_path):
            found = True
            break
        time.sleep(3)
    logger.info("worker_response exists: %s (exit code so far: %s)", found, proc.poll())

    # 4) task.done simulieren (Worker haette es via pi_messenger gerufen)
    if found:
        _mark_done(task_path)

    # 5) Receiver scan (inlined + validiert + publish)
    recv = PiMeshReceiverLoop(transport=transport, crew_cwds=PIMESH_CREWS, project_root=str(BASE_DIR))
    items = recv.scan_once()
    logger.info("published items: %d", len(items))
    if items:
        p = items[0]["payload"]
        logger.info("event=%s sender_role=%s artifacts=%s", p.get("event"), p.get("sender_role"), p.get("artifacts"))
        for a in (p.get("artifacts") or []):
            if a.get("path") == "hello.txt":
                logger.info("hello.txt inlined content: %r", (a.get("content") or "")[:60])
    else:
        logger.warning("Receiver published nothing. task status: %s, resp exists: %s",
                       _task_status(task_path), found)

    # aufraeumen: worker-prozess beenden falls noch aktiv
    if proc.poll() is None:
        try:
            proc.terminate()
        except Exception:
            pass


def _task_status(path):
    try:
        return json.load(open(path)).get("status")
    except Exception:
        return "?"


if __name__ == "__main__":
    main()
