 Um den Prozess der Firma-Engine zu verstehen, müssen wir sie nicht als bloßes Programm,        
 sondern als biologisch-mechanisches System betrachten. Die Engine trennt strikt zwischen dem   
 Denken (Strategie), dem Prüfen (Gesetz) und dem Tun (Muskeln).                                 
                                                                                                
 Hier ist das industrielle Fließschema der Firma-Engine.                                        
                                                                                                
 ────────────────────────────────────────────────────────────────────────────────               
                                                                                                
 🏗 Die Anatomie der Firma-Engine                                                                
                                                                                                
 Ich unterteile das System in vier funktionale Layer, die zusammen die "Cognitive Loop" bilden. 
                                                                                                
 1. Das Gehirn (The Cerebral Cortex) – Strategie & Steuerung                                    
                                                                                                
 Hier wird entschieden, WAS getan werden muss und WIE der Weg dorthin aussieht.                 
                                                                                                
 - Der Orchestrator (Das Bewusstsein): Er ist der Dirigent. Er kennt den aktuellen Zustand des  
   Projekts und weiß, in welcher Phase (PLANNING, CODING, VERIFYING) wir uns befinden. Er       
   steuert die Übergänge.                                                                       
 - Der Planner (Der Stratege): Ein spezialisiertes LLM. Er erhält die User-Anfrage und zerlegt  
   sie in eine deterministische Liste von Tasks. Er liefert nicht den Code, sondern die         
   Bauanleitung.                                                                                
                                                                                                
 2. Das Nervensystem (The Peripheral Nervous System) – Transport & Zuweisung                    
                                                                                                
 Die Schnittstellen, die Signale vom Gehirn zu den Muskeln leiten.                              
                                                                                                
 - Der Scheduler (Der Dispatcher): Er scannt die Datenbank nach "READY"-Tasks und weist sie     
   einem verfügbaren Worker zu.                                                                 
 - Der Internal Transport (Die Synapsen): Die technische Pipeline, die Nachrichten              
   (TASK_ASSIGNMENT) an die Worker schickt und Antworten (WORKER_RESPONSE) zurücknimmt.         
                                                                                                
 3. Die Muskeln (The Motor Cortex) – Ausführung                                                 
                                                                                                
 Hier findet die eigentliche Arbeit statt. Hier wird "geschwitzt".                              
                                                                                                
 - Der Executor / Coder (Der Handwerker): Ein LLM, das strikt nach dem Plan des Strategen       
   arbeitet. Er schreibt den Code und paketiert ihn als Artefakte.                              
 - Der Artifact Store (Das Lager): Ein sicheres Archiv, in dem jede Dateiversion versioniert    
   abgelegt wird. Nichts wird "einfach so" überschrieben; alles ist rückverfolgbar.             
                                                                                                
 4. Das Immunsystem (The Frontal Lobe) – Governance & Validierung                               
                                                                                                
 Das wichtigste Modul. Es verhindert, dass das System halluziniert oder instabil wird.          
                                                                                                
 - Der Guardian (Der Gesetzgeber): Jede Nachricht, die von den Muskeln kommt, muss durch den    
   Guardian. Er prüft: Entspricht die Antwort dem JSON-Schema? Ist die Aktion erlaubt? Wenn der 
   Guardian "Nein" sagt, wird die Antwort verworfen, bevor sie das Gehirn erreicht.             
 - Die Sandbox (Das Prüffeld): Eine isolierte Umgebung, in der der Code tatsächlich ausgeführt  
   wird. Hier wird die Theorie der Realität gegenübergestellt.                                  
 - Der Verification Service (Der Richter): Er analysiert das Ergebnis der Sandbox (Exit-Codes,  
   Logs) und entscheidet: VERIFY_SUCCESS oder VERIFY_FAILURE.                                   
                                                                                                
 ────────────────────────────────────────────────────────────────────────────────               
                                                                                                
 🔄 Das Fließschema (The Pipeline)                                                              
                                                                                                
 So sieht ein kompletter Durchlauf aus:                                                         
                                                                                                
 ### Phase A: Die Intent-Phase (User $\rightarrow$ Strategie)                                   
                                                                                                
 1. User-Prompt $\rightarrow$ wird in den Orchestrator eingespeist.                             
 2. Orchestrator setzt Status auf PLANNING.                                                     
 3. Scheduler weist den Planner zu.                                                             
 4. Planner $\rightarrow$ erstellt einen Plan (JSON).                                           
 5. Guardian $\rightarrow$ validiert das Plan-Schema $\rightarrow$ PLAN_APPROVED.               
                                                                                                
 ### Phase B: Die Implementierungs-Phase (Strategie $\rightarrow$ Muskel)                       
                                                                                                
 6. Orchestrator wechselt zu CODING.                                                            
 7. Scheduler weist den Executor (Coder) zu.                                                    
 8. Executor $\rightarrow$ schreibt Code basierend auf dem Plan $\rightarrow$ sendet Artefakte. 
 9. Guardian $\rightarrow$ prüft Artefakt-Kontrakt $\rightarrow$ CODE_SUBMITTED.                
 10. Artifact Store $\rightarrow$ speichert die Datei physisch ab.                              
                                                                                                
 ### Phase C: Die Realitäts-Phase (Muskel $\rightarrow$ Prüfung)                                
                                                                                                
 11. Orchestrator wechselt zu VERIFYING.                                                        
 12. Verification Service $\rightarrow$ triggert die Sandbox.                                   
 13. Sandbox $\rightarrow$ führt den Code aus $\rightarrow$ liefert Logs/Exit-Code.             
 14. Verification Service $\rightarrow$ bewertet das Ergebnis.                                  
                                                                                                
 ### Phase D: Die Konvergenz-Phase (Prüfung $\rightarrow$ Loop)                                 
                                                                                                
 - Szenario 1 (Erfolg): $\rightarrow$ VERIFY_SUCCESS $\rightarrow$ Projekt beendet ✅.          
 - Szenario 2 (Fehler): $\rightarrow$ VERIFY_FAILURE $\rightarrow$ Der Fehler-Log wird als      
   Feedback an den Executor zurückgeschickt $\rightarrow$ Zurück zu Phase B.                    
                                                                                                
 ────────────────────────────────────────────────────────────────────────────────               
                                                                                                
 📊 Zusammenfassung der Schnittstellen                                                          
                                                                                                
 ┌───────────────┬──────────────┬───────────────────────┬─────────────────────────────────────┐ 
 │ Von           │ Nach         │ Signal /              │ Zweck                               │ 
 │               │              │ Schnittstelle         │                                     │ 
 ├───────────────┼──────────────┼───────────────────────┼─────────────────────────────────────┤ 
 │ User          │ Orchestrator │ UserPrompt            │ Startet den Prozess                 │ 
 ├───────────────┼──────────────┼───────────────────────┼─────────────────────────────────────┤ 
 │ Scheduler     │ Worker       │ TASK_ASSIGNMENT       │ "Hier ist dein Auftrag"             │ 
 ├───────────────┼──────────────┼───────────────────────┼─────────────────────────────────────┤ 
 │ Worker        │ Guardian     │ WORKER_RESPONSE       │ "Hier ist meine Arbeit"             │ 
 ├───────────────┼──────────────┼───────────────────────┼─────────────────────────────────────┤ 
 │ Guardian      │ Orchestrator │ TaskEvent             │ "Die Arbeit ist valide / invalide"  │ 
 ├───────────────┼──────────────┼───────────────────────┼─────────────────────────────────────┤ 
 │ Verification  │ Guardian     │ VERIFY_RESULT         │ "Der Code funktioniert /            │ 
 │               │              │                       │ funktioniert nicht"                 │ 
 ├───────────────┼──────────────┼───────────────────────┼─────────────────────────────────────┤ 
 │ ArtifactStore │ Sandbox      │ FileStream            │ "Hier ist die Datei zum Testen"     │ 
 └───────────────┴──────────────┴───────────────────────┴─────────────────────────────────────┘ 
                                                                                                
 Das Besondere an Firma:                                                                        
 Es gibt keinen direkten Weg vom Coder zum Erfolg. Alles muss durch den Guardian und die        
 Sandbox. Das Gehirn vertraut den Muskeln nicht – es vertraut nur der Verifizierung. Das ist    
 das Geheimnis der deterministischen Konvergenz.    




 Hier ist die detaillierte technische Aufschlüsselung:                                          
                                                                                                
 ────────────────────────────────────────────────────────────────────────────────               
                                                                                                
 ### 1. Der Orchestrator: Das Gesetz (Hard-Coded Logic)                                         
                                                                                                
 Der Orchestrator "versteht" in menschlichem Sinne nichts. Er besitzt keine Intuition. Er ist   
 ein Regelwerk.                                                                                 
                                                                                                
 - Wie er funktioniert: Er nutzt eine sogenannte Governance Matrix. Das ist im Grunde eine      
   Tabelle, die sagt: "Wenn der Task im Zustand CODING ist und das Event CODE_SUBMITTED         
   eintrifft $\rightarrow$ ändere den Zustand auf VERIFYING."                                   
 - Warum kein LLM? Wenn der Orchestrator ein LLM wäre, könnte er "entscheiden", die Regeln zu   
   ignorieren oder eine Phase zu überspringen. Das wäre instabil. Indem der Orchestrator hart   
   codiert ist, garantieren wir, dass der Prozess immer dieselben Schritte durchläuft.          
 - Seine Aufgabe: Er überwacht die Datenbank. Er ist der einzige, der das Recht hat, den        
   execution_phase Status eines Tasks zu ändern.                                                
                                                                                                
 ### 2. Die Zuweisung: Wie ein Auftrag zum Worker kommt                                         
                                                                                                
 Die Zuweisung läuft nicht über einen "Anruf", sondern über eine Queue-Logik (Scheduler).       
                                                                                                
 1. Der Scheduler (Der Scanner): Er fragt die Datenbank in einer Endlosschleife: "Gibt es       
    Tasks, die den Status READY haben und noch keinen zugewiesenen Worker?"                     
 2. Die Zuweisung: Wenn er einen findet, schreibt er die ID des Workers in die Datenbank und    
    sendet über den Internal Transport eine Nachricht (TASK_ASSIGNMENT) an den Worker.          
 3. Der Worker: Der Worker (z.B. der Coder) schläft eigentlich. Sobald er die Nachricht         
    empfängt, wacht er auf, liest die Projektdaten und beginnt zu arbeiten.                     
                                                                                                
 ### 3. Die Sandbox: Die Isolationskammer                                                       
                                                                                                
 Die Sandbox ist eine der kritischsten Komponenten. Stell sie dir als einen gläsernen Kasten    
 vor, in dem der Code ausgeführt wird.                                                          
                                                                                                
 - Was sie genau ist: Technisch gesehen ist es ein Wrapper um das Python-Modul subprocess. Sie  
   startet einen eigenen, separaten Prozess auf dem Betriebssystem.                             
 - Was sie macht:                                                                               
     - Isolation: Wenn der Coder ein Programm schreibt, das in einer Endlosschleife landet oder 
       den Speicher sprengt, stürzt nur die Sandbox ab, nicht die Firma-Engine.                 
     - Überwachung: Die Sandbox fängt alles ab, was das Programm ausgibt (stdout) und alle      
       Fehlermeldungen (stderr).                                                                
     - Kontrolle: Sie setzt harte Timeouts. Wenn das Programm länger als X Sekunden braucht     
       $\rightarrow$ KILL.                                                                      
     - Windows-Spezialität: Wie wir vor kurzem gelernt haben, sorgt sie auf Windows dafür, dass 
       .py Dateien mit dem Befehl python main.py gestartet werden, anstatt sie als Binärdatei   
       auszuführen.                                                                             
                                                                                                
 ### 4. Die Verifizierung: Der Richter und die Umleitung                                        
                                                                                                
 Hier passiert die "Magie" der Selbstkorrektur.                                                 
                                                                                                
 Der Ablauf der Verifizierung:                                                                  
 1. Der Verification Service nimmt den Code aus dem Artifact Store.                             
 2. Er schiebt ihn in die Sandbox.                                                              
 3. Er führt ihn aus und schaut auf den Exit-Code:                                              
     - Exit 0: Das Programm ist sauber durchgelaufen.                                           
     - Exit 1 (oder anderes): Das Programm ist abgestürzt.                                      
 4. Die Bewertung: Der Service prüft auch, ob die Ausgabe (Logs) den Anforderungen entspricht.  
                                                                                                
 Die Umleitung (Der Loop):                                                                      
 Wenn die Verifizierung scheitert (VERIFY_FAILURE):                                             
 1. Der Orchestrator sieht das Event und sagt: "Okay, Phase VERIFYING ist gescheitert           
    $\rightarrow$ setze Phase zurück auf CODING".                                               
 2. Der Task wird wieder auf READY gesetzt.                                                     
 3. Der Scheduler weist den Task erneut dem Coder zu.                                           
 4. Der Clou: Der Coder erhält diesmal nicht nur den ursprünglichen Prompt, sondern auch den    
    Error-Log aus der Sandbox.                                                                  
                                                                                                
 Beispiel aus unserem letzten Run:                                                              
 - Coder: Schreibt Code $\rightarrow$ CODE_SUBMITTED.                                           
 - Sandbox: Führt aus $\rightarrow$ TypeError: float() argument must be... $\rightarrow$ Exit   
   1.                                                                                           
 - Orchestrator: "Fehler! Zurück zum Coder!"                                                    
 - Coder: "Oh, ich sehe den TypeError. Ich muss prüfen, ob der Wert None ist." $\rightarrow$    
   korrigiert Code $\rightarrow$ CODE_SUBMITTED.                                                
                                                                                                
 ### Zusammenfassung: Wer macht was?                                                            
                                                                                                
 ┌───────────────┬──────────────┬────────────────────────┬────────────────────────────────┐     
 │ Komponente    │ Natur        │ Rolle                  │ Analogie                       │     
 ├───────────────┼──────────────┼────────────────────────┼────────────────────────────────┤     
 │ Orchestrator  │ Hard Code    │ Überwachung & Status   │ Der Richter / Das Gesetz       │     
 ├───────────────┼──────────────┼────────────────────────┼────────────────────────────────┤     
 │ Planner/Coder │ LLM          │ Kreativität & Lösung   │ Der Architekt / Der Handwerker │     
 ├───────────────┼──────────────┼────────────────────────┼────────────────────────────────┤     
 │ Scheduler     │ Logik        │ Logistik & Zuweisung   │ Der Disponent                  │     
 ├───────────────┼──────────────┼────────────────────────┼────────────────────────────────┤     
 │ Sandbox       │ OS-Prozess   │ Ausführung & Isolation │ Das Testlabor                  │     
 ├───────────────┼──────────────┼────────────────────────┼────────────────────────────────┤     
 │ Guardian      │ Schema-Check │ Validierung & Filter   │ Der Zollbeamte                 │     
 └───────────────┴──────────────┴────────────────────────┴────────────────────────────────┘     
                                                                                                
 Das Ergebnis: Wir haben ein System, bei dem das "unzuverlässige" LLM in einen "extrem          
 zuverlässigen" Käfig aus hart codierter Logik gesperrt wurde. Das LLM darf probieren,          
 scheitern und lernen, aber es kann den Prozess nicht verlassen oder manipulieren. Das ist      
 industrielle KI-Softwareentwicklung.  




 
 Da Firma nach dem Prinzip "Freedom in Strategy, Rigidity in Protocol" gebaut ist, ist sie      
 extrem modular. Du kannst fast jede Komponente austauschen, ohne den Rest des Systems zu       
 gefährden.                                                                                     
                                                                                                
 Hier ist dein "Developer's Map", unterteilt nach den Bereichen, die du bearbeiten möchtest.    
                                                                                                
 ────────────────────────────────────────────────────────────────────────────────               
                                                                                                
 ### 1. Den Workflow ändern (Das Gesetz)                                                        
                                                                                                
 Wenn du die Reihenfolge der Schritte ändern willst (z.B. eine neue "Review-Phase" zwischen     
 Coding und Verifizierung einbauen), sind das deine Dateien:                                    
                                                                                                
 - engine/governance.py: Dies ist das Herzstück. Hier ist die "Governance Matrix" definiert.    
   Sie legt fest, welches Event (TaskEvent) in welcher Phase (ExecutionPhase) zu welchem neuen  
   Zustand führt. Wenn du eine neue Phase einführst, musst du sie hier registrieren.            
 - engine/orchestrator.py: Hier wird die Logik implementiert, wie der Orchestrator auf diese    
   Ereignisse reagiert und wie er die Phasen steuert.                                           
 - engine/scheduler.py: Hier bearbeitest du, wie Aufgaben verteilt werden (z.B. Prioritäten,    
   maximale Concurrency).                                                                       
                                                                                                
 ### 2. Agenten & Prompts anpassen (Die Intelligenz)                                            
                                                                                                
 Wenn du willst, dass der Coder anders schreibt, der Planner detaillierter plant oder du einen  
 ganz neuen Agenten (z.B. einen "Security Auditor") hinzufügen willst:                          
                                                                                                
 - workers/ (Ordner):                                                                           
     - planner.py: Hier liegt die Logik und der System-Prompt für den Strategen.                
     - executor.py: Hier liegt die Logik und der System-Prompt für den Coder.                   
 - workers/llm_worker.py: Die Basisklasse für alle LLM-Worker. Wenn du das grundlegende         
   Verhalten aller Agenten ändern willst (z.B. wie sie mit Fehlern umgehen), mach es hier.      
 - Neuen Agenten hinzufügen:                                                                    
     1. Erstelle eine neue Klasse in workers/ (oder erbend von LLMWorker).                      
     2. Definiere eine neue Role in engine/models.py (z.B. Role.AUDITOR).                       
     3. Füge die entsprechende Logik in die governance.py ein, damit der Orchestrator weiß,     
        wann dieser neue Agent gerufen werden soll.                                             
                                                                                                
 ### 3. LLM-Provider austauschen (Die Rechenpower)                                              
                                                                                                
 Wenn du von Nvidia NIM zu OpenAI, Anthropic oder einem lokalen Llama-Modell wechseln willst:   
                                                                                                
 - engine/providers/ (Ordner):                                                                  
     - base.py: Die Schnittstelle, die jeder Provider erfüllen muss.                            
     - nvidia_provider.py, openai_provider.py, etc.: Die konkreten Implementierungen.           
 - Umstellung: Du musst lediglich im Start-Script (z.B. run_8_1.py) den Provider austauschen.   
   Die Engine merkt nicht einmal, dass ein anderes Modell antwortet, solange der Provider das   
   richtige Format liefert.                                                                     
                                                                                                
 ### 4. Sandbox & Timeouts (Die Sicherheit)                                                     
                                                                                                
 Wenn das Programm zu schnell terminiert, du mehr Rechte in der Sandbox willst oder die         
 Hardware-Limits anpassen musst:                                                                
                                                                                                
 - engine/services/sandbox.py: Hier bearbeitest du, wie Prozesse gestartet werden, wie Timeouts 
   gehandhabt werden und wie die Isolation funktioniert.                                        
 - engine/orchestrator.py: Suche nach Variablen wie ack_timeout oder hard_timeout. Hier wird    
   festgelegt, wann die Engine einen Worker für "tot" erklärt und einen Reset auslöst.          
 - engine/services/guardian.py: Hier definierst du die Validierungsregeln. Wenn du willst, dass 
   der Coder bestimmte neue Felder in seinem JSON liefert, musst du das Schema hier anpassen.   
                                                                                                
 ### 5. Datenbank & State (Das Gedächtnis)                                                      
                                                                                                
 Wenn du mehr Daten speichern willst (z.B. die Kosten pro Task oder die genaue Zeitdauer pro    
 Phase):                                                                                        
                                                                                                
 - engine/models.py: Hier definierst du die SQLAlchemy-Modelle (Project, Plan, Task, Message).  
   Füge hier neue Spalten hinzu.                                                                
 - engine/repository.py: Hier liegen die SQL-Abfragen. Wenn du eine neue Spalte im Modell hast, 
   musst du hier die save- und get-Methoden anpassen.                                           
 - engine/db.py: Die grundlegende Datenbank-Verbindung und Session-Konfiguration.               
                                                                                                
 ────────────────────────────────────────────────────────────────────────────────               
                                                                                                
 ### 🛠 Zusammenfassung der "Hebel"                                                              
                                                                                                
 ┌────────────────────┬────────────────────────┬───────────────┬─────────────────────────────┐  
 │ Ziel               │ Datei / Ordner         │ Schwierigkeit │ Risiko                      │  
 ├────────────────────┼────────────────────────┼───────────────┼─────────────────────────────┤  
 │ Prompt ändern      │ workers/*.py           │ Einfach       │ Niedrig                     │  
 ├────────────────────┼────────────────────────┼───────────────┼─────────────────────────────┤  
 │ Timeout anpassen   │ engine/orchestrator.py │ Einfach       │ Niedrig                     │  
 ├────────────────────┼────────────────────────┼───────────────┼─────────────────────────────┤  
 │ Neues LLM nutzen   │ engine/providers/      │ Mittel        │ Mittel                      │  
 ├────────────────────┼────────────────────────┼───────────────┼─────────────────────────────┤  
 │ Phasen hinzufügen  │ engine/governance.py   │ Schwer        │ Hoch                        │  
 ├────────────────────┼────────────────────────┼───────────────┼─────────────────────────────┤  
 │ Datenmodell ändern │ engine/models.py       │ Mittel        │ Mittel (DB-Migration nötig) │  
 └────────────────────┴────────────────────────┴───────────────┴─────────────────────────────┘  
                                                                                                
 Pro-Tipp für Modifikationen:                                                                   
 Wenn du etwas an der governance.py oder orchestrator.py änderst, starte immer mit einem        
 Clean-Run (lösche die .db Datei). Da diese Dateien den Zustand der State-Machine definieren,   
 führen alte Datenbank-Einträge bei neuen Regeln oft zu inkonsistenten Zuständen.  



 