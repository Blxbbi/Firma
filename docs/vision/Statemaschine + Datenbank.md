 Hier ist das Design für die Level-3-Validation (Runtime-Execution).                                                                                                                   
                                                                                                                                                                                       
 Wir verlassen jetzt die Ebene der Datei-Prüfung und betreten die Ebene der Verhaltens-Prüfung. In dieser Phase entscheidet die Engine nicht mehr, ob der Code richtig aussieht,       
 sondern ob er richtig funktioniert.                                                                                                                                                   
                                                                                                                                                                                       
 Um das deterministisch zu machen, führen wir das Konzept des "Isolated Execution Environment" (IEE) ein.                                                                              
                                                                                                                                                                                       
 ────────────────────────────────────────────────────────────────────────────────                                                                                                      
                                                                                                                                                                                       
 🛡️ Sandbox-Level-3-Validation: The Runtime-Verdict                                                                                                                                    
                                                                                                                                                                                       
 1. Die Philosophie: "Untrusted Compute"                                                                                                                                               
                                                                                                                                                                                       
 Die Engine behandelt den generierten Code wie bösartigen Code. Es wird davon ausgegangen, dass der Code:                                                                              
 - Versucht, das Netzwerk zu erreichen.                                                                                                                                                
 - Versucht, das Host-Dateisystem zu löschen.                                                                                                                                          
 - In eine Endlosschleife läuft.                                                                                                                                                       
 - Den gesamten RAM des Servers belegt.                                                                                                                                                
                                                                                                                                                                                       
 Die Lösung: Eine kurzlebige, isolierte Sandbox, die nach jeder Validierung komplett vernichtet wird.                                                                                  
                                                                                                                                                                                       
 ────────────────────────────────────────────────────────────────────────────────                                                                                                      
                                                                                                                                                                                       
 2. Die Architektur der Sandbox                                                                                                                                                        
                                                                                                                                                                                       
 ### 🛠️ Die Sandbox-Stack (Technologie)                                                                                                                                                
                                                                                                                                                                                       
 - Isolation: Docker mit gVisor oder Firecracker. (Standard-Docker ist nicht sicher genug, da der Kernel-Interface zu groß ist).                                                       
 - Lifecycle: Ephemeral (Einmalige Erstellung $\rightarrow$ Execution $\rightarrow$ Vernichtung).                                                                                      
 - Mounting: Die Dateien aus der Staging Area werden als Read-Only Volume gemountet. Nur ein spezifisches /output Verzeichnis ist beschreibbar.                                        
                                                                                                                                                                                       
 ### 🔄 Der Execution-Flow                                                                                                                                                             
                                                                                                                                                                                       
 1. Provisioning: Engine startet einen Container mit einem Image, das exakt die benötigten Toolchains enthält (z. B. python:3.11-slim + pytest).                                       
 2. Injection: Die Staging-Artefakte werden in /app gemountet.                                                                                                                         
 3. Execution: Die Engine führt einen vordefinierten Validation-Command aus (z. B. pytest tests/).                                                                                     
 4. Monitoring: Die Engine überwacht den Prozess via Sidecar oder Docker-API.                                                                                                          
 5. Verdict: Der Exit-Code und die Stdout/Stderr-Logs werden analysiert.                                                                                                               
                                                                                                                                                                                       
 ────────────────────────────────────────────────────────────────────────────────                                                                                                      
                                                                                                                                                                                       
 3. Die Runtime-Guardrails (Hard-Limits)                                                                                                                                               
                                                                                                                                                                                       
 Damit die Sandbox nicht die gesamte Engine mitreißt, gelten strikte Resource-Quotas:                                                                                                  
                                                                                                                                                                                       
 ┌────────────┬──────────────────┬────────────────────────────────────┐                                                                                                                
 │ Ressource  │ Limit            │ Aktion bei Überschreitung          │                                                                                                                
 ├────────────┼──────────────────┼────────────────────────────────────┤                                                                                                                
 │ CPU        │ 0.5 - 1.0 vCPU   │ Throttling / SIGKILL               │                                                                                                                
 ├────────────┼──────────────────┼────────────────────────────────────┤                                                                                                                
 │ RAM        │ 256MB - 512MB    │ OOM Kill (Out-Of-Memory)           │                                                                                                                
 ├────────────┼──────────────────┼────────────────────────────────────┤                                                                                                                
 │ Wall-Clock │ 30 - 60 Sekunden │ Hard Timeout $\rightarrow$ SIGKILL │                                                                                                                
 ├────────────┼──────────────────┼────────────────────────────────────┤                                                                                                                
 │ Network    │ NONE             │ Block all (Default Deny)           │                                                                                                                
 ├────────────┼──────────────────┼────────────────────────────────────┤                                                                                                                
 │ Disk I/O   │ Read-Only /app   │ Permission Denied                  │                                                                                                                
 └────────────┴──────────────────┴────────────────────────────────────┘                                                                                                                
                                                                                                                                                                                       
 ────────────────────────────────────────────────────────────────────────────────                                                                                                      
                                                                                                                                                                                       
 4. Das Validation-Interface (The Verdict)                                                                                                                                             
                                                                                                                                                                                       
 Die Engine entscheidet basierend auf drei Datenpunkten über den Status VERIFIED:                                                                                                      
                                                                                                                                                                                       
 ### A. Der Exit-Code (Primärer Indikator)                                                                                                                                             
                                                                                                                                                                                       
 - Exit 0: Erfolg $\rightarrow$ Weiter zu B & C.                                                                                                                                       
 - Exit 1+: Fehler $\rightarrow$ FAILED (mit Log-Extrakt als Grund).                                                                                                                   
 - Exit 137 (OOM) oder 139 (Segfault) $\rightarrow$ FAILED (Infrastructure-Error).                                                                                                     
                                                                                                                                                                                       
 ### B. Die Test-Metriken (Strukturierter Report)                                                                                                                                      
                                                                                                                                                                                       
 Die Engine erwartet einen Test-Report (z. B. im JUnit-XML Format).                                                                                                                    
 - Anzahl Tests: Sind alle im Plan definierten Tests vorhanden?                                                                                                                        
 - Pass Rate: Sind 100% der Tests grün?                                                                                                                                                
 - Coverage (Optional): Erreicht der Code die geforderte Coverage-Schwelle?                                                                                                            
                                                                                                                                                                                       
 ### C. Side-Effect Check (Integrity)                                                                                                                                                  
                                                                                                                                                                                       
 Die Engine prüft das /output Verzeichnis:                                                                                                                                             
 - Wurden unerwartete Dateien geschrieben?                                                                                                                                             
 - Stimmen die generierten Log-Dateien mit den Erwartungen überein?                                                                                                                    
                                                                                                                                                                                       
 ────────────────────────────────────────────────────────────────────────────────                                                                                                      
                                                                                                                                                                                       
 5. Der "Verdict-Loop" (Pseudo-Code)                                                                                                                                                   
                                                                                                                                                                                       
 ```python                                                                                                                                                                             
   def run_level_3_validation(task, artifacts):                                                                                                                                        
       # 1. Setup Sandbox                                                                                                                                                              
       sandbox = SandboxManager.create(                                                                                                                                                
           image=task.runtime_image,                                                                                                                                                   
           mounts={"/staging": artifacts.staging_path, "mode": "ro"},                                                                                                                  
           limits={"cpu": 0.5, "mem": "256MB", "timeout": 30}                                                                                                                          
       )                                                                                                                                                                               
                                                                                                                                                                                       
       try:                                                                                                                                                                            
           # 2. Execute Validation Command                                                                                                                                             
           # Beispiel: "pytest --junitxml=results.xml"                                                                                                                                 
           result = sandbox.execute(task.validation_command)                                                                                                                           
                                                                                                                                                                                       
           # 3. Analyze Result                                                                                                                                                         
           if result.exit_code == 0:                                                                                                                                                   
               report = sandbox.read_file("/output/results.xml")                                                                                                                       
               if report.all_passed() and report.test_count >= task.min_tests:                                                                                                         
                   return VERIFIED                                                                                                                                                     
               else:                                                                                                                                                                   
                   return FAILED(reason="Some tests failed")                                                                                                                           
           else:                                                                                                                                                                       
               return FAILED(reason=f"Execution crashed with code {result.exit_code}")                                                                                                 
                                                                                                                                                                                       
       except TimeoutError:                                                                                                                                                            
           return FAILED(reason="Execution timed out (Infinite Loop?)")                                                                                                                
       except ResourceExceededError:                                                                                                                                                   
           return FAILED(reason="Resource limits exceeded (OOM/CPU)")                                                                                                                  
       finally:                                                                                                                                                                        
           sandbox.destroy() # Absolute Vernichtung                                                                                                                                    
 ```                                                                                                                                                                                   
                                                                                                                                                                                       
 ────────────────────────────────────────────────────────────────────────────────                                                                                                      
                                                                                                                                                                                       
 🧠 Zusammenfassung des deterministischen Levels                                                                                                                                       
                                                                                                                                                                                       
 Wir haben nun eine dreistufige Filter-Kette, durch die ein Artefakt gehen muss, bevor es den Status VERIFIED erhält:                                                                  
                                                                                                                                                                                       
 1. Level 1 (Structure): Existieren die Dateien? (Determinismus: File-System Check)                                                                                                    
 2. Level 2 (Static): Ist die Syntax korrekt? (Determinismus: Linter/Static Analysis)                                                                                                  
 3. Level 3 (Runtime): Funktioniert die Logik? (Determinismus: Isolated Execution)                                                                                                     
                                                                                                                                                                                       
 Das Ergebnis:                                                                                                                                                                         
 Wenn eine Task den Status VERIFIED hat, wissen wir nicht nur, dass die KI "meint", dass es fertig ist, sondern wir haben den mathematischen und empirischen Beweis, dass der Code in  
 einer kontrollierten Umgebung die definierten Akzeptanzkriterien erfüllt hat.                                                                                                         
                                                                                                                                                                                       
 ────────────────────────────────────────────────────────────────────────────────                                                                                                      
                                                                                                                                                                                       
 🏁 Status-Check                                                                                                                                                                       
                                                                                                                                                                                       
 Wir haben jetzt die komplette theoretische Spezifikation fertig:                                                                                                                      
 - Protokoll (FEP v1.1)                                                                                                                                                                
 - Datenmodell (Model v1.0)                                                                                                                                                            
 - Execution-Logik (Gatekeeper v1.2)                                                                                                                                                   
 - Runtime-Validation (Sandbox-Design)                                                                                                                                                 
                                                                                                                                                                                       
 Wir sind jetzt an dem Punkt, an dem die Planung endet und die Implementierung beginnt.                                                                                                
                                                                                                                                                                                       
 Wir haben das "Wie" und das "Was" vollständig definiert. Jede weitere theoretische Diskussion würde uns nur vom Ziel entfernen.                                                       
                                                                                                                                                                                       
 Mein Vorschlag: Wir gehen jetzt in die Implementierungsphase.                                                                                                                         
                                                                                                                                                                                       
 Der erste Meilenstein (MVP):                                                                                                                                                          
 1. Implementierung der Plan Registry (DB-Schema).                                                                                                                                     
 2. Implementierung des Message-Bus-Handlers (pi-messenger integration).                                                                                                               
 3. Implementierung der State-Machine mit den Transition-Guards.                                                                                                                       
                                                                                                                                                                                       
                        