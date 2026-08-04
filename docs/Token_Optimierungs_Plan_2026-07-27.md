# Token-Optimierungs-Plan für Firma PiMesh
**Ziel:** Nachhaltige Token-Effizienz ohne Qualitätsverlust  
**Prinzip:** Systematik vor Symptom-Bekämpfung

---

## 📊 Ausgangslage (Run-Vergleich)

| Metrik | Dummy Reviewer | Echter Reviewer | Delta |
|--------|----------------|-----------------|-------|
| **Total Tokens** | 1,329,535 | 1,241,243 | -88,292 (-6.6%) |
| **Output Tokens** | 91,513 (6.9%) | 87,323 (7.0%) | -4,190 |
| **Input Tokens** | 313,478 (23.6%) | 358,400 (28.9%) | +44,922 |
| **Cache Tokens** | 924,544 (69.5%) | 795,520 (64.1%) | -129,024 |

**Erkenntnis:** Output-Tokens sind nur **6-7%** des Gesamtverbrauchs!  
**Hauptproblem:** Input-Tokens und Workspace-Größe.

---

## 🎯 Strategie: 3-Säulen-Modell

### Säule 1: **Kontext-Effizienz** (Input-Tokens senken)
**Ziel:** Weniger Tokens pro Turn laden, ohne Information zu verlieren

#### Maßnahmen:
1. **Workspace-Priorisierung**
   - Nur **relevante Dateien** in den Prompt laden
   - Große Dateien (**style.css, app.js**) zusammenfassen
   - Alte Artefakte komprimieren

2. **Prompt-Template-Optimierung**
   - System-Prompts auf **Kern-Prinzipien** reduzieren
   - Wiederholende Anweisungen entfernen
   - Format-Vorgaben standardisieren

3. **Turn-Kompression**
   - Ältere Turns **zusammenfassen** statt vollständig zu laden
   - Nur **letzte 3-5 Turns** vollständig laden
   - Ältere Turns auf **Key-Insights** reduzieren

---

### Säule 2: **Output-Disziplin** (Output-Tokens senken)
**Ziel:** Modell gibt nur das Gefragte aus, keine "Small Talk"-Antworten

#### Maßnahmen:
1. **Format-Vorgaben**
   - Strukturierte Formate: JSON, Listen, Tabellen
   - "Nur Code, keine Erklärungen" für CODER
   - "Max 3 Sätze pro Task" für PLANNER

2. **Antwort-Kontrolle**
   - Keine Wiederholungen
   - Keine überflüssigen Meta-Kommentare
   - Keine "Ich habe verstanden..." Einleitungen

3. **Task-spezifische Prompts**
   - CODER: "Schreibe nur den Code, keine Kommentare"
   - PLANNER: "Nur Task-Liste + Dateien, keine Erklärungen"
   - RESEARCHER: "Nur Fakten, keine Interpretation"

---

### Säule 3: **Turn-Effizienz** (Anzahl Turns senken)
**Ziel:** Weniger Iterationen pro Task

#### Maßnahmen:
1. **Klare Akzeptanzkriterien**
   - Pro Task: **max 3 Akzeptanzkriterien**
   - Messbar, nicht interpretierbar
   - Beispiel: "index.html hat 7 Sektionen" statt "index.html ist vollständig"

2. **Prompt-Personalisierung**
   - Pro Rolle: **eigener Prompt**
   - Keine generischen "Du bist ein hilfreicher Assistent" Prompts
   - Konkrete Handlungsanweisungen

3. **Retry-Prävention**
   - Erste Antwort muss **100% korrekt** sein
   - Keine "try again" Schleifen
   - Sofortige Korrektur bei Fehlern

---

## 📋 Schritt-für-Schritt-Plan

### Phase 1: Diagnose (Woche 1)
**Ziel:** Verstehen, wo Tokens hingehen

1. **Workspace-Analyse**
   - Welche Dateien werden pro Rolle geladen?
   - Welche Dateien sind >10KB?
   - Welche Dateien sind redundant?

2. **Prompt-Analyse**
   - Welche Teile des System-Prompts sind redundant?
   - Welche Teile werden ignoriert?
   - Welche Teile sind zu lang?

3. **Output-Analyse**
   - Welche Teile der Antworten sind überflüssig?
   - Wo gibt es Wiederholungen?
   - Wo gibt es "Small Talk"?

---

### Phase 2: Quick Wins (Woche 2)
**Ziel:** Schnelle, nachhaltige Verbesserungen

1. **Output-Formatierung**
   - CODER: "Nur Code, keine Kommentare"
   - PLANNER: "JSON-Format, keine Erklärungen"
   - RESEARCHER: "Bullet-Points, keine Interpretation"

2. **Workspace-Bereinigung**
   - Alte Runs archivieren (>7 Tage)
   - Große Dateien zusammenfassen
   - Redundante Dateien entfernen

3. **Prompt-Kürzung**
   - System-Prompts auf **50% reduzieren**
   - Wiederholungen entfernen
   - Unwichtige Details entfernen

---

### Phase 3: Nachhaltige Optimierung (Woche 3-4)
**Ziel:** Langfristige Token-Effizienz

1. **Kontext-Kompression**
   - Ältere Turns automatisch zusammenfassen
   - Workspace-Dateien priorisieren
   - Intelligentes Laden von Dateien

2. **Role-spezifische Prompts**
   - Pro Rolle: eigener optimierter Prompt
   - Klare Handlungsanweisungen
   - Keine generischen Phrasen

3. **Monitoring**
   - Token-Tracking pro Turn
   - Lecks automatisch erkennen
   - Alerts bei ungewöhnlichem Verbrauch

---

## 🛠️ Konkrete Maßnahmen (Priorisiert)

### P1: Output-Disziplin (sofort, -30% Output)
```python
# CODER Prompt kürzen
CODER_PROMPT = """
Schreibe nur den Code. Keine Erklärungen, keine Kommentare.
Nur das, was in expected_artifacts gefordert ist.
"""

# PLANNER Prompt kürzen  
PLANNER_PROMPT = """
Erstelle einen Plan als JSON. Nur Tasks + Dateien.
Max 3 Sätze pro Task. Keine Erklärungen.
"""
```

### P2: Workspace-Bereinigung (diese Woche, -20% Input)
```python
# Vor dem Spawn: Nur relevante Dateien laden
def prepare_workspace(task_id, role):
    # Lade nur Dateien, die älter als 1h sind
    # Komprimiere Dateien >5KB
    # Entferne duplicate Files
    pass
```

### P3: Turn-Kompression (nächste Woche, -15% Input)
```python
# Nach 5 Turns: Ältere Turns zusammenfassen
def compress_turns(conversation):
    if len(conversation) > 5:
        # Fasse Turns 1-3 zu einem Summary zusammen
        # Lade nur Turns 4-5 vollständig
        pass
```

---

## 📈 Erfolgsmetriken

| Metrik | Current | Ziel (4 Wochen) |
|--------|---------|-----------------|
| **Total Tokens/Run** | 1,241,243 | < 900,000 (-27%) |
| **Output/Response** | 7.0% | < 5% |
| **Turns/Task** | 6.8 | < 5 |
| **Cache-Rate** | 64% | > 70% |

---

## 🚀 Nächste Schritte

**Soll ich:**
1. **Mit P1 starten** (Output-Formatierung) und sofort einen Run machen?
2. **Zuerst Phase 1** (Diagnose) komplett machen?
3. **Nur die größten Lecks** angehen (CODER task-2, RESEARCHER Turns)?

Was bevorzugst du?
