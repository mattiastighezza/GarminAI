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
- **Librerie Core:** `garminconnect`, `google-genai` (SDK ufficiale v1+, client unificato), `python-telegram-bot[job-queue]`, `python-dotenv`, `requests`, `httpx` (previsto per sviluppi futuri), `matplotlib` (previsto per visual charting Fase 11).
- **Persistenza & File Locali:**
  - `.env`: Credenziali Garmin, API key Gemini, token e chat ID Telegram.
  - `~/.garmin_tokens`: Directory cache sessione OAuth Garmin (gestione MFA una tantum).
  - `~/.garmin_last_id.txt`: Registro ID ultima attività processata.
  - `piano_allenamento.txt`: Tabella di allenamento in testo libero.
  - `storico_allenamenti.md`: Log progressivo cumulativo delle sessioni e delle analisi AI.
  - `profilo_atleta.json`: Scheda anagrafica, antropometrica e parametri fisiologici dinamici (attivo da Fase 1).
  - `mock_data/`: Dataset simulati per lo sviluppo e test offline (`mock_data/running_activity.json`).
  - `prompts/`: System prompt specializzati dinamici (`coach_system.md`, `fisiologo_system.md`, `tattico_system.md`, `giudice_system.md`).
  - `ultime_direttive.json`: Cache degli ordini operativi dell'ultima seduta per la verifica nel feedback loop (previsto Fase 9).

---

## 4. Stato Attuale dell'Implementazione (Funzionante)
- **Onboarding Interattivo & Profilo Utente Dinamico (Completata Fase 1 ✅):**
  - **Persistenza & Profile Manager (`src/profile_manager.py` e `profilo_atleta.json`):**
    - Tracciamento dinamico di: età, altezza (m/cm), peso corporeo, peso iniziale di riferimento, FC Max, Soglia Anaerobica (SAFC), passo target gara, gara obiettivo, data ultimo aggiornamento, flag `onboarding_completato`.
    - Calcolo in tempo reale di **Indice di Massa Corporea (IMC)** con relativa categoria e **trend peso cumulativo** da inizio monitoraggio.
    - Parser fisiologico rigorosamente posizionale: il 1° valore imposta sempre e unicamente la FC Max (100-240 bpm), il 2° valore la SAFC (80-220 bpm), senza riordini o forzature min/max.
  - **Generalizzazione dei System Prompt AI (`prompts/`):**
    - Rimossi tutti i parametri statici hardcoded (96 kg, 1.85 m, 5:35 min/km) da `coach_system.md`, `fisiologo_system.md`, `tattico_system.md` e `giudice_system.md`.
    - Iniezione vincolante del blocco `=== PROFILO ATLETA & PARAMETRI DINAMICI ===` in Round 1 (Fisiologo/Tattico), Round 2 (Giudice) e fallback coach singolo in `src/debate.py` e `src/llm_service.py`.
  - **Bot Telegram Interattivo (`src/bot.py` & flag `--bot` in `main.py`):**
    - Procedura di onboarding guidato a 4 step con `ConversationHandler` e pulsanti inline nei messaggi (conferma default cardio 202/178, salta tabella, importazione storico Garmin 0, 5, 10).
    - Tastiera a pulsanti fissa e persistente (Reply Keyboard) sempre visibile sotto la barra di scrittura (`📋 Profilo`, `🏃‍♂️ Ultima Run`, `⚖️ Peso`, `📏 Altezza`, `❤️ Soglie FC`, `📋 Piano`, `⚡ Target`, `📖 Aiuto`).
    - Pulsanti inline sotto la scheda profilo per azioni rapide.
    - Comandi di aggiornamento e consultazione istantanei: `/peso`, `/altezza`, `/fc`, `/fcmax`, `/safc`, `/piano`, `/target`, `/gara`, `/ultimarun` (estrae l'ultima sessione e il report AI dallo storico), `/reset_onboarding`, `/aiuto`.
    - Import storico iniziale quota-safe (`src/garmin_client.py`) a costo zero di token LLM.
- **Architettura Modulare (Completata Fase 0):** Codice suddiviso in package `src/` e orchestrato da `main.py` (`garmin-ai.py` mantenuto come backup):
  - `src/config.py`: Gestione configurazione centralizzata, percorsi e variabili d'ambiente.
  - `src/garmin_client.py`: Inizializzazione client Garmin e recupero nuove attività.
  - `src/telemetry.py`: Formattazione metriche, estrazione dati avanzati (meteo, zone HR, split) e calcolo matematico locale della deriva cardiaca/Efficiency Factor.
  - `src/debate.py`: Orchestratore del Multi-Agent Debate a due round con supporto parallelo non bloccante.
  - `src/llm_service.py`: Client unificato Gemini con orchestrazione debate e catena di fallback resiliente.
  - `src/notifier.py`: Invio messaggi Telegram con chunking intelligente.
  - `src/storage.py`: Gestione persistenza per piano di allenamento, storico e ID ultima attività.
  - `src/mock_client.py`: Emulatore offline di Garmin Connect per collaudo locale a costo zero.
  - `src/rate_limiter.py`: Gestione dinamica rate-limit Free Tier Gemini (sliding-window anti-429).
  - `src/profile_manager.py`: Gestione persistenza profilo dinamico, calcolo IMC, trend peso e soglie.
  - `src/bot.py`: Listener interattivo Telegram per onboarding e comandi rapidi atleta.
  - `prompts/`: System prompt specializzati per i diversi ruoli del coach e del dibattito.
- **Rifiniture Tecniche & Robustezza (Completata Fase 8 ✅):**
  - **Modalità Mock Offline (`--mock`):** permette di eseguire l'intera pipeline (`python main.py --mock`) usando il dataset locale realistico `mock_data/running_activity.json`, senza interrogare Garmin Connect e senza alterare l'ID dell'attività reale né lo storico di produzione.
  - **Rate Limiter Dinamico Gemini:** singleton centralizzato `GeminiRateLimiter` con sliding window a 60 secondi (target 12 RPM rispetto al limite 15 RPM) e intervallo minimo garantito per prevenire errori 429 durante il dibattito a più round.
  - **Risoluzione Bug Idempotenza Garmin:** integrata la chiamata mancante a `save_last_activity_id(activity_id)` a completamento dell'invio Telegram reale.
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

### FASE 1: Onboarding Interattivo & Profilo Utente Dinamico [COMPLETATA ✅]
*Obiettivo:* Rendere il bot bidirezionale: al primo avvio acquisisce dati atleta, piano e storico pregresso; consente modifiche successive da chat (peso, altezza, soglie FC, passo target).
* **Implementazione effettuata:**
  - Creato `src/profile_manager.py` e persistenza JSON in `profilo_atleta.json`: anagrafica atleta, peso, altezza, FC Max, SAFC, passo target, obiettivo gara, calcolo real-time di IMC e trend ponderale cumulativo.
  - Creato il bot interattivo Telegram in `src/bot.py` (eseguibile via `python main.py --bot [--mock]`):
    - Onboarding guidato a 4 step con bottoni inline per default cardio, skip tabella e import storico Garmin (0, 5, 10).
    - Tastiera fissa (Reply Keyboard) sempre visibile sotto la chat per comandi rapidi a tocco singolo.
    - Pulsanti inline sotto la scheda profilo per interazione istantanea.
    - Comandi dedicati: `/peso`, `/altezza`, `/fc`, `/fcmax`, `/safc`, `/piano`, `/target`, `/gara`, `/ultimarun`, `/reset_onboarding`, `/aiuto`.
    - Regola posizionale ferrea per le soglie cardiache: 1° valore = FC Max, 2° valore = SAFC.
  - Generalizzati tutti i prompt in `prompts/` rimuovendo valori statici ed iniettando il profilo dinamico in Round 1 e Round 2 del Multi-Agent Debate.
  - Implementato in `src/garmin_client.py` l'import storico iniziale quota-safe nello storico locale.

### FASE 1.1: Rifiniture UX Bot Telegram & Acquisizione Dati Atomica
*Obiettivo:* Perfezionare l'interazione utente su Telegram eliminando ogni attrito di digitazione e garantendo controlli sempre visibili.
* **1. Hamburger Menu Button (`set_my_commands`):**
  - Configurare all'avvio del bot la lista comandi nativa Telegram tramite `app.bot.set_my_commands([BotCommand(...), ...])`.
  - Mostrare a sinistra del tasto allegati il pulsante "Menu" con l'elenco completo dei comandi e una descrizione chiara e sintetica di ciascuno.
* **2. Interfaccia Always-Interactive (Zero schermate senza tasti):**
  - Non lasciare mai l'utente senza tasti da premere in nessuna schermata o stato.
  - Mostrare sempre pulsanti contestuali o di default (es. `[ ❌ Annulla ]`, `[ 📋 Menu ]`, `[ ⏭️ Salta ]`) anche durante le richieste di input testuale.
* **3. Acquisizione Dati Atomica (Step Singoli):**
  - Riformulare l'onboarding e la raccolta dati scomponendo le richieste multiple in passaggi singoli atomici (un solo dato per step, zero separatori a virgola):
    - Step 1: Età $\rightarrow$ Step 2: Altezza $\rightarrow$ Step 3: Peso $\rightarrow$ Step 4: FC Max $\rightarrow$ Step 5: SAFC $\rightarrow$ Step 6: Tabella Allenamento $\rightarrow$ Step 7: Storico Garmin.

### FASE 2: Architettura a Demone Asincrono (`python-telegram-bot[job-queue]`)
*Obiettivo:* Far convivere il listener Telegram per i comandi utente con il controllo periodico in background su Garmin Connect nello stesso processo.
* **Come farlo:**
  1. Utilizzare `python-telegram-bot[job-queue]` (già integrato nella base di `src/bot.py`).
  2. Registrare il job periodico Garmin su `Application`: `app.job_queue.run_repeating(callback_garmin, interval=900, first=10)`.
  3. *Gestione Thread non bloccante:* Eseguire il fetch sincrono di `garminconnect` su thread separato (`await asyncio.to_thread(garmin.get_activities, 0, 5)`) per non rallentare né bloccare le risposte della chat Telegram.
  4. Non appena rilevata una nuova attività di corsa, lanciare in asincrono `analyze_with_gemini_async(...)` e recapitare il verdetto direttamente in chat.

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

### FASE 8: Rifiniture Tecniche & Robustezza [COMPLETATA ✅]
*Obiettivo:* Garantire stabilità operativa, conformità ai limiti di rate-limit Free Tier e facilità di sviluppo locale.
* **Implementazione effettuata:**
  - Creato `mock_data/running_activity.json` e la classe simulata `src/mock_client.py` (`MockGarminClient`) per consentire collaudi offline istantanei via `python main.py --mock`.
  - Creato `src/rate_limiter.py` con sliding-window su 60 secondi (target di sicurezza 12 RPM) e intervallo minimo anti-burst, integrato in `src/debate.py`.
  - Risolto il mancato aggiornamento di `~/.garmin_last_id.txt` in `main.py` per prevenire la ri-elaborazione continua della medesima sessione reale.

### FASE 8.1: Hardening Rate Limiter & Protezione Quota Gemini (Anti-429 RPM & RPD)
*Obiettivo:* Azzerare gli errori HTTP 429 su Gemini Free Tier gestendo attivamente sia il rate limit al minuto (RPM) che il tetto giornaliero di richieste (RPD) monitorati su Google AI Studio.
* **Criticità rilevata:** L'agente Tattico riceve `[Tattico] Modello gemini-3.5-flash non disponibile (errore 429). Passo al modello successivo.` per sforamento dei limiti Free Tier su AI Studio.
* **Come implementarlo:**
  1. **Tracciamento Distinto RPM e RPD:** Integrare nel `GeminiRateLimiter` un contatore persistente delle chiamate giornaliere (`gemini_quota_tracker.json`) con reset a mezzanotte, per bloccare preventivamente le chiamate verso modelli che hanno esaurito l'RPD ed evitare tentativi inutili.
  2. **Classificazione Intelligente dell'Errore 429:**
     - Se l'errore 429 indica superamento dell'RPM (quota transitoria al minuto): applicare un backoff esponenziale con jitter (attesa di 10-20s) prima di tentare il fallback.
     - Se l'errore 429 indica esaurimento dell'RPD (quota giornaliera): segnare immediatamente il modello come "esausto per oggi" nel tracker locale e passare al modello successivo nella catena di fallback.
  3. **Pacing Adattivo & Fallback Sequenziale:** Se il tasso di richieste si avvicina alla soglia (es. > 10 RPM), commutare l'esecuzione di Fisiologo e Tattico da parallela a sequenziale con spacing di sicurezza garantito (es. 4-5 secondi tra le chiamate), evitando burst simultanei.
  4. **Model Routing Ottimizzato per Quota:** Utilizzare modelli ultra-leggeri con quote RPD più generose per il Round 1 (Fisiologo e Tattico) e riservare i modelli a più alto contesto/reasoning al Giudice (Round 2).

### FASE 9: Ottimizzazione Architetturale Multi-Agent Debate & Feedback Loop
*Obiettivo:* Rendere il dibattito a due round rigorosamente deterministico nei calcoli, strutturato tramite schemi JSON Pydantic, protetto da crash di formattazione Telegram ed evoluto a coach persistente verificando l'aderenza alle direttive della seduta precedente.
* **1. Pre-Processing Deterministico Python (a monte del Round 1):**
  - Parsing del piano e isolamento della seduta programmata per la data odierna.
  - Calcolo matematico a monte di: $\Delta$ passo medio rispetto al target (sec/km), durata e incidenza pause ($T_{\text{elapsed}} - T_{\text{moving}}$), dislivello e cadenza vs soglia minima.
  - Fornitura di un set di "fatti incontrovertibili" a Tattico e Fisiologo per azzerare le allucinazioni aritmetiche.
* **2. Output Strutturato (JSON / Pydantic SDK `google-genai`):**
  - Definizione degli schemi `TatticoOutput` e `FisiologoOutput` tramite Pydantic e parametri nativi `response_mime_type="application/json"` con `response_schema`.
  - Il Giudice riceve dizionari puliti e ad alta densità anziché testi liberi in Markdown, velocizzando la sintesi ed eliminando il rumore.
* **3. Calibrazione Temperature & Model Routing:**
  - Tattico: `temperature=0.1 - 0.2` (contabilità e geometria della corsa rigorosa, zero interpretazioni).
  - Fisiologo: `temperature=0.3 - 0.4` (rigore metabolico e biologico, eliminazione correlazioni fittizie).
  - Giudice: `temperature=0.5` (fluidità verbale per tono relazionale "Tough Love").
  - Routing modelli: valutazione di modelli ultra-rapidi/economici per il Round 1 strutturato e modello a pieno contesto/reasoning per il Giudice.
* **4. Chiusura Feedback Loop (Verifica Direttiva Precedente $N-1$):**
  - Persistenza su file/storage (`ultime_direttive.json`) delle 3-4 direttive operative assegnate dal Giudice alla seduta $N-1$.
  - Iniezione degli ordini precedenti nel prompt di Tattico e Giudice per la seduta $N$ per verificare disciplina, recidive o correzioni.
* **5. Sanitizzazione e Parsing HTML Telegram:**
  - Istruzione del prompt del Giudice a formattare l'output direttamente in HTML semplice (`<b>`, `<i>`, `<code>`).
  - Aggiornamento di `src/notifier.py` con `parse_mode="HTML"` per garantire output formattato ed elegante, eliminando i crash dovuti ai caratteri speciali non escapati di `MarkdownV2`.

### FASE 10: Fisiologia Olistica & Prevenzione Infortuni (Sonno, HRV, ACWR & Usura Scarpe)
*Obiettivo:* Integrare la valutazione metabolica e di recupero sistemico per distinguere tra scarso impegno e affaticamento biologico reale, tutelando articolazioni e tendini dell'atleta (96 kg).
* **1. Estrazione Parametri di Recupero & Sonno:**
  - Recupero tramite `garminconnect` di: durata e punteggio sonno, stato HRV notturno (equilibrato/basso), Body Battery e ore di recupero stimate.
  - Iniezione delle metriche di recupero nel prompt del Fisiologo per contestualizzare la deriva cardiaca e la tolleranza allo sforzo prima dell'emissione del verdetto.
* **2. Calcolo Matematico Deterministico ACWR (Acute:Chronic Workload Ratio):**
  - Calcolo locale del rapporto tra carico acuto (ultimi 7 giorni) e cronico (ultimi 28 giorni).
  - Identificazione dello sweet spot (0.8 - 1.3) e attivazione di alert perentorio sopra 1.5 ("danger zone") con prescrizione automatica di scarico o sessione a basso impatto articolare (MTB).
* **3. Tracciamento Usura Scarpe (Gear Mileage Tracking):**
  - Monitoraggio chilometrico delle scarpe da corsa (tramite associazione Garmin o registro via bot `/scarpe`).
  - Soglia di usura e alert preventivo ricalibrati a 400-500 km (rispetto agli standard 700-800 km) a causa dell'elevato impatto al suolo del peso corporeo (96 kg).

### FASE 11: Visual Charting & Multimodalità Telegram (Grafici & Note Vocali)
*Obiettivo:* Arricchire il feedback del Coach con sintesi grafiche immediate e consentire all'atleta di inviare sensazioni soggettive vocali post-allenamento.
* **1. Generazione Grafici Telemetrici Locali (`matplotlib`):**
  - Script locale leggero per generare immagini PNG sintetiche da inviare su Telegram prima del report testuale:
    - Grafico a barre degli split chilometrici (passo vs target 5:35 min/km e FC media sovrapposta).
    - Distribuzione percentuale delle 5 zone cardio.
    - Correlazione Cadenza vs Passo nel corso della seduta.
* **2. Elaborazione Note Vocali Post-Corsa (RPE & Feedback Soggettivo):**
  - Gestione messaggi vocali Telegram (`filters.VOICE`) con download temporaneo del file audio `.ogg`.
  - Trascrizione e analisi multimodale diretta tramite `google-genai` per estrarre sensazioni di fatica, RPE percepito (1-10) e fastidi muscolari/articolari, incrociandoli con la telemetria oggettiva.

### FASE 12: Routine Automatizzate & Debriefing (Daily Briefing & Weekly Digest)
*Obiettivo:* Rendere la presenza del coach continua e proattiva con comunicazioni pianificate all'inizio e alla fine della settimana.
* **1. Daily Briefing Mattutino:**
  - Job periodico Telegram (es. ore 07:00) che notifica la seduta del giorno da `piano_allenamento.txt`, le condizioni meteo previste e una direttiva operativa chiave.
* **2. Weekly Digest Domenicale:**
  - Sintesi cumulativa domenicale: volume chilometrico settimanale vs target, tempo totale, dislivello, bilancio cross-training (km corsa vs ore MTB/palestra), trend ponderale e pagellino riassuntivo del Coach con le priorità della settimana successiva.

### FASE 13: Predizione Agonistica (VDOT / Riegel) & Riprogrammazione Dinamica
*Obiettivo:* Monitorare scientificamente l'avvicinamento alla Mezza delle Terre Verdiane (21.097 km) e adattare il piano in caso di imprevisti.
* **1. Race Predictor Mezza Maratona:**
  - Calcolo dinamico del tempo stimato e del passo gara mezza maratona applicando le formule di Riegel e le tabelle VDOT sui dati delle sessioni di medio e lungo e sul trend del peso corporeo.
  - Verifica della sostenibilità del target 5:35 min/km (1h57m) con indicazione del margine di sicurezza o del rischio di crollo nel finale di gara.
* **2. Riprogrammazione Dinamica del Piano:**
  - Comando `/riprogramma` o suggerimento automatico se una seduta chiave viene saltata o posticipata, con ricalcolo ottimizzato dei giorni rimanenti della settimana senza sacrificare il recupero.

### FASE 14: Data Portability & Healthcheck Sessione
*Obiettivo:* Garantire la resilienza operativa del bot e il pieno possesso dei dati da parte dell'atleta.
* **1. Comando `/esporta`:**
  - Generazione ed invio diretto in chat Telegram di un export completo (CSV/JSON/ZIP) con storico sedute, lap telemetrici, log peso e direttive.
* **2. Healthcheck Preventivo Token Garmin:**
  - Verifica periodica dello stato di validità dei token OAuth memorizzati in `~/.garmin_tokens`, con notifica tempestiva su Telegram in caso di sessione prossima alla scadenza prima del fallimento dei job di polling.
