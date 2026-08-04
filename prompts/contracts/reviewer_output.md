
## OUTPUT CONTRACT (REVIEWER)

**Schreibe die Datei EXAKT als** `worker_response.{task_id}.response.json` **in** `.pi/messenger/crew/`.

Inhalt (genau dieses Schema):
```
protocol_version: 1.0
message_id: <eindeutige uuid>
task_id: {task_id}
run_id: {run_id}
state_revision: {state_revision}
event: REVIEW_APPROVED | REVIEW_FAILURE
sender_role: {role}
artifacts: []
timestamp: {now}
logs: <max 5 Bullet Issues oder Begruendung>
```

**Regeln:**
- `REVIEW_APPROVED`: Alle Acceptance Criteria erfuellt
- `REVIEW_FAILURE`: Liste max 5 Issues, warum es fehlschlägt
- Keine weiteren Dateien schreiben
