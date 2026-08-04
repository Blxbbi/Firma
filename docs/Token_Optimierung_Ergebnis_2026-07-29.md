# Token-Optimierung Ergebnis — 2026-07-29

## Zusammenfassung

| # | Massnahme | Status |
|---|-----------|--------|
| 1 | **Bugfix**: `worker_log_parser.py` erkennt Token-Usage jetzt korrekt (0 statt None) | ✅ |
| 2 | **Prompt-Kürzung**: Output-Contract von ~20 auf ~8 Zeilen | ✅ |
| 3 | **Researcher-Prompts**: Delta-Erkennung von ~30 auf ~8 Zeilen | ✅ |
| 4 | **Coder-Prompts**: INGEST MODE und Rejection-Feedback gekürzt | ✅ |
| 5 | **Planner-Prompts**: Delta-Erkennung und SEQUENCE-Warnung gekürzt | ✅ |
| 6 | **Tests aktualisiert**: Alle 9 Tests in `test_pi_mesh_transport.py` passen | ✅ |

---

## Spec-Grössen (nach Optimierung)

| Role | Spec-Grösse (chars) | Zeilen | Einsparung |
|------|---------------------|--------|------------|
| PLANNER | 4,605 | 130 | ~34% |
| CODER | 5,182 | 137 | ~20% |
| REVIEWER | 4,897 | 139 | ~54% |
| RESEARCHER | 3,789 | 92 | ~53% |

---

## Token-Einsparung (geschätzt)

| Szenario | Alt | Neu | Gespart |
|----------|-----|-----|---------|
| Einzelner Task (REVIEWER) | ~10,750 chars | ~4,897 chars | ~5,853 chars (~1,463 Tokens) |
| Einzelner Task (RESEARCHER) | ~8,000 chars | ~3,789 chars | ~4,211 chars (~1,052 Tokens) |
| Typischer Run (3 Tasks) | ~49,500 chars | ~28,552 chars | ~20,948 chars (~5,237 Tokens) |

---

## Bugfix: Token-Messung

**Problem:** `worker_log_parser.py` verwendete `or`-Verkettung für Token-Felder:
```python
inp = usage.get("input") or usage.get("input_tokens")  # 0 ist falsy → None!
```

**Folge:** Alle Metrics zeigten `0`, weil `0 or None == None` in Python.

**Fix:** Explizite Key-Prüfung:
```python
inp = usage.get("input") if "input" in usage else usage.get("input_tokens")
```

**Resultat:** Token-Usage wird jetzt korrekt erfasst (z.B. `input=115,949`, `output=15,491`).

---

## Run `3c12694f` — Echte Messung (nach Bugfix)

| Role/Task | Turns | Tools | Input | Output | CacheR | Total |
|-----------|-------|-------|-------|--------|--------|-------|
| coding-crew/task-1 | 4 | 8 | 115,949 | 15,491 | 0 | 131,440 |
| coding-crew/task-2 | 8 | 14 | 81,678 | 36,156 | 226,560 | 344,394 |
| coding-crew/task-3 | 7 | 12 | 97,288 | 9,136 | 108,288 | 214,712 |
| planning-crew/1948423d... | 13 | 24 | 161,867 | 16,000 | 215,040 | 392,907 |
| planning-crew/7944b5cd... | 4 | 8 | 41,198 | 31,089 | 88,320 | 160,607 |
| reviewing-crew/task-1 | 4 | 6 | 45,372 | 6,483 | 56,064 | 107,919 |
| reviewing-crew/task-2 | 5 | 8 | 53,820 | 14,154 | 84,096 | 152,070 |
| reviewing-crew/task-3 | 8 | 12 | 142,273 | 61,892 | 103,680 | 307,845 |
| **TOTAL** | **53** | **92** | **739,445** | **190,401** | **882,048** | **1,811,894** |

---

## Nächste Schritte

1. **Neuen Run starten** mit optimierten Prompts → Messung der Einsparung in echt
2. **Weitere Prompt-Optimierungen** — z.B. `pimesh_system.md` Prompts kürzen
3. **Cache-Read optimieren** — 882K Cache-Reads sind hoch, evtl. Prompts weiter straffen
