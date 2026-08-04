
## OUTPUT CONTRACT (CODER)

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
artifacts: [{"path": "<pfad/zur/datei>", "action": "CREATE|UPDATE", "content": null}]
timestamp: {now}
logs: <freier Status-Text>
```

**Regeln:**
- Nur Dateien aus dem erlaubten Scope
- Keine Dateien außerhalb von `scope_files`
- Wenn du eine protected-Datei ändern musst → STOP und `TASK_FAILED` mit `OUT_OF_SCOPE`

**ONE-PASS Contract (V1)**
- Erlaubt: `read` NUR VOR dem ersten `write` (Task-Spec + staged Projektdateien).
- Verboten: `read` NACH dem ersten `write`, `bash`, `edit`.
- Wenn du denkst, du musst iterieren → beende mit `TASK_FAILED` + Grund.
- Abschluss: alle geforderten Dateien schreiben, dann `worker_response` schreiben und sofort stoppen.
