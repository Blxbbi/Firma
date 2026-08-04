import re
import os

files = [
    'pimesh/reviewing-crew/.pi/messenger/crew/tasks/task-4.md',
    'pimesh/reviewing-crew/.pi/messenger/crew/tasks/task-5.md',
    'pimesh/reviewing-crew/.pi/messenger/crew/tasks/task-6.md',
    'pimesh/reviewing-crew/.pi/messenger/crew/tasks/task-7.md',
]

for filepath in files:
    print(f"=== Optimiere {filepath} ===")
    
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Extract task_id and run_id from assignment
    task_id_match = re.search(r'"task_id": "([^"]+)"', content)
    run_id_match = re.search(r'"run_id": "([^"]+)"', content)
    state_revision_match = re.search(r'"state_revision": ([0-9]+)', content)
    
    task_id = task_id_match.group(1) if task_id_match else 'task-N'
    run_id = run_id_match.group(1) if run_id_match else 'unknown'
    state_revision = state_revision_match.group(1) if state_revision_match else '1'
    
    # Extract acceptance criteria
    criteria_match = re.search(r'"acceptance_criteria": \[(.*?)\]', content, re.DOTALL)
    if criteria_match:
        criteria_text = criteria_match.group(1)
        criteria = re.findall(r'"([^"]+)"', criteria_text)
    else:
        criteria = []
    
    # Extract file to review
    file_match = re.search(r'### `([^`]+)`', content)
    file_to_review = file_match.group(1) if file_match else 'unknown'
    
    # Build optimized prompt
    optimized = f'''# Firma Task {task_id}  (Role: REVIEWER)

Du bist ein REVIEWER. Prüfe in EINEM DURCHGANG, ob die CODER-Implementierung die Akzeptanzkriterien erfüllt.

## Aufgabe
- Lies NUR diese Datei und die zu prüfende(n) Datei(en).
- Schreibe NUR die `worker_response.{{task_id}}.response.json`.
- Keine Code-Änderungen, keine Iteration, keine weiteren Reads.

## Zu prüfende Datei
- `{file_to_review}`

## Akzeptanzkriterien (MUST PASS)
'''
    
    for i, criterion in enumerate(criteria[:5], 1):
        optimized += f'- {criterion}\n'
    
    optimized += f'''
## Output
Schreibe die Datei EXAKT als `worker_response.{task_id}.response.json` in `.pi/messenger/crew/` mit:
```json
{{
  "protocol_version": "1.0",
  "message_id": "<eindeutige uuid>",
  "task_id": "{task_id}",
  "run_id": "{run_id}",
  "state_revision": {state_revision},
  "event": "REVIEW_APPROVED" | "REVIEW_FAILURE",
  "sender_role": "REVIEWER",
  "artifacts": [],
  "timestamp": "<ISO-Zeitstempel>",
  "logs": "<max 5 Bullet Issues oder Begründung>"
}}
```

## Regeln
- `REVIEW_APPROVED`: Alle Kriterien erfüllt.
- `REVIEW_FAILURE`: Max 5 Issues auflisten.
- Keine weiteren Dateien schreiben.

## Hard Stops
- Datei außerhalb `.pi/messenger/crew/` → TASK_FAILED
- Nach Write sofort stoppen, kein Edit/Bash/Weiteres Read
'''
    
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(optimized)
    
    old_lines = len(content.splitlines())
    new_lines = len(optimized.splitlines())
    print(f"  -> {old_lines} Zeilen -> {new_lines} Zeilen ({100 - new_lines/old_lines*100:.1f}% Reduktion)")
    print()
