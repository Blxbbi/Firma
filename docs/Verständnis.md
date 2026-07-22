 Was du baust: "Firma" – Eine deterministische AI-Execution-Engine                                          
                                                                                                            
 Das ist kein typisches Multi-Agent-Chat-Projekt. Du baust eine Infrastruktur-Maschine, die AI-Worker wie   
 austauschbare "Muskeln" steuert. Das "Gehirn" ist nicht GPT, sondern deine Engine.                         
                                                                                                            
 ────────────────────────────────────────────────────────────────────────────────                           
                                                                                                            
 Meine Verständnis-Übersicht                                                                                
                                                                                                            
 ### 🧩 Kernidee & Philosophie                                                                              
                                                                                                            
 ┌────────────────────────┬───────────────────────────────────────────────────┐                             
 │ Prinzip                │ Umsetzung                                         │                             
 ├────────────────────────┼───────────────────────────────────────────────────┤                             
 │ Determinismus          │ Wahrheit liegt in der Infrastruktur, nicht im LLM │                             
 ├────────────────────────┼───────────────────────────────────────────────────┤                             
 │ Single Source of Truth │ Die Plan Registry ist die "Verfassung"            │                             
 ├────────────────────────┼───────────────────────────────────────────────────┤                             
 │ Agenten = Worker       │ LLMs treffen keine Statusentscheidungen           │                             
 ├────────────────────────┼───────────────────────────────────────────────────┤                             
 │ 3-Level-Validation     │ Struktur → Statische Analyse → Runtime-Sandbox    │                             
 └────────────────────────┴───────────────────────────────────────────────────┘                             
                                                                                                            
 ### 🏗️ Architektur-Komponenten                                                                             
                                                                                                            
 ┌────────────────────────────┬───────────────────────────────────────────────────────┬───────────────────┐ 
 │ Komponente                 │ Zuständigkeit                                         │ Status            │ 
 ├────────────────────────────┼───────────────────────────────────────────────────────┼───────────────────┤ 
 │ Plan Registry              │ Speichert versionierte Pläne als JSON mit Tasks,      │ ✅                │ 
 │                            │ Artefakten, Kriterien                                 │                   │ 
 ├────────────────────────────┼───────────────────────────────────────────────────────┼───────────────────┤ 
 │ Execution Engine           │ Herzstück: State Machine, Tick-Loop, Koordination     │ ✅                │ 
 │ (Orchestrator)             │                                                       │                   │ 
 ├────────────────────────────┼───────────────────────────────────────────────────────┼───────────────────┤ 
 │ State Machine              │ Hart kodierte                                         │ ✅                │ 
 │ (GovernanceMatrix)         │ Phase-&rarr;Rollen-&rgt;Event-Transitions             │                   │ 
 ├────────────────────────────┼───────────────────────────────────────────────────────┼───────────────────┤ 
 │ Artifact Store             │ SHA256-gesicherte Dateiablage pro Plan-Version        │ ✅                │ 
 ├────────────────────────────┼───────────────────────────────────────────────────────┼───────────────────┤ 
 │ Guardian Pipeline          │ 8-Step-Validation: Transport → Schema → Idempotenz →  │ ✅                │ 
 │                            │ FSM → CAS-Commit                                      │                   │ 
 ├────────────────────────────┼───────────────────────────────────────────────────────┼───────────────────┤ 
 │ Sandbox                    │ Lokale Subprocess-Isolation für Code-Execution        │ ✅ (Mock/Simple   │ 
 │                            │                                                       │ local)            │ 
 ├────────────────────────────┼───────────────────────────────────────────────────────┼───────────────────┤ 
 │ Message Repository         │ Atomic-CAS-Operations, Pessimistic Locking, Session   │ ✅                │ 
 │                            │ Scoping                                               │                   │ 
 ├────────────────────────────┼───────────────────────────────────────────────────────┼───────────────────┤ 
 │ Spec Gate                  │ Zyklus-Check, Rollen-Validierung, Schema-Verifikation │ ✅                │ 
 ├────────────────────────────┼───────────────────────────────────────────────────────┼───────────────────┤ 
 │ pi-messenger Integration   │ Transport für Worker-Task-Aufgaben                    │ ✅                │ 
 └────────────────────────────┴───────────────────────────────────────────────────────┴───────────────────┘ 
                                                                                                            
 ### 🔄 Ablauf (Beispiel)                                                                                   
                                                                                                            
 ```                                                                                                        
   User: "Bau OAuth-Login"                                                                                  
      │                                                                                                     
      ▼                                                                                                     
   ┌─────────────┐                                                                                          
   │ PLANNER LLM │  → Plan Registry ← die Wahrheit                                                          
   └──────┬──────┘                                                                                          
          ▼                                                                                                 
   ┌─────────────┐                                                                                          
   │ Orchestrator│  (Tick every 500ms)                                                                      
   └──────┬──────┘                                                                                          
          ▼                                                                                                 
      ┌────────┐                                                                                            
      │ TASK T1│ → READY → CLAIMED → IN_PROGRESS                                                            
      └────────┘          ↓                                                                                 
                 ┌─────────────┐                                                                            
                 │ CODER LLM   │ → arbeitet → SUBMITTED                                                     
                 └──────┬──────┘                                                                            
                        ▼                                                                                   
                 ┌─────────────┐                                                                            
                 │ Guardian    │ ← Strukturprüfung → Static Analysis → Sandbox                              
                 └──────┬──────┘                     → Exit-Code, Tests                                     
                        ▼                                                                                   
                 ┌─────────────┐                                                                            
                 │ VERIFIED/FAIL│ ❌Back to READY oder ✅COMPLETE                                           
                 └─────────────┘                                                                            
 ```                                                                                                        
                                                                                                            
 ────────────────────────────────────────────────────────────────────────────────                           
                                                                                                            
 🎯 Besonders Starker Design-Aspect                                                                         
                                                                                                            
 ### Die 9-Step Guardian Pipeline (guardian.py)                                                             
                                                                                                            
 Das ist die Kern-Defensivlinie:                                                                            
                                                                                                            
 1. Transport-Level-Validation                                                                              
 2. Schema-Validation (Pydantic WorkerResponse)                                                             
 3. Task-Existenz-Check                                                                                     
 4. Terminal-State-Check                                                                                    
 5. Idempotenz-Check (Read-Only)                                                                            
 6. Optimistic Concurrency (Revision Match)                                                                 
 7. Role-Event-Authorization (GovernanceMatrix)                                                             
 8. FSM-Transition-Validation                                                                               
 9. Atomic Commit (CAS + Persistence + Message-Log)                                                         
                                                                                                            
 │ "The actual write happens AFTER the CAS to ensure CAS is the first write." — Klare Read-Modify-Write     
 │ Isolation.                                                                                               
                                                                                                            
 ### GovernanceMatrix (governance.py)                                                                       
                                                                                                            
 Der FSM ist hässlich hart codiert — genau richtig für deterministische Prozesskontrolle:                   
                                                                                                            
 ┌─────────────┬────────────────────────────────┬───────────────┐                                           
 │ Phase       │ Erlaubte Events                │ Rollen-Rechte │                                           
 ├─────────────┼────────────────────────────────┼───────────────┤                                           
 │ PLANNING    │ PLAN_APPROVED, PLAN_REJECTED   │ PLANNER       │                                           
 ├─────────────┼────────────────────────────────┼───────────────┤                                           
 │ RESEARCHING │ RESEARCH_COMPLETE, TASK_FAILED │ RESEARCHER    │                                           
 ├─────────────┼────────────────────────────────┼───────────────┤                                           
 │ CODING      │ CODE_SUBMITTED, TASK_FAILED    │ CODER         │                                           
 ├─────────────┼────────────────────────────────┼───────────────┤                                           
 │ VERIFYING   │ VERIFY_SUCCESS, VERIFY_FAILURE │ SYSTEM        │                                           
 ├─────────────┼────────────────────────────────┼───────────────┤                                           
 │ REVIEWING   │ REVIEW_SUCCESS, REVIEW_FAILURE │ REVIEWER      │                                           
 ├─────────────┼────────────────────────────────┼───────────────┤                                           
 │ COMPLETE    │ (Terminal)                     │ —             │                                           
 └─────────────┴────────────────────────────────┴───────────────┘                                           
                                                                                                            
 ### Spec Gate (services/spec_gate.py)                                                                      
                                                                                                            
 Validiert Plausibilität, bevor die Engine akzeptiert:                                                      
 - Duplikate Task-IDs                                                                                       
 - Zyklische Dependencies (DFS-Check)                                                                       
 - Ungültige Rollen                                                                                         
                                                                                                            
 ────────────────────────────────────────────────────────────────────────────────                           
                                                                                                            
 🐛 Was ich kritisch sehe / Auffälligkeiten                                                                 
                                                                                                            
 ### 1. Sandbox ist nur "LocalSandbox"                                                                      
                                                                                                            
 Die ambitionierten Level-3-Sandbox-Pläne (gVisor, Firecracker, Docker-Netzwerk-Isolation) aus              
 Statemaschine + Datenbank.md sind nicht implementiert. Aktuell einfacher subprocess.run() in einem lokalen 
 Verzeichnis. Das ist das größte Sicherheitsloch im aktuellem Code.                                         
                                                                                                            
 ### 2. Worker sind aktuell "Simulated"                                                                     
                                                                                                            
 - LocalWorkerBridge simuliert Worker-Antworten lokal                                                       
 - mock_worker.py existiert                                                                                 
 - Keine echten externen LLM-Worker zurückrufe                                                              
 - pi_worker_minimal.py scheint ein Ansatz zu sein                                                          
                                                                                                            
 ### 3. DB-Chaos:                                                                                           
                                                                                                            
 Tonnen temporärer .db-Dateien (firmenfirmenfirmenfirma.db, test_persistence_*.db, mesh_*.db). Das          
 projekt-reife Vorgehen wäre: Ein .gitignore für SQLite und konsistente Datenbank-Nutzung.                  
                                                                                                            
 ### 4. Viele Tests, aber keine pytest-Integration:                                                         
                                                                                                            
 ```                                                                                                        
   test_embedded_mesh.py                                                                                    
   test_mesh_run.py                                                                                         
   test_spec_gate.py                                                                                        
   test_governance.py                                                                                       
 ```                                                                                                        
                                                                                                            
 Die Tests sind quasi Standalone-Skripte, kein pytest-Runner. Das ist unpraktisch für CI/CD.                
                                                                                                            
 ### 5. Code-Duplikation                                                                                    
                                                                                                            
 ExecutionService vs worker_bridge.py — beide managen die Ausführung. GuardianPipeline und Workflow-Aufrufe 
 haben überlappende Verantwortlichkeiten.                                                                   
                                                                                                            
 ### 6. imports:                                                                                            
                                                                                                            
 Ein paar ungenutzte / fehlende imports — z.B. Set in governance.py importiert, wird nicht genutzt (well,   
 Set is genutzt in _role_auth, aber from typing import ... ist da). Linter-Warnings.                        
                                                                                                            
 ────────────────────────────────────────────────────────────────────────────────                           
                                                                                                            
 💡 Mein Fazit                                                                                              
                                                                                                            
 ┌─────────────────────┬──────────────────────────────────────────────────────────────┐                     
 │ Metrik              │ Bewertung                                                    │                     
 ├─────────────────────┼──────────────────────────────────────────────────────────────┤                     
 │ Vision              │ ⭐⭐⭐⭐⭐ Extrem klare, richtige Richtung                   │                     
 ├─────────────────────┼──────────────────────────────────────────────────────────────┤                     
 │ Architektur         │ ⭐⭐⭐⭐⭐ Solide, separation of concerns, atomic operations │                     
 ├─────────────────────┼──────────────────────────────────────────────────────────────┤                     
 │ Determinismus       │ ⭐⭐⭐⭐☆ GovernanceMatrix + CAS atomic commits              │                     
 ├─────────────────────┼──────────────────────────────────────────────────────────────┤                     
 │ Execution (Sandbox) │ ⭐⭐☆☆☆ Lokales subprocess, keine Echt-Isolation             │                     
 ├─────────────────────┼──────────────────────────────────────────────────────────────┤                     
 │ Reife               │ ⭐⭐⭐☆☆ MVP-Phase, viel Tests/Chaos                         │                     
 └─────────────────────┴──────────────────────────────────────────────────────────────┘                     
                                                                                                            
 Das Kernkonzept (Determinismus durch Infrastrukur, nicht durch das LLM) ist fundamental richtig und        
 überlegt. Die drei wichtigsten Verbesserungen wären:                                                       
                                                                                                            
 1. Echte Sandbox (Docker/gVisor) implementieren                                                            
 2. LLM-Provider-Integration vollenden (OpenAI/Claude/Local als Worker-Module)                              
 3. Tests formalisieren (pytest, fixtures, CI-Runner)                      