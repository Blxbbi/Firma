
## OUTPUT CONTRACT (RESEARCHER)

**Schreibe die Datei EXAKT als** `worker_response.{task_id}.response.json` **in** `.pi/messenger/crew/`.

Inhalt (genau dieses Schema):
```
protocol_version: 1.0
message_id: <eindeutige uuid>
task_id: {task_id}
run_id: {run_id}
state_revision: {state_revision}
event: {target_event}
sender_role: {role}
artifacts: [{"path": "research/brief.md", "action": "CREATE", "content": null}]
timestamp: {now}
logs: <freier Status-Text>
```

ZUSÄTZLICH: Schreibe `research/brief.md` (relativ zu `.pi/messenger/crew/`, also `.pi/messenger/crew/research/brief.md`).
