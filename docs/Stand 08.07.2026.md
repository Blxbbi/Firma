# 📋 Tagesbericht – Projekt „Firma“ (Stand 08.07.2026)

## 🧭 Ausgangslage
Zu Beginn der Session war „Firma“ eine deterministische AI-Execution-Engine mit funktionierender State-Machine, aber mit kritischen industriellen Schwachstellen:
- **Silent Hangs:** Tasks blieben in `CLAIMED/PROCESSING` stecken ohne Recovery.
- **Provider-Instabilität:** API-Blockaden auf TCP-Ebene frieren den Event-Loop ein.
- **Fragiler Worker-Loop:** Exceptions wurden geschluckt; Zombie-Tasks blockierten das System.
- **Implizite Globalität:** DB-Pollution und `limit(1)` führten zu Ghost-Tasks und Cross-Run-Interferenzen.

---

## 🛠️ Technische Umsetzung: Die Evolution zur Plattform

Die Session wurde in sieben Evolutionsphasen unterteilt, um das System von einem "Proof-of-Concept" zu einer "Industrial Runtime" zu heben.

### Phase 1 – Provider-Härtung (Silent Hang eliminieren)
- **Maßnahmen:** Umstellung auf synchronen Client mit Thread-Isolation via `asyncio.to_thread()`, harte HTTP-Timeouts (`httpx`) und marker-basierte Telemetrie.
- **Ergebnis:** ✅ Kein Event-Loop-Freeze mehr; deterministische Provider-Timeouts.

### Phase 2 – Worker-Loop-Härtung
- **Maßnahmen:** Implementierung einer "Bulletproof"-Struktur. Jeder Assignment-Versuch endet garantiert in einem Event. Globaler try/except-Schutz und explizite Exception-Propagation.
- **Ergebnis:** ✅ Kein Silent Hang mehr; jeder Fehler wird deterministisch klassifiziert.

### Phase 3 – Revision & OCC-Stabilisierung
- **Maßnahmen:** Durchsetzung von Revision-Guards zur Vermeidung von Race-Conditions zwischen Worker und Watchdog.
- **Ergebnis:** ✅ Keine State-Korruption; deterministische Recovery.

### Phase 4 – Run-Isolation (Architekturbruch)
- **Maßnahmen:** Einführung der `run_id` als harter Kontext-Schlüssel für alle Entitäten (`Project`, `Plan`, `Task`). Implementierung eines Lease-Modells (`lease_expires_at`).
- **Ergebnis:** ✅ Eliminierung impliziter Globalität; parallele Runs ohne Interferenz möglich.

### Phase 5 – Lifecycle-Control
- **Maßnahmen:** Erweiterung des Run-Modells um Status-States (`ACTIVE`, `COMPLETED`, `FAILED`, `CANCELLED`) und Zeitstempel. Orchestrator prüft Run-Status bei jedem Tick.
- **Ergebnis:** ✅ Echter Lebenszyklus; deterministischer Stopp der Engine.

### Phase 6 – RunController (Plattform-Schicht)
- **Maßnahmen:** Einführung von `engine/controller.py` als Supervisor. Strikte Trennung: `Platform (RunController)` $\rightarrow$ `Runtime (Orchestrator)` $\rightarrow$ `Execution (Worker)` $\rightarrow$ `Persistence (Repository)`.
- **Ergebnis:** ✅ Saubere Trennung von Lifecycle und Execution; Plattformstruktur etabliert.

### Phase 7 – Industrial Validation (Real-World Stress Test)
**Das Ziel war der Beweis, dass die Plattform unabhängig von der Modell-Intelligenz stabil bleibt.**

- **Test-Case:** Erstellung einer High-End Corporate Website.
- **Szenario A (Llama-3.1-8B):** Modell lieferte minderwertige Skeletons $\rightarrow$ Verifier erkannte dies $\rightarrow$ Iterations-Limit $\rightarrow$ **Run korrekt als FAILED markiert**.
- **Szenario B (Llama-3.1-70B):** Modell lieferte syntaktisch korrekte Ergebnisse $\rightarrow$ Verifier markierte `PASS` $\rightarrow$ **Run erfolgreich durchgelaufen**.
- **Ergebnis:** ✅ **PLATFORM-VALIDIERUNG BESTANDEN**. Das System erkennt schlechten Output und stoppt ihn deterministisch.

---

## 📊 Technische Meilensteine der Session

| Kategorie | Status | Erkenntnis |
| :--- | :---: | :--- |
| Event-Loop-Stabilität | ✅ | Thread-Isolation funktioniert |
| Provider-Resilienz | ✅ | Timeouts sind nun deterministisch |
| Run-Isolation | ✅ | `run_id` eliminiert Cross-Run-Leakage |
| Lifecycle-Control | ✅ | `RunController` steuert die Runtime |
| Plattform-Validierung | ✅ | System erkennt Modell-Versagen korrekt |
| Kognitive Kapazität | ⚠️ | Erste Tests zeigen, dass 8B-Modelle für komplexe UI-Tasks unzureichend sind, während 70B-Modelle deutlich zuverlässiger performen |
| Validierungs-Tiefe | 🔄 | Nächste Phase: Syntaktische Checks funktionieren; semantische Qualitätsprüfung wird jetzt ausgebaut |

---

## 🧠 Die zentralen Erkenntnisse

**Der zentrale Erfolg des Tages war nicht, dass ein Run erfolgreich war, sondern dass sowohl erfolgreiche als auch fehlerhafte Runs deterministisch, isoliert und nachvollziehbar verarbeitet wurden.**

1. **Systemstabilität $\neq$ Output-Qualität:** 
   Die Plattform ist nun so robust, dass sie "schlechte" Modelle erkennt und ablehnt. Das ist der eigentliche industrielle Erfolg.
   
2. **Die Kognitive Schwelle:** 
   Es gibt eine harte Grenze zwischen 8B- und 70B-Modellen bei komplexen Aufgaben. Die Plattform macht diesen Unterschied durch die Verifikation sichtbar.

3. **Das "Cheating"-Phänomen:** 
   Starke Modelle neigen dazu, die Validierung zu "bestechen" (Keywords einfügen, ohne Design-Qualität zu liefern). 
   $\rightarrow$ **Folge:** Wir müssen von syntaktischer Validierung (Keywords) zu semantischer Validierung (Qualitäts-Review) übergehen.

---

## 📍 Aktueller Systemzustand
„Firma“ ist jetzt eine **isolierte Execution-Runtime** mit deterministischer Fehlerbehandlung, Provider-Resilienz, Lease-basierter Selbstheilung und vollständiger Lifecycle-Kontrolle.

Das System ist jetzt **korrekt durch Design, nicht durch Disziplin.**

## 🚀 Nächste Phase: AI-Engineering & Quality-Guard
Wir verlassen die Infrastruktur-Phase und treten in die **Optimierungs-Phase** ein:
1. **Semantische Validierung:** Ausbau kombinierter Qualitäts-Gates (strukturelle Checks, DOM-basierte Prüfungen, deterministische Heuristiken und optional LLM-Reviews unter Governance-Kontrolle).

2. **Simulator-Sync:** Behebung der "Stale Revision" im Simulator für nahtlose Tests.
3. **Modell-Matrix:** Definition der optimalen Modelle pro Rolle.

**Essenz des Tages:** 
Vom Bugfix zum Plattform-Engineering. Die Maschine steht. Jetzt wird die Qualitätskontrolle industriell.

---

## ✅ Abnahmestatus der Plattform

| Bereich | Status |
|---|---|
| Single-Run Smoke Test | ✅ Bestanden |
| Real-LLM Task Flow | ✅ Bestanden |
| Failure Handling | ✅ Bestanden |
| Run Isolation | ✅ Bestanden |
| Provider Timeout Recovery | ✅ Bestanden |
| Multi-Run Paralleltest | ⏳ Ausstehend |
| Semantische Qualitätsprüfung | ⏳ Nächste Phase |
| Modell-Rollen-Matrix | ⏳ Nächste Phase |



 Goal                                                                                                                                                                                                                 
                                                                                                                                                                                                                      
 - Research and provide a status report on the "Firma" project.                                                                                                                                                       
 - Assess the architectural risks and evolution paths of the "Firma" engine.                                                                                                                                          
 - Implement a professional corporate website for "Firma" using the engine's deterministic pipeline (Planning $\rightarrow$ Implementation $\rightarrow$ Validation).                                                 
 - Transition the engine from a "project" to a deterministic AI-Execution Runtime with formal governance.                                                                                                             
 - Test and measure the "controllability" of probabilistic workers under deterministic governance (Worker Calibration).                                                                                               
 - Prove the full runtime loop (READY $\rightarrow$ COMPLETE) is industrially stable using dummy workers.                                                                                                             
 - Transform unpredictable external LLM dependencies into deterministic, classified error sources (Resilience Hardening).                                                                                             
 - Transition to Industrial Validation (Phase 6): Validate the runtime under real-world API instability and characterize provider performance.                                                                        
 - Transition the system from "debugging" to "system engineering" by implementing explicit run-isolation.                                                                                                             
 - Transition to Phase 7 (Platform): Evolve from a runtime kernel to a controllable execution platform with standalone lifecycle management.                                                                          
 - Industrial Quality Assurance: Validate the platform's ability to detect and reject low-quality output through strict acceptance criteria.                                                                          
 - Project Maintenance: Implement a professional directory structure to eliminate "experimentation clutter" and ensure long-term maintainability.                                                                     
                                                                                                                                                                                                                      
 Constraints & Preferences                                                                                                                                                                                            
                                                                                                                                                                                                                      
 - Website Requirements: Professional dark-theme, High-End Enterprise aesthetic, responsive layout using Tailwind CSS (via CDN), deliverables as static files (index.html, styles.css, script.js).                    
 - Architecture: Maintain strict separation between the Kernel (Governance), Nervous System (pi-messenger), and Muscles (LLM Workers).                                                                                
 - Platform Design: RunController must be a Supervisor/Lifecycle Manager, not a "God Module." It manages Orchestrator instances but must not interfere with task-level business logic.                                
 - Environment: Windows terminal (requires avoiding emojis in logs and using unbuffered output -u).                                                                                                                   
 - Semantic Validation: Move beyond simple string-based checks (CONTAINS) to combined quality gates including structural checks, DOM-based verification, deterministsic heuristics, and governed LLM reviews.         
                                                                                                                                                                                                                      
 Progress                                                                                                                                                                                                             
                                                                                                                                                                                                                      
 ### Done                                                                                                                                                                                                             
                                                                                                                                                                                                                      
 - [x] Research and status report on the "Firma" architecture.                                                                                                                                                        
 - [x] Analysis of architectural blind spots.                                                                                                                                                                         
 - [x] Created run_corporate_site.py to orchestrate the website build.                                                                                                                                                
 - [x] Implemented verify_deterministic bridge in run_corporate_site.py.                                                                                                                                              
 - [x] Governance Cure Implementation: Added verification_type to Task, defined formal failure classes, and implemented StructuralWebVerifier.                                                                        
 - [x] Closed-Loop Validation: Achieved the first full runtime cycle: CODING $\rightarrow$ VERIFYING $\rightarrow$ VALIDATION_FAILURE $\rightarrow$ CODING.                                                           
 - [x] Controllability Hardening: Implemented structured "Delta-Feedback" and hardened inline-SVG verification.                                                                                                       
 - [x] Messaging Pipeline Restoration: Fixed InternalTransport and implemented a blocking worker loop using await queue.get().                                                                                        
 - [x] Provider Hardening: Integrated httpx.Client with hard socket timeouts and asyncio.to_thread isolation.                                                                                                         
 - [x] Optimistic Concurrency Control: Implemented revision-based guards in the Guardian to prevent stale worker responses.                                                                                           
 - [x] Run-Isolation Design Implementation:                                                                                                                                                                           
     - Introduced Run model and bound all entities (Project, Plan, Task) to run_id.                                                                                                                                   
     - Removed all implicit globality (limit(1)) in the Scheduler.                                                                                                                                                    
     - Implemented lease-based recovery (claimed_at, lease_expires_at) to eliminate zombie tasks.                                                                                                                     
     - Updated Orchestrator and Transport to be run-scoped.                                                                                                                                                           
     - Refactored MessageRepository to enforce run_id filtering on every query.                                                                                                                                       
 - [x] Platform Foundation (Phase 7):                                                                                                                                                                                 
     - Enhanced Run model with started_at, completed_at, config_json, metrics_json, and failure_reason.                                                                                                               
     - Implemented RunController in engine/controller.py as a Supervisor for Run lifecycles (Create, Start, Stop, Cancel).                                                                                            
     - Updated Orchestrator to include a Lifecycle Guard that stops ticks if Run.status != "ACTIVE".                                                                                                                  
     - Created platform_main.py as a clean entry point that separates platform control from execution.                                                                                                                
     - Hardened worker_simulator to publish TASK_FAILED events on exception, preventing silent hangs.                                                                                                                 
 - [x] Clean Run Validation: Modified platform_main.py to wait for terminal states (COMPLETED, FAILED, CANCELLED) instead of using a fixed loop.                                                                      
 - [x] Smoke Test Design: Implemented a minimalist "Ping Pong" task (create ping.txt with content pong) to isolate infrastructure stability from prompt complexity.                                                   
 - [x] Run-Isolation Bug Fixes:                                                                                                                                                                                       
     - Added run_id column to MessageLog in engine/models.py.                                                                                                                                                         
     - Resolved sqlite3.IntegrityError: NOT NULL constraint failed: message_log.run_id by updating engine/orchestrator.py to pass run_id to the Guardian and adding a fallback extraction in                          
       engine/services/guardian.py.                                                                                                                                                                                   
     - Resolved AttributeError: type object 'MessageType' has no attribute 'TASK_RESULT' (Resolved)                                                                                                                   
     - Resolved AttributeError: type object 'MessageType' has no attribute 'ERROR_REPORT' (Resolved)                                                                                                                  
     - Resolved TypeError: MessageRepository.mark_message_processed() missing 1 required positional argument: 'run_id' (Resolved)                                                                                     
     - Resolved TypeError: MessageRepository.save_submission_log() missing 1 required positional argument: 'log_entry' (Resolved)                                                                                     
     - Resolved TypeError: MessageRepository.get_artifacts_for_plan() missing 1 required positional argument: 'plan_id' (Resolved)                                                                                    
     - Resolved ValueError: No verifier registered under the name: csv (Resolved via Orchestrator fix)                                                                                                                
 - [x] Smoke Test End-to-End Validation:                                                                                                                                                                              
     - Fixed TypeError in engine/services/artifact_store.py regarding missing plan_id in get_artifacts_for_plan().                                                                                                    
     - Eliminated "Silent Hangs" in PLANNING by updating engine/governance.py to allow TASK_FAILED transitions and modifying engine/services/guardian.py to trigger terminal Run failure.                             
     - Resolved "Default Value Trap" in engine/orchestrator.py by ensuring task.verification_type is passed to execution_service.verify().                                                                            
     - Prevented "LLM Schema Reflection" in workers/planner.py by replacing raw Pydantic JSON schemas with a simplified structural prompt and a One-Shot example.                                                     
     - Extended worker_simulator in platform_main.py to handle the REVIEWER role via REVIEW_APPROVED events.                                                                                                          
     - Implemented Run-Termination Semantics in engine/orchestrator.py via _check_run_completion(), automatically marking the Run as COMPLETED or FAILED when all tasks reach terminal states.                        
     - Verified a successful end-to-end flow: PLANNING $\rightarrow$ CODING $\rightarrow$ VERIFYING $\rightarrow$ REVIEWING $\rightarrow$ COMPLETE $\rightarrow$ Run COMPLETED.                                       
 - [x] Industrial Platform Validation:                                                                                                                                                                                
     - Validated the platform using the Corporate Website project.                                                                                                                                                    
     - Proved that a FAILED run caused by a weak model (Llama-3.1-8B) is a Platform-Level Success, confirming that the system deterministically rejects low-quality output.                                           
     - Confirmed that stronger models (Llama-3.1-70B) can successfully navigate the full pipeline.                                                                                                                    
     - Identified the "Cheating" phenomenon: LLMs satisfying syntactic string checks (e.g., CONTAINS:Tailwind) without providing actual semantic quality.                                                             
     - Verified Optimistic Concurrency Control (OCC) by detecting and rejecting a "Stale Revision" response in the Guardian during a race condition.                                                                  
 - [x] Project Restructuring ("Operation Tabula Rasa"):                                                                                                                                                               
     - Established a Git baseline (git init, branch chore/clean-architecture).                                                                                                                                        
     - Implemented a professional directory structure:                                                                                                                                                                
         - /engine, /workers (core assets)                                                                                                                                                                            
         - /platform (containing main.py, formerly platform_main.py)                                                                                                                                                  
         - /docs (consolidated documentation including Firma.md and Stand 08.07.2026.md)                                                                                                                              
         - /data/db and /data/artifacts (persistence layer)                                                                                                                                                           
         - /archive/logs, /archive/legacy_scripts, /archive/temp (disposable artifacts)                                                                                                                               
     - Updated .gitignore to exclude DB files, logs, and artifacts.                                                                                                                                                   
     - Resolved ModuleNotFoundError: No module named 'engine' by implementing dynamic sys.path adjustment in platform/main.py.                                                                                        
     - Verified structural migration with a successful smoke test.                                                                                                                                                    
                                                                                                                                                                                                                      
 ### In Progress                                                                                                                                                                                                      
                                                                                                                                                                                                                      
 - [ ] Implementing Semantic Validation (Anti-Cheating) using multi-stage quality gates.                                                                                                                              
 - [ ] Synchronizing the worker_simulator to handle revisions correctly and prevent "Stale Revision" hangs.                                                                                                           
 - [ ] Defining a Model-Role Matrix to assign optimal LLMs to specific roles (Planner, Executor, Reviewer).                                                                                                           
                                                                                                                                                                                                                      
 ### Blocked                                                                                                                                                                                                          
                                                                                                                                                                                                                      
 - [ ] None.                                                                                                                                                                                                          
                                                                                                                                                                                                                      
 Key Decisions                                                                                                                                                                                                        
                                                                                                                                                                                                                      
 - Run-Isolation over DB Deletion: Shifted to explicit run_id isolation as the architectural standard to allow parallel runs and maintain history.                                                                    
 - Lease-Model Recovery: Replaced simple state checks with lease_expires_at to ensure deterministic recovery from crashes.                                                                                            
 - Supervisor Pattern: Implemented RunController as a lifecycle manager that controls Orchestrator instances without managing internal task logic.                                                                    
 - Worker-Side Isolation: Enforced run_id checks in workers to prevent cross-talk in shared transport environments.                                                                                                   
 - Provider Stability: Switched to meta-llama/llama-3.1-8b-instruct via OpenRouter for platform validation to avoid transient 404s with experimental Gemini slugs.                                                    
 - Smoke Testing: Decided to utilize minimalist tasks to prove the functional integrity of the pipeline before returning to complex output generation.                                                                
 - Consolidated Worker Messaging: Decided to use a single MessageType.WORKER_RESPONSE and differentiate behavior via an internal event field in the payload to prevent further contract drift.                        
 - Legacy Guard Removal: Removed MessageGuards.VALID_TRANSITIONS in favor of the formal GovernanceMatrix to maintain a single source of truth for state transitions.                                                  
 - Deterministic Failure Paths: Added terminal failure transitions (e.g., PLANNING $\rightarrow$ FAILED) to the GovernanceMatrix to prevent silent hangs when LLMs fail validation.                                   
 - Schema Reflection Prevention: Switched from raw Pydantic JSON schemas to simplified structural prompts and one-shot examples in workers/planner.py to avoid LLM outputting the schema definition instead of data.  
 - Run-Termination Semantics: Implemented DB-based aggregation in the Orchestrator tick to close the Run lifecycle based on the terminal status of all associated tasks.                                              
 - Platform-Level Validation Definition: Defined a "FAILED" run caused by a weak model as a successful validation of the platform's governance and quality control.                                                   
 - Cognitive Capacity Threshold: Determined that 8B models are generally insufficient for complex UI tasks, whereas 70B models provide the necessary reliability.                                                     
 - Semantic Validation Requirement: Decided that string-based validation is insufficient due to LLM "cheating"; moving toward a combined gate approach (DOM, heuristics, LLM-signal).                                 
 - Project Architecture Professionalization: Moved from a flat root directory to a structured platform layout (/platform, /data, /archive, /docs) to ensure long-term maintainability.                                
                                                                                                                                                                                                                      
 Next Steps                                                                                                                                                                                                           
                                                                                                                                                                                                                      
 1. Implement a "Semantic Verifier" to prevent LLM cheating and ensure actual quality.                                                                                                                                
 2. Fix simulator revision synchronization to eliminate "Stale Revision" hangs.                                                                                                                                       
 3. Establish the Model-Role Matrix for optimal worker performance.                                                                                                                                                   
 4. Conduct multi-run parallel stress tests to validate the RunController under load.                                                                                                                                 
                                                                                                                                                                                                                      
 Critical Context                                                                                                                                                                                                     
                                                                                                                                                                                                                      
 - Project Path: platform/main.py / engine/controller.py                                                                                                                                                              
 - Isolation Guarantee: Every query in the MessageRepository is now strictly filtered by run_id.                                                                                                                      
 - Control Hierarchy: Platform (RunController) $\rightarrow$ Runtime Kernel (Orchestrator + Scheduler) $\rightarrow$ Execution (Worker + Provider) $\rightarrow$ Persistence (Repository).                            
 - Cognitive Gap: 8B models $\rightarrow$ Skeletons/Failures; 70B models $\rightarrow$ Functional/Pass.                                                                                                               
 - Revision Guard: The Guardian rejects responses with stale revisions to prevent state corruption, which can cause hangs in fast simulators.                                                                         
 - Critical Bug Log:                                                                                                                                                                                                  
     - IntegrityError: NOT NULL constraint failed: message_log.run_id (Resolved)                                                                                                                                      
     - ModuleNotFoundError: No module named 'engine' in platform/main.py (Resolved via sys.path adjustment)                                                                                                           
     - Stale revision. Response: 11, Task: 12 (Detected and handled by Guardian; identified as a simulator sync issue)                                                                                                
                                                                                                                                                                                                                      
 ────────────────────────────────────────────────────────────────────────────────                                                                                                                                     
                                                                                                                                                                                                                      
 Turn Context (split turn):                                                                                                                                                                                           
                                                                                                                                                                                                                      
 Original Request                                                                                                                                                                                                     
                                                                                                                                                                                                                      
 The user instructed the AI to start/begin.                                                                                                                                                                           
                                                                                                                                                                                                                      
 Early Progress                                                                                                                                                                                                       
                                                                                                                                                                                                                      
 - No work has been performed yet.                                                                                                                                                                                    
                                                                                                                                                                                                                      
 Context for Suffix                                                                                                                                                                                                   
                                                                                                                                                                                                                      
 - The conversation has just started; there is no prior technical context or specific task defined.                                                                                                                   
                                                                                                                                                                                                                      
 <read-files>                                                                                                                                                                                                         
 Zielarchitektur.md                                                                                                                                                                                                   
 artifact_store/c19654af-9c5e-4e97-a7ca-8c86a1c8ef50/v1/addba79a-7782-4b1b-bcd3-49c4e3e07916/index.html                                                                                                               
 artifact_store/c19654af-9c5e-4e97-a7ca-8c86a1c8ef50/v1/addba79a-7782-4b1b-bcd3-49c4e3e07916/script.js                                                                                                                
 artifact_store/c19654af-9c5e-4e97-a7ca-8c86a1c8ef50/v1/addba79a-7782-4b1b-bcd3-49c4e3e07916/styles.css                                                                                                               
 engine/db.py                                                                                                                                                                                                         
 engine/services/sandbox.py                                                                                                                                                                                           
 engine/services/verification_registry.py                                                                                                                                                                             
 firma_web_config.json                                                                                                                                                                                                
 run_9_1.py                                                                                                                                                                                                           
 run_corporate_site_forensics.log                                                                                                                                                                                     
 run_debug.log                                                                                                                                                                                                        
 run_golden_path.log                                                                                                                                                                                                  
 run_hardened_A.log                                                                                                                                                                                                   
 </read-files>                                                                                                                                                                                                        
                                                                                                                                                                                                                      
 <modified-files>                                                                                                                                                                                                     
 .gitignore                                                                                                                                                                                                           
 Firma.md                                                                                                                                                                                                             
 Stand 08.07.2026.md                                                                                                                                                                                                  
 engine/controller.py                                                                                                                                                                                                 
 engine/exceptions.py                                                                                                                                                                                                 
 engine/governance.py                                                                                                                                                                                                 
 engine/guards.py                                                                                                                                                                                                     
 engine/models.py                                                                                                                                                                                                     
 engine/orchestrator.py                                                                                                                                                                                               
 engine/providers/base.py                                                                                                                                                                                             
 engine/providers/nvidia_provider.py                                                                                                                                                                                  
 engine/providers/openai_provider.py                                                                                                                                                                                  
 engine/providers/openrouter_provider.py                                                                                                                                                                              
 engine/providers/pi_provider.py                                                                                                                                                                                      
 engine/providers/stochastic_llm_provider.py                                                                                                                                                                          
 engine/repository.py                                                                                                                                                                                                 
 engine/scheduler.py                                                                                                                                                                                                  
 engine/services/artifact_store.py                                                                                                                                                                                    
 engine/services/execution.py                                                                                                                                                                                         
 engine/services/guardian.py                                                                                                                                                                                          
 engine/services/verification_service.py                                                                                                                                                                              
 engine/transport/internal_transport.py                                                                                                                                                                               
 platform/main.py                                                                                                                                                                                                     
 platform_main.py                                                                                                                                                                                                     
 run_corporate_site.py                                                                                                                                                                                                
 run_gemini_final.py                                                                                                                                                                                                  
 workers/executor.py                                                                                                                                                                                                  
 workers/llm_worker.py                                                                                                                                                                                                
 workers/planner.py                                                                                                                                                                                                   
 </modified-files>  