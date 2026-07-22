# 🔭 Vision: PiProvider als Compute-Backend (nicht als Agentisierung)

**Datum:** 13.07.2026
**Status:** Design-Vision, vorbereitend für Implementierung
**Kontext:** Firma Engine ist ab heute (Happy Path `COMPLETED`) stabil. Compute soll austauschbar werden, ohne Governance anzufassen.

---

## 1. Das Ziel

Firma soll zur Laufzeit zwischen zwei LLM-Backends wählen können:

| Backend | Rolle | Telemetrie |
|---------|-------|-----------|
| `NvidiaProvider` | Aktuelles, direktes NIM-Backend | Latenz (Execution_Audit) |
| `PiProvider` | pi-Instanz als Compute-Substrat | Token, Kosten, Prompt-Transparenz, Tool-Use |

Entscheidungskriterium: **Env-Var `FIRMA_LLM_BACKEND=nvidia|pi`** + optionaler Fallback.
Kein Code-Touch nötig, jederzeitiger Rollback.

---

## 2. Architektonische Prinzipien (Dependency Inversion)

Firma ist bereits entkoppelt:

```
PlannerWorker / ExecutionWorker
        │  (kennen nur das Interface)
        ▼
   BaseLLMProvider  ◄── abstrakte generate() / generate_json()
        │
        ├── NvidiaProvider   (heute, unverändert)
        └── PiProvider       (neu, gleiches Interface)
```

**Regel:** `PiProvider` implementiert `BaseLLMProvider`. Er darf:
- ❌ Keinen State ändern
- ❌ Keine direkte DB-Interaktion haben
- ❌ Keine Events selbst triggern

Er ist **Compute-Substrat**, nicht Orchestrator. Alle Governance (Guardian, Orchestrator, Repository) bleibt zu 100% im Firma-Kern.

---

## 3. Die pi-Topologie: Wie es konkret läuft

Firma läuft als **Engine-Instanz** und joined den **pi-messenger Mesh**. Daneben existiert (mindestens) eine **Compute-Worker-Instanz** – eine pi-Instanz, die *ausschließlich* als LLM-Backend konfiguriert ist.

```
┌─────────────────────────────────────────────────────────────┐
│  pi-messenger Mesh (durable, observability-enabled)          │
│                                                               │
│  ┌──────────────────────┐         ┌──────────────────────┐  │
│  │  Firma Engine-Instanz │         │  Compute-Worker       │  │
│  │  (Orchestrator)       │         │  (pi, pure LLM)       │  │
│  │                       │         │                       │  │
│  │  Planner/Executor ────┼──msg───►│  ruft pi's LLM-Stack  │  │
│  │  PiProvider           │         │  normalisiert zu JSON │  │
│  │  (Client-Seite)       │◄─msg────┼───────────────────────│  │
│  └──────────────────────┘         └──────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

**Kommunikation ausschließlich über pi-messenger** – nicht via OS-Subprocess.
Grund: pi-messenger liefert genau die Telemetrie, die wir wollen (Token, Prompt, Latenz, Routing).

---

## 4. Message Flow (Sequenz pro LLM-Call)

```
1. Executor.handle_assignment()
      └─> provider.generate_json(system_prompt, user_prompt, schema)
             │
2. PiProvider (Client-Seite im Engine):
      └─> messenger.publish(
            to="compute-worker",
            type="COMPUTE_REQUEST",
            payload={ system_prompt, user_prompt, schema, request_id }
          )
             │  (async, wartet auf Correlation-ID)
             ▼
3. Compute-Worker (pi-Instanz) empfängt COMPUTE_REQUEST:
      ├─> ruft pi's eigenen LLM-Stack (OpenRouter/GPT/Claude/etc.)
      ├─> erhält Modell-Antwort
      ├─> STRICTE NORMALISIERUNG zu ExecutorLLMOutput-konformem JSON
      └─> messenger.publish(
            to="firma-engine",
            type="COMPUTE_RESULT",
            payload={ request_id, normalized_json }
          )
             │
4. PiProvider empfängt COMPUTE_RESULT:
      └─> gibt normalized_json an Executor zurück
             │
5. Executor validiert gegen ExecutorLLMOutput (Schema), wie heute.
```

**Harte Grenze (Normalization Boundary):**
Nur das **strikt normalisierte JSON** geht zurück. Keine Gedanken, keine Tool-Calls, keine Nebenkanäle. Der Compute-Worker ist eine "reine Funktion": `(system, user, schema) → json`.

---

## 5. Warum pi-messenger (und nicht simple Subprocess-Shell)?

| Aspekt | Subprocess (`pi` CLI spawn) | pi-messenger Mesh |
|--------|---------------------------|-------------------|
| Token-Tracking | ❌ (nur wenn CLI loggt) | ✅ Native Telemetrie |
| Prompt-Transparenz | ⚠️ Manuell | ✅ Sichtbar im Mesh-Feed |
| Durability bei Crash | ❌ Verloren | ✅ Persistenter Feed |
| Fallback/Retry | ⚠️ Selbst gebaut | ✅ Messenger-Reserve |
| Multi-Step Reasoning | ❌ Stateless | ✅ Worker kann Loops intern |
| Isolation | ✅ Prozess | ✅ Instanz |

pi-messenger ist die "Observability-Schicht", die der Berater fordert.

---

## 6. A/B-Vergleich & Fallback (Strategischer Gewinn)

```python
# engine/settings.py
LLM_BACKEND = os.getenv("FIRMA_LLM_BACKEND", "nvidia")  # "nvidia" | "pi"

def get_provider(fallback=True):
    try:
        if LLM_BACKEND == "pi":
            return PiProvider()
        return NvidiaProvider()
    except Exception:
        if fallback:
            return NvidiaProvider()  # deterministischer Sicherheitsnetz
```

**A/B-Workflow:**
1. Run mit `FIRMA_LLM_BACKEND=nvidia` → Metriken loggen.
2. Run mit `FIRMA_LLM_BACKEND=pi` → gleiche Metriken loggen.
3. Vergleich: Token-Kosten, Latenz, Output-Qualität (Verifier-Pass-Rate), Retry-Budget-Verbrauch.
4. Entscheidung: Welches Backend liefert bei gleichem Prompt besseren Durchsatz?

**Rollback:** Env-Var auf `nvidia` → sofort wieder der validierte Happy-Path-Stand von heute.

---

## 7. Abgrenzung: Compute-Backend vs. Agentisierung (WICHTIG)

Der Berater betont: **Nicht als "Agentisierung", sondern als "Compute-Backend".**

| Compute-Backend (gewollt) | Agentisierung (verboten) |
|---------------------------|--------------------------|
| pi führt nur den LLM-Call aus | pi plant selbstständig Tasks |
| Eine Runde: Prompt → JSON | Multi-Step autonome Loops |
| Kein Zugriff auf Firma-State | Greift auf Tasks/DB zu |
| Austauschbar wie ein Treiber | Wird Teil der Orchestrierung |

Der Compute-Worker ist so dumm wie ein NIM-Endpoint – nur mit besserer Telemetrie.

---

## 8. Nächste Schritte (Implementierungs-Split, nicht-invasiv)

1. **`engine/providers/pi_provider.py`** – `class PiProvider(BaseLLMProvider)`, Client-Seite (messenger-publish + wait-for-correlation).
2. **`engine/providers/pi_compute_worker.py`** – die pi-Instanz-Seite (empfängt COMPUTE_REQUEST, ruft LLM, normalisiert).
3. **`engine/settings.py`** – `LLM_BACKEND` + `get_provider()` Factory mit Fallback.
4. **`run_snake.py`** – `get_provider()` statt hardcoded `NvidiaProvider`.
5. **Doku:** Diese Vision als Referenz; `docs/Stand 13.07.2026.md` bleibt Happy-Path-Baseline.

**Risiko:** Minimal. Bestehender `NvidiaProvider` wird nicht angefasst. Firma-Kern (Governance/Orchestrator/Repository) unverändert.

---

## 🧠 Ein-Satz-Fazit

> Pi wird nicht zum Chef gemacht – es wird zum besseren Werkzeug. Die Engine orchestriert, pi rechnet. Alles andere bleibt deterministisch.
