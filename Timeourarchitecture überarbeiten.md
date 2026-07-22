# 📡 LLM Liveness & Timeout Architecture  
## (Roadmap für Streaming Heartbeats / Industrial Timeout Handling)

---

## 🎯 Ziel

Diese Dokumentation beschreibt die zukünftige Architektur zur stabilen Behandlung von LLM‑Latenz innerhalb der Firma Engine.

Aktuell arbeitet die Engine mit einem **Blind‑Timeout‑Modell**:

- Wenn ein Task länger als `HARD_TIMEOUT` (z. B. 300s) im Zustand `CLAIMED` bleibt,
- wird ein `WORKER_TIMEOUT` ausgelöst,
- der Task wird zurückgesetzt.

Dieses Modell unterscheidet jedoch nicht zwischen:

- 🟢 *Langsamem LLM* (arbeitet noch, produziert Tokens)
- 🔴 *Abgestürztem Worker* (keine Aktivität mehr)

Ziel ist es, diese Unterscheidung industriell korrekt zu implementieren.

---

# 🧠 Problemstellung

Große Modelle (z. B. Llama‑70B) können 200+ Sekunden Antwortzeit benötigen.

Für die Engine sieht das aktuell identisch aus wie ein abgestürzter Worker.

Das führt zu:

- unnötigen `WORKER_TIMEOUT`-Events
- Revisionserhöhungen
- Verwerfen spät eintreffender Antworten
- ineffizientem Neustart von Tasks

Das Timeout-System ist derzeit **blind gegenüber echter Liveness**.

---

# 🏗️ Architektur-Optionen

## 1️⃣ Adaptive Timeouts (Kurzfristig)

Erhöhung oder dynamische Anpassung des Hard-Timeouts je nach Phase.

**Vorteile:**
- Schnell implementiert
- Kein Architekturumbau

**Nachteile:**
- Erkennt keinen echten Absturz
- Kann Zombie-Tasks lange im System halten
- Nur Parameter-Tuning, kein struktureller Fix

---

## 2️⃣ Provider-Timeout-Alignment (Mittelfristig)

Synchronisierung von:

- HTTP-Client-Timeout
- Worker-Timeout
- Orchestrator-Hard-Timeout

**Ziel:**
Der Worker erkennt API-Abbruch selbst und sendet ein `ERROR_REPORT`, bevor der Orchestrator eingreifen muss.

**Vorteile:**
- Reduziert künstliche Kollisionen
- Sauberer Fehlerpfad

**Nachteile:**
- Erkennt weiterhin keine „langsame, aber lebende“ Antwort

---

## 3️⃣ Streaming Heartbeats (Industrieller Standard)

### ✅ Ziel

Unterscheidung zwischen:

- *Langsam, aber lebendig*
- *Tot / abgestürzt*

### ✅ Grundprinzip

Statt auf vollständige JSON-Antwort zu warten:

1. LLM liefert Antwort im Streaming-Modus.
2. Worker sendet periodisch `WORKER_HEARTBEAT`.
3. Orchestrator aktualisiert `last_seen`.
4. Timeout greift nur, wenn: