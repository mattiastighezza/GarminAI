# CONTEXT.md - Garmin AI Running Coach

## 1. Project Overview
Pipeline Python che interroga Garmin Connect, estrae telemetria fisiologica e biomeccanica avanzata (lap chilometrici, zone cardio, dinamiche di corsa, meteo), riconosce la seduta prevista nel piano di allenamento (anche se recuperata o anticipata in un giorno diverso), ne valuta rigorosamente l'aderenza tramite Google Gemini (Free Tier con fallback resiliente) e invia un report analitico su Telegram.

---

## 2. Profilo Atleta & Parametri di Default
- **Anagrafica Base:** 31 anni, 1.85 m, 96 kg.
- **Soglie Fisiologiche:** FC Max ~202 bpm, Soglia Anaerobica (SAFC) ~178 bpm.
- **Target Agonistico:** Mezza delle Terre Verdiane (21.097 km) - Passo obiettivo: **5:35 min/km**.
- **Cross-Training:** Corsa su strada alternata a mountain bike (MTB) e potenziamento muscolare.
- **Tono AI Coach:** Severo, esigente, zero complimenti di facciata, focalizzato sull'impatto biomeccanico del peso corporeo (96 kg) su GCT, cadenza, oscillazione verticale e gestione dello sforzo.

---

## 3. Tech Stack & Vincoli di Sistema
- **Runtime:** Python 3.15.1
- **Librerie Core:** `garminconnect`, `google-genai` (SDK ufficiale v1+, client unificato), `python-dotenv`, `requests`, `httpx` (previsto per sviluppi futuri).
- **Persistenza & File Locali:**
  - `.env`: Credenziali Garmin, API key Gemini, token e chat ID Telegram.
  - `~/.garmin_tokens`: Directory cache sessione OAuth Garmin (gestione MFA una tantum).
  - `~/.garmin_last_id.txt`: Registro ID ultima attività processata.
  - `piano_allenamento.txt`: Tabella di allenamento in testo libero.
  - `storico_allenamenti.md`: Log progressivo cumulativo delle sessioni e delle analisi AI.
  - `profilo_atleta.json`: Scheda anagrafica e parametri fisiologici dinamici (previsto, attualmente hardcoded).
  - `prompts/`: System prompt specializzati (`coach_system.md`, `fisiologo_system.md`, `tattico_system.md`, `giudice_system.md`).

---

## 4. Stato Attuale dell'Implementazione (Funzionante)
- **Architettura Modulare (Completata Fase 0):** Codice suddiviso in package `src/` e orchestrato da `main.py` (`garmin-ai.py` mantenuto come backup):
  - `src/config.py`: Gestione configurazione centralizzata, percorsi e variabili d'ambiente.
  - `src/garmin_client.py`: Inizializzazione client Garmin e recupero nuove attività.
  - `src/telemetry.py`: Formattazione metriche, estrazione dati avanzati (meteo, zone HR, split) e calcolo matematico locale della deriva cardiaca/Efficiency Factor.
  - `src/debate.py`: Orchestratore del Multi-Agent Debate a due round con supporto parallelo non bloccante.
  - `src/llm_service.py`: Client unificato Gemini con orchestrazione debate e catena di fallback resiliente.
  - `src/notifier.py`: Invio messaggi Telegram con chunking intelligente.
  - `src/storage.py`: Gestione persistenza per piano di allenamento, storico e ID ultima attività.
  - `prompts/`: System prompt specializzati per i diversi ruoli del coach e del dibattito.
- **Multi-Agent Debate (Completata Fase 4 ✅):**
  - Contraddittorio competitivo strutturato a 3 agenti:
    1. **Il Fisiologo (Difesa):** valuta l'impatto biologico del peso (96 kg), la termoregolazione/meteo, la deriva cardiaca e la variazione dell'Efficiency Factor pre-calcolati.
    2. **Il Tattico di Pista (Accusa):** analizza la geometria della corsa, gli split chilometrici, il mancato rispetto del target 5:35 min/km e le pause superflue con tolleranza zero.
    3. **L'Head Coach (Giudice Supremo):** valuta le tesi contrapposte sui dati reali della sessione ed emette il verdetto finale operativo in 4 punti direttamente all'atleta, senza citare gli agenti interni o il dibattito.
  - **Esecuzione & Vincoli Free Tier:** Round 1 parallelo asincrono con `asyncio.gather()`, stampa terminale per debug di fisiologo/tattico, spacing di sicurezza per il rispetto del limite di 15 RPM, Round 2 di sintesi e fallback automatico al modello coach singolo in caso di errore.
- **Autenticazione Garmin Stabile:** Riuso token OAuth locali in `~/.garmin_tokens` per prevenire blocchi di sessione e gestire il prompt MFA.
- **Estrazione Telemetrica Approfondita:**
  - Metriche aggregate: Distanza, tempo attivo, elapsed, pause, passo medio/picco, dislivello.
  - Fisiologia & Carico: FC media/max, Training Effect aerobico/anaerobico, Training Load acuto, VO2Max, calorie, liquidi stimati.
  - Biomeccanica & Dinamiche: Cadenza (spm), falcata (cm), oscillazione/rapporto verticale, Ground Contact Time (ms) e bilanciamento L/R, potenza media/max/normalizzata.
  - Dati aggiuntivi estratti: Meteo (con conversione automatica °F -> °C), percentuali di permanenza nelle zone cardio, split per singolo lap.
- **Calcolo Deriva Cardiaca & Efficiency Factor:** Pre-calcolato matematicamente a livello locale confrontando prima e seconda metà dei lap (var % FC e var % EF) e passato esplicitamente nel contesto per Gemini.
- **Catena Fallback Gemini:**
  - Priorità modelli tramite .env: `gemini-3.5-flash`, `gemini-3.8-flash`, `gemini-3.7-flash`, `gemini-3.1-flash-lite`, `gemini-2.5-flash`.
  - Gestione errori: Skip immediato al modello successivo su HTTP 404/429; retry esponenziale (5s, 10s, 20s) fino a 3 tentativi su errori transitori 500/503 o timeout di rete.
- **Spedizione Notifiche Telegram:**
  - Client sincrono tramite `requests.post`.
  - Chunking intelligente sui ritorni a capo entro il limite di 4000 caratteri per evitare crash.
  - Invio in testo semplice (senza `parse_mode`) per prevenire errori di formattazione markdown.

---

## 5. Regole Architetturali per l'AI Assistant (Guardrails)
1. **SDK Gemini:** Usare unicamente `from google import genai`. Vietato tassativamente reintrodurre il pacchetto legacy deprecato `google-generativeai`.
2. **Sicurezza Credenziali:** Non stampare o registrare nei log URL con esposti token Telegram o chiavi API.
3. **Integrità Dati Garmin:**
   - Velocità fornite in `m/s` -> convertire sempre in passo `min/km` via `format_pace`.
   - Temperature meteo fornite in Fahrenheit -> convertire sempre in Celsius.
   - Distanze fornite in metri -> convertire in chilometri.
4. **Idempotenza:** `LAST_ACTIVITY_FILE` e `storico_allenamenti.md` vanno aggiornati solo a completamento positivo di analisi e notifica.
5. **Restrizione Terminale:** Non eseguire comandi nel terminale in modo autonomo. Suggerire il comando nel testo e attendere l'esecuzione manuale da parte dell'utente.

---

## 6. Roadmap Sviluppi Futuri & Guida all'Implementazione

### FASE 0: Refactoring Architetturale (Da Monolite a Moduli) [COMPLETATA ✅]
*Obiettivo:* Superare l'implementazione monolitica di `garmin-ai.py`.
* **Implementazione effettuata:** Codice modularizzato in `src/` (`config.py`, `garmin_client.py`, `telemetry.py` con calcolo matematico di drift ed EF, `llm_service.py`, `notifier.py`, `storage.py`), nuovo entry point `main.py` ed esternalizzazione del prompt in `prompts/coach_system.md`.

### FASE 1: Onboarding Interattivo & Profilo Utente Dinamico
*Obiettivo:* Rendere il bot bidirezionale: al primo avvio acquisisce dati atleta, piano e storico pregresso; consente modifiche successive da chat (es. variazione peso).
* **Dati e Persistenza (`profilo_atleta.json`):**
  - Salvare: `eta`, `peso_kg`, `altezza_m`, `passo_target`, `obiettivo_gara`, `onboarding_completato`, `ultimo_aggiornamento`.
  - Creare un modulo `profile_manager.py` con `load_profile()`, `save_profile()`, `update_field()`.
* **Flusso Onboarding (`ConversationHandler` in `python-telegram-bot`):**
  1. `/start`: Se `onboarding_completato == False`, avvia sequenza guidata; altrimenti mostra la scheda corrente.
  2. Step 1: Chiede età e peso separati da virgola (es. `31, 96`).
  3. Step 2: Chiede se c'è un piano pronto (testo incollato in chat o digitare `salta`).
  4. Step 3: Chiede quante attività storiche pregresse importare da Garmin (`0`, `5`, `10`).
* **Comandi Rapidi di Aggiornamento:**
  - `/peso <valore>`: Aggiorna istantaneamente il peso nel JSON.
  - `/piano <testo>`: Visualizza o sovrascrive `piano_allenamento.txt`.
  - `/profilo`: Stampa riepilogo leggibile dei parametri correnti.

### FASE 2: Architettura a Demone Asincrono (`python-telegram-bot[job-queue]`)
*Obiettivo:* Far convivere il listener Telegram per i comandi utente con il controllo periodico su Garmin.
* **Come farlo:**
  1. Installare `python-telegram-bot[job-queue]`.
  2. Registrare comandi e `ConversationHandler` su `ApplicationBuilder`.
  3. Aggiungere il job ciclico Garmin: `app.job_queue.run_repeating(callback_garmin, interval=900, first=10)`.
  4. *Gestione Thread:* Poiché `garminconnect` è sincrona, eseguire le chiamate di fetch fuori dall'event loop asincrono tramite `await asyncio.to_thread(garmin.get_activities, 0, 5)` per non bloccare Telegram.

### FASE 3: Matching Dinamico Seduta vs Piano & Calcolo Aderenza
*Obiettivo:* Valutare la rispondenza dell'allenamento rispetto al piano, identificando automaticamente la seduta anche se eseguita in un giorno diverso da quello programmato.
* **Come implementarlo:**
  1. **Iniezione della Data Formattata:** In `garmin_client.py`, passare al prompt la data estesa con giorno della settimana (es. `Mercoledì 28 Ottobre 2026, ore 18:30`).
  2. **Istruzione nel System Prompt:** 
     - Verificare se la seduta corrisponde a quella prevista per il giorno corrente e calcolare l'aderenza (1-10).
     - Se non corrisponde (o era giorno di riposo), confrontare le metriche con le altre sedute della settimana per riconoscere se si tratta di un recupero o un anticipo.

### FASE 4: Multi-Agent Debate (Fisiologo vs Tattico vs Giudice) [COMPLETATA ✅]
*Obiettivo:* Eliminare le risposte piatte e le allucinazioni tramite un contraddittorio competitivo strutturato, mantenendosi entro i vincoli del Free Tier (15 RPM).
* **Implementazione effettuata:**
  - Creati i prompt specializzati `prompts/fisiologo_system.md`, `prompts/tattico_system.md` e `prompts/giudice_system.md`.
  - Creato l'orchestratore `src/debate.py` con Round 1 in parallelo (`asyncio.gather`), spacing protettivo per il Free Tier e Round 2 di sintesi del Giudice.
  - Integrato in `src/llm_service.py` con fallback automatico e trasparenza verso `main.py`.

### FASE 5: Integrazione Cross-Training (MTB & Palestra)
*Obiettivo:* Far considerare al modello il carico neuromuscolare e metabolico extra-corsa.
* **Come farlo:**
  1. Se `act_type` è `cycling`, `mountain_biking` o `strength_training`, non invocare Gemini per l'analisi completa (togliere il filtro esclusivo su `running`).
  2. Estrarre data, tipo, durata, FC media e Training Load.
  3. Fare append di una riga sintetica in `storico_allenamenti.md` (es: `[2026-10-25] MTB: 2h10m | FC: 138 bpm | Load: 195`).
  4. Aggiornare `LAST_ACTIVITY_FILE` per chiudere l'elaborazione dell'attività non-running.

### FASE 6: Backfill Storico Intelligente (Quota Free Tier Safe)
*Obiettivo:* Popolare lo storico iniziale senza rischiare HTTP 429 su Gemini.
* **Come farlo:**
  1. Scaricare le ultime $N$ corse da Garmin.
  2. Estrarre localmente in Python solo: Data, Km, Durata, Passo, FC media, Load.
  3. Scrivere le righe in blocco all'inizio di `storico_allenamenti.md`.
  4. Aggiornare `LAST_ACTIVITY_FILE` all'attività più recente.

### FASE 7: Compressione Contesto & Ottimizzazione Prompt
*Obiettivo:* Garantire una visione di trend plurisettimanale senza saturare la finestra di contesto.
* **Come farlo:**
  1. Separare l'archiviazione:
     - `storico_completo.md`: archivio dettagliato con lap e testi integrali per consultazione umana.
     - `storico_sintetico.jsonl`: una riga JSON compatta per seduta.
  2. Nel prompt passare le ultime 10-15 sessioni da `storico_sintetico.jsonl` (consumo < 1500 token).

### FASE 8: Rifiniture Tecniche & Robustezza
* **Gestione Rate-Limit Dinamica:** Aggiungere un delay minimo o un token-bucket se si concatenano chiamate multiple durante il debate.
* **Modalità Mock per Sviluppo Offline:** Creare un flag `--mock` che carica un JSON Garmin locale senza effettuare chiamate di rete, permettendo di testare il debate LLM a costo zero.