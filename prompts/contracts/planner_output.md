
## OUTPUT CONTRACT (PLANNER)

**WICHTIG: Schreibe die Datei EXAKT als** `plan_draft.{task_id}.json` **in** `.pi/messenger/crew/`.

`plan_draft` MUSS ein PlanDraftSchema sein (kein freier Text):
```json
{
  "plan_name": "<kurzer Name>",
  "tasks": [
    {
      "id": "task-N",
      "description": "<was gebaut wird>",
      "dependencies": ["task-X", ...],
      "expected_artifacts": [
        {"path": "datei.html", "type": "CREATE|UPDATE"}
      ],
      "acceptance_criteria": [
        "<Testkriterium>"
      ],
      "review_checklist": [
        "<Reviewkriterium>"
      ],
      "hard_constraints": [
        "<Must-use or must-not-use technical constraint>"
      ],
      "tech_stack": [
        "<technology choice>"
      ]
    }
  ]
}
```

**Regeln:**
- Dateinamen MÜSSEN Kleinbuchstaben sein (z.B. `index.html`, `style.css`, `app.js`)
- Max 3 `expected_artifacts` pro Task
- Max 10 Tasks insgesamt
- Keine externen Dependencies in `expected_artifacts`
- **File Ownership**: Jede Datei darf nur in genau einem CODER-Task als `expected_artifacts` vorkommen (keine Duplikate über Tasks hinweg).
- **Logische Einheiten**: Wenn eine Aufgabe logisch mehrere Dateien erfordert (z.B. eine HTML-Seite + CSS + JS), müssen ALLE abhängigen Dateien in demselben `expected_artifacts`-Array stehen. Trenne zusammengehörige Dateien nicht auf verschiedene Tasks auf.
- `review_checklist` muss konkrete, nachweisbare Kriterien enthalten.
- `hard_constraints` muss technisch prüfbare Aussagen enthalten.
- `tech_stack` muss die tatsächlich vorgesehenen Technologien/Versionen enthalten.

**Beispiel für eine Website-Task (alle 3 Dateien gemeinsam):**
```json
{
  "id": "task-1",
  "description": "Erstelle die vollständige Firmen-Website mit HTML, CSS und JavaScript",
  "expected_artifacts": [
    {"path": "index.html", "type": "CREATE"},
    {"path": "style.css", "type": "CREATE"},
    {"path": "app.js", "type": "CREATE"}
  ],
  "acceptance_criteria": [
    "index.html existiert und verweist auf style.css und app.js",
    "style.css enthält responsive Layouts und WCAG-AA-konforme Farben",
    "app.js enthält die Interaktivität der Seite"
  ],
  "review_checklist": [
    "index.html enthält kein inline CSS oder JS",
    "style.css enthält keine externen CDNs",
    "app.js verwendet keine localStorage oder sessionStorage"
  ],
  "hard_constraints": [
    "Use only vanilla HTML/CSS/JS",
    "No external CDNs or frameworks"
  ],
  "tech_stack": [
    "HTML5",
    "CSS3",
    "Vanilla JavaScript"
  ]
}
```

**Falsches Beispiel (NICHT tun — getrennte Tasks für zusammengehörige Dateien):**
```json
// FALSCH: HTML, CSS und JS gehören zusammen, müssen aber in einem Task stehen
{"id": "task-1", "expected_artifacts": [{"path": "index.html", "type": "CREATE"}]},
{"id": "task-2", "expected_artifacts": [{"path": "style.css", "type": "CREATE"}]},
{"id": "task-3", "expected_artifacts": [{"path": "app.js", "type": "CREATE"}]}
```
