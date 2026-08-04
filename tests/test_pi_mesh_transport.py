"""
Unit-Tests fuer PiMeshTransport + PiMeshReceiverLoop (file-based, kein pi-Tool).

Testet:
 - dispatch() schreibt valides pi-messenger Task-File (task-N.json + .md)
 - Receiver liest worker_response.<id>.response.json aus .pi/messenger/crew/, inline content
 - Dedupe: zweiter Scan publiziert nicht erneut
 - Pfad-Traversal wird nicht gelesen (Security Boundary) -> SUBMISSION_INVALID_SCHEMA
"""
import asyncio
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine.transport.pi_mesh_transport import PiMeshTransport, WORKER_RESPONSE_SUFFIX
from run_pi_mesh import PiMeshReceiverLoop, WORKER_RESPONSE_SUFFIX


CREWS = {
    "PLANNER": "pimesh/planning-crew",
    "CODER": "pimesh/coding-crew",
    "REVIEWER": "pimesh/reviewing-crew",
    "RESEARCHER": "pimesh/planning-crew",
}


def _write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def _worker_dir(crew_cwd):
    return os.path.join(crew_cwd, ".pi", "messenger", "crew")


def _dispatch(root, task_id, role="CODER"):
    t = PiMeshTransport(crew_cwds=CREWS, project_root=root)
    payload = {
        "event": "TASK_ASSIGNMENT",
        "run_id": "run-X",
        "task_id": task_id,
        "role": role,
        "state_revision": 5,
        "prompt": "make game",
        "task_definition": {"description": "d", "acceptance_criteria": ["a"]},
    }
    asyncio.run(t.dispatch(payload))
    tasks_dir = os.path.join(root, CREWS[role], ".pi", "messenger", "crew", "tasks")
    crew_cwd = os.path.join(root, CREWS[role])
    return t, tasks_dir, crew_cwd


def test_dispatch_writes_task_files():
    root = tempfile.mkdtemp()
    _, tasks_dir, _ = _dispatch(root, "task-1")
    jp = os.path.join(tasks_dir, "task-1.json")
    mp = os.path.join(tasks_dir, "task-1.md")
    assert os.path.isfile(jp), "task-1.json missing"
    assert os.path.isfile(mp), "task-1.md missing"
    task = json.load(open(jp))
    assert task["id"] == "task-1"
    assert task["status"] == "todo", f"status should be todo, got {task['status']}"
    assert task["depends_on"] == []
    assert task["firma_assignment"]["run_id"] == "run-X"
    print("PASS: dispatch writes valid task files")
    return root


def test_receiver_inlines_and_dedupes():
    root = tempfile.mkdtemp()
    _, tasks_dir, crew_cwd = _dispatch(root, "task-1")
    wd = _worker_dir(crew_cwd)
    _write(os.path.join(wd, "game.js"), "const canvas=1;")
    resp = {
        "protocol_version": "1.0",
        "message_id": "msg-1",
        "task_id": "task-1",
        "run_id": "run-X",
        "state_revision": 5,
        "event": "CODE_SUBMITTED",
        "sender_role": "CODER",
        "artifacts": [{"path": "game.js", "action": "CREATE", "content": None}],
        "timestamp": "2026-07-13T00:00:00Z",
        "logs": "ok",
    }
    _write(os.path.join(wd, f"worker_response.task-1{WORKER_RESPONSE_SUFFIX}"), json.dumps(resp))

    t = PiMeshTransport(crew_cwds=CREWS, project_root=root)
    recv = PiMeshReceiverLoop(transport=t, crew_cwds=CREWS, project_root=root)
    items1 = recv.scan_once()
    assert len(items1) == 1, f"expected 1 published, got {len(items1)}"
    art = items1[0]["payload"]["artifacts"][0]
    assert art["content"] == "const canvas=1;", f"content not inlined: {art['content']}"
    print("PASS: receiver inlines content from .pi/messenger/crew/")

    items2 = recv.scan_once()
    assert len(items2) == 0, f"dedupe failed: second scan published {len(items2)}"
    print("PASS: receiver dedupes (consumed once)")


def test_contract_filename_in_markdown():
    expectations = {
        "PLANNER": "PLAN_SUBMITTED",
        "CODER": "CODE_SUBMITTED",
        "REVIEWER": "REVIEW_APPROVED",
    }
    for role, ev in expectations.items():
        root = tempfile.mkdtemp()
        t = PiMeshTransport(crew_cwds=CREWS, project_root=root)
        payload = {
            "event": "TASK_ASSIGNMENT", "run_id": "run-X", "task_id": "task-1", "role": role,
            "state_revision": 5, "prompt": "p",
            "task_definition": {"description": "d", "acceptance_criteria": ["a"]},
        }
        asyncio.run(t.dispatch(payload))
        crew_cwd = os.path.join(root, CREWS[role])
        md = open(os.path.join(crew_cwd, ".pi", "messenger", "crew", "tasks", "task-1.md"), encoding="utf-8").read()
        fname = f"worker_response.task-1{WORKER_RESPONSE_SUFFIX}"
        assert fname in md, f"{role}: contract filename {fname} not in markdown"
        assert ev in md, f"{role}: target event {ev} not in markdown"
        assert "sender_role" in md
    print("PASS: dispatch markdown contains exact contract (filename + role event)")


def test_persona_responses_publish():
    for role, ev in [("PLANNER", "PLAN_SUBMITTED"), ("CODER", "CODE_SUBMITTED"), ("REVIEWER", "REVIEW_APPROVED")]:
        root = tempfile.mkdtemp()
        t, tasks_dir, crew_cwd = _dispatch(root, "task-1", role=role)
        wd = _worker_dir(crew_cwd)
        if role == "CODER":
            _write(os.path.join(wd, "hello.txt"), "hi")
            arts = [{"path": "hello.txt", "action": "CREATE", "content": None}]
        else:
            arts = []
        resp = {
            "protocol_version": "1.0", "message_id": "m", "task_id": "task-1", "run_id": "run-X",
            "state_revision": 5, "event": ev, "sender_role": role, "artifacts": arts,
            "timestamp": "2026-07-14T00:00:00Z", "logs": "ok",
            "plan_draft": (
                {"plan_name": "plan", "tasks": [
                    {"id": "task-1", "description": "d", "dependencies": [],
                     "expected_artifacts": [{"path": "game.js", "type": "CREATE"}],
                     "acceptance_criteria": ["a"]}
                ]}
                if role == "PLANNER" else None
            ),
        }
        _write(os.path.join(wd, f"worker_response.task-1{WORKER_RESPONSE_SUFFIX}"), json.dumps(resp))
        recv = PiMeshReceiverLoop(transport=t, crew_cwds=CREWS, project_root=root)
        items = recv.scan_once()
        assert len(items) == 1, f"{role}: expected 1 published, got {len(items)}"
        assert items[0]["payload"]["event"] == ev, f"{role}: got {items[0]['payload']['event']}"
    print("PASS: all three personas publish valid WorkerResponse")


def test_schema_violation_event_roman():
    root = tempfile.mkdtemp()
    t, tasks_dir, crew_cwd = _dispatch(root, "task-1")
    wd = _worker_dir(crew_cwd)
    resp = {
        "protocol_version": "1.0", "message_id": "m", "task_id": "task-1", "run_id": "run-X",
        "state_revision": 5, "event": "ROMAN", "sender_role": "CODER",
        "artifacts": [], "timestamp": "2026-07-14T00:00:00Z", "logs": "bad",
    }
    _write(os.path.join(wd, f"worker_response.task-1{WORKER_RESPONSE_SUFFIX}"), json.dumps(resp))
    recv = PiMeshReceiverLoop(transport=t, crew_cwds=CREWS, project_root=root)
    items = recv.scan_once()
    assert len(items) == 1
    assert items[0]["payload"]["event"] == "SUBMISSION_INVALID_SCHEMA"
    print("PASS: schema violation (event=ROMAN) -> SUBMISSION_INVALID_SCHEMA")


def test_receiver_path_traversal_rejected():
    root = tempfile.mkdtemp()
    _, tasks_dir, crew_cwd = _dispatch(root, "task-2")
    wd = _worker_dir(crew_cwd)
    resp = {
        "protocol_version": "1.0",
        "message_id": "msg-2",
        "task_id": "task-2",
        "run_id": "run-X",
        "state_revision": 5,
        "event": "CODE_SUBMITTED",
        "sender_role": "CODER",
        "artifacts": [{"path": "../evil.txt", "action": "CREATE", "content": None}],
        "timestamp": "2026-07-13T00:00:00Z",
        "logs": "evil",
    }
    _write(os.path.join(wd, f"worker_response.task-2{WORKER_RESPONSE_SUFFIX}"), json.dumps(resp))

    t = PiMeshTransport(crew_cwds=CREWS, project_root=root)
    recv = PiMeshReceiverLoop(transport=t, crew_cwds=CREWS, project_root=root)
    items = recv.scan_once()
    assert len(items) == 1, f"expected 1 published, got {len(items)}"
    # Pfad wurde nicht gelesen (Security); content blieb null -> Schema-Fail
    assert items[0]["payload"]["event"] == "SUBMISSION_INVALID_SCHEMA", f"expected schema fail, got {items[0]['payload']['event']}"
    print("PASS: path traversal not read -> SUBMISSION_INVALID_SCHEMA")


def test_spec_prompt_fixes_1_to_4():
    # Counter-Konfiguration durch die echte Spec rendern (Fix 1-4 Nachweis)
    from run_snake import _counter_config
    cfg = _counter_config()
    root = tempfile.mkdtemp()
    t = PiMeshTransport(crew_cwds=CREWS, project_root=root)
    payload = {
        "event": "TASK_ASSIGNMENT", "run_id": "run-X", "task_id": "task-3", "role": "CODER",
        "state_revision": 5, "prompt": cfg["prompt"],
        "task_definition": {
            "description": "Implement app.js: counter increments on click.",
            "expected_artifacts": [{"path": "app.js", "type": "CREATE"}],
            "acceptance_criteria": ["EXISTS:app.js", "CONTAINS:app.js:addEventListener", "CONTAINS:app.js:innerHTML"],
        },
    }
    asyncio.run(t.dispatch(payload))
    md = open(os.path.join(root, CREWS["CODER"], ".pi", "messenger", "crew", "tasks", "task-3.md"), encoding="utf-8").read()
    # Fix 1: kein JSON-Return mehr (auch nicht im uebergebenen prompt)
    assert "Return ONLY" not in md, "Fix 1 failed: still contains 'Return ONLY'"
    # Fix 2: Scope-Trennung: explizite Scope/Protected-Regeln statt generischem Background
    assert "SCOPE CONTRACT" in md, "Fix 2 failed: no SCOPE CONTRACT section"
    assert "AUTHORITATIVE" in md, "Fix 2 failed: no AUTHORITATIVE task marker"
    # Fix 3: acceptance criteria als MUST PASS kommuniziert
    assert "MUST PASS" in md, "Fix 3 failed: no 'MUST PASS' criteria block"
    assert "CONTAINS:app.js:innerHTML" in md, "Fix 3 failed: criteria not rendered"
    assert "textContent" in md, "Fix 3 failed: innerHTML/textContent hint missing"
    # Fix 4: kein Snake-Rest 'game.js'
    assert "game.js" not in md, "Fix 4 failed: 'game.js' still present"
    print("PASS: spec prompt fixes 1-4 applied (no JSON-return, scope split, MUST-PASS criteria, no game.js)")


def test_coder_one_pass_contract_in_spec():
    root = tempfile.mkdtemp()
    t = PiMeshTransport(crew_cwds=CREWS, project_root=root)
    payload = {
        "event": "TASK_ASSIGNMENT",
        "run_id": "run-X",
        "task_id": "task-1",
        "role": "CODER",
        "state_revision": 5,
        "prompt": "make website",
        "task_definition": {
            "description": "Implement style.css",
            "expected_artifacts": [{"path": "style.css", "type": "CREATE"}],
            "acceptance_criteria": ["EXISTS:style.css"],
        },
    }
    asyncio.run(t.dispatch(payload))
    md = open(os.path.join(root, CREWS["CODER"], ".pi", "messenger", "crew", "tasks", "task-1.md"), encoding="utf-8").read()

    assert "ONE-PASS Contract (V1)" in md
    assert "`read` NUR VOR dem ersten `write`" in md
    assert "`read` NACH dem ersten `write`" in md
    assert "`bash`" in md
    assert "`edit`" in md
    assert "TASK_FAILED" in md
    assert "worker_response" in md
    print("PASS: CODER spec contains OUTPUT contract rules")


def test_prompt_contracts_are_injected_once():
    """
    Verify that each role spec contains exactly its own output contract
    and no legacy duplicated phrases. Each dispatch overwrites the same
    task file, so we check isolation per role.
    """
    root = tempfile.mkdtemp()
    t = PiMeshTransport(crew_cwds=CREWS, project_root=root)

    roles = [
        ("PLANNER", CREWS["PLANNER"]),
        ("RESEARCHER", CREWS["PLANNER"]),  # researcher uses planning-crew dir
        ("CODER", CREWS["CODER"]),
        ("REVIEWER", CREWS["REVIEWER"]),
    ]

    legacy_phrase = "Schreibe SOFORT eine Datei namens `worker_response.{task_id}.response.json`"

    for role, crew_dir in roles:
        payload = {
            "event": "TASK_ASSIGNMENT",
            "run_id": "run-X",
            "task_id": "task-1",
            "role": role,
            "state_revision": 5,
            "prompt": "make website",
            "task_definition": {
                "description": f"{role} task",
                "expected_artifacts": [{"path": "index.html", "type": "CREATE"}],
                "acceptance_criteria": ["EXISTS:index.html"],
            },
        }
        asyncio.run(t.dispatch(payload))
        md = open(os.path.join(root, crew_dir, ".pi", "messenger", "crew", "tasks", "task-1.md"), encoding="utf-8").read()

        # This role's contract appears exactly once
        assert "Output Contract" in md
        assert md.count("Output Contract") == 1

        # No other role's contract leaked in
        for other_role, _ in roles:
            if other_role == role:
                continue
            assert f"OUTPUT CONTRACT ({other_role})" not in md

        # Legacy duplicated phrase removed
        assert legacy_phrase not in md
        print(f"PASS: {role} contract injected exactly once, isolated")

    print("PASS: all role contracts are isolated and injected once")


if __name__ == "__main__":
    test_dispatch_writes_task_files()
    test_receiver_inlines_and_dedupes()
    test_receiver_path_traversal_rejected()
    test_contract_filename_in_markdown()
    test_persona_responses_publish()
    test_schema_violation_event_roman()
    test_spec_prompt_fixes_1_to_4()
    test_coder_one_pass_contract_in_spec()
    test_prompt_contracts_are_injected_once()
    print("\nALL TESTS PASSED")
