import os
import sys
import time
from datetime import timedelta
from pathlib import Path

import httpx
import requests
from dotenv import load_dotenv
from garminconnect import Garmin
from google import genai
from google.genai import errors as genai_errors
from google.genai import types

# Carica il .env dalla cartella dello script (non dalla cartella corrente)
BASE_DIR = Path(__file__).parent
load_dotenv(BASE_DIR / ".env")

# File per memorizzare l'ID dell'ultima attività elaborata, token, piano e storico
LAST_ACTIVITY_FILE = os.path.expanduser("~/.garmin_last_id.txt")
TOKEN_DIR = os.path.expanduser("~/.garmin_tokens")
PIANO_FILE = BASE_DIR / "piano_allenamento.txt"
STORICO_FILE = BASE_DIR / "storico_allenamenti.md"

# Modelli Gemini provati in ordine: se uno e' sovraccarico/non disponibile passa al successivo
DEFAULT_MODELS = "gemini-3.5-flash,gemini-3.8-flash,gemini-3.7-flash,gemini-3.1-flash-lite,gemini-2.5-flash"
MAX_ATTEMPTS = 3  # tentativi per modello in caso di 503


def init_garmin():
    email = os.environ.get("GARMIN_EMAIL")
    password = os.environ.get("GARMIN_PASSWORD")
    if not email or not password:
        raise RuntimeError(
            "GARMIN_EMAIL / GARMIN_PASSWORD non trovati: controlla il file .env"
        )

    print(f"Login Garmin con l'email: {email}")

    # Se esistono token salvati li usa, altrimenti fa il login completo
    # (e chiede il codice MFA da tastiera, se attivo sul tuo account).
    client = Garmin(email, password, prompt_mfa=lambda: input("Codice MFA Garmin: "))
    client.login(TOKEN_DIR)
    return client


def get_training_plan():
    if PIANO_FILE.exists():
        with open(PIANO_FILE, "r", encoding="utf-8") as f:
            return f.read().strip()
    return "Nessun piano di allenamento fornito. Valuta la sessione isolatamente."


def read_history():
    if STORICO_FILE.exists():
        with open(STORICO_FILE, "r", encoding="utf-8") as f:
            # Ultimi 6000 caratteri per fornire contesto storico senza appesantire il prompt
            return f.read()[-6000:]
    return "Nessun allenamento precedente registrato."


def update_history(act_id, full_data, feedback):
    with open(STORICO_FILE, "a", encoding="utf-8") as f:
        f.write(
            f"## Attività {act_id}\n"
            f"{full_data}\n\n"
            f"**Analisi Coach:**\n{feedback}\n\n"
            f"---\n\n"
        )


def format_pace(speed_m_s):
    if not speed_m_s or speed_m_s <= 0:
        return "N/D"
    pace_min = (1000 / speed_m_s) / 60
    mins = int(pace_min)
    secs = int(round((pace_min - mins) * 60))
    if secs == 60:
        mins += 1
        secs = 0
    return f"{mins}:{secs:02d} min/km"


def format_seconds(seconds):
    if seconds is None:
        return "N/D"
    return str(timedelta(seconds=int(round(seconds))))


def get_new_activities(client):
    # Scarica le ultime 5 attività per gestire eventuali caricamenti multipli
    activities = client.get_activities(0, 5)
    if not activities:
        return []

    last_id = None
    if os.path.exists(LAST_ACTIVITY_FILE):
        with open(LAST_ACTIVITY_FILE, "r") as f:
            last_id = f.read().strip()

    # Invertiamo l'ordine: dalla più vecchia alla più recente
    activities.reverse()

    # Se il file last_id non esiste (o è vuoto durante i test), restituisce solo l'ultima attività
    if not last_id:
        return [activities[-1]]

    new_activities = []
    found_last = False
    for act in activities:
        act_id = str(act.get("activityId"))
        if act_id == last_id:
            found_last = True
            continue
        if found_last:
            new_activities.append(act)

    # Se last_id era presente ma più vecchio delle ultime 5 attività, le elabora tutte
    if not found_last:
        return activities

    return new_activities


def fetch_extra_details(client, act_id):
    extra_lines = []

    # 1. Meteo della sessione
    try:
        weather = client.get_activity_weather(act_id)
        if isinstance(weather, dict) and weather:
            temp_f = weather.get("temp")
            # Garmin spesso restituisce la temperatura in Fahrenheit nel payload weather
            temp_c = f"{(temp_f - 32) * 5 / 9:.1f}°C" if isinstance(temp_f, (int, float)) else "N/D"
            apparent_f = weather.get("apparentTemp")
            app_c = f"{(apparent_f - 32) * 5 / 9:.1f}°C" if isinstance(apparent_f, (int, float)) else "N/D"
            rh = weather.get("relativeHumidity", "N/D")
            wind_speed = weather.get("windSpeed", "N/D")
            cond = (weather.get("weatherTypeDTO") or {}).get("desc", "N/D")
            extra_lines.append(
                f"=== METEO ===\n"
                f"Condizioni: {cond} | Temp: {temp_c} (Percepita: {app_c}) | Umidità: {rh}% | Vento: {wind_speed}"
            )
    except Exception as e:
        extra_lines.append(f"=== METEO ===\nNon disponibile ({e})")

    # 2. Tempo nelle Zone Cardio
    try:
        hr_zones = client.get_activity_hr_in_timezones(act_id)
        if isinstance(hr_zones, list) and hr_zones:
            zone_strs = []
            total_zone_secs = sum(z.get("secsInZone", 0) for z in hr_zones) or 1
            for z in sorted(hr_zones, key=lambda x: x.get("zoneNumber", 0)):
                z_num = z.get("zoneNumber", "?")
                secs = z.get("secsInZone", 0)
                low_hr = z.get("zoneLowBoundary", "?")
                pct = (secs / total_zone_secs) * 100
                zone_strs.append(f"  - Zona {z_num} (>={low_hr} bpm): {format_seconds(secs)} ({pct:.1f}%)")
            extra_lines.append("=== TEMPO NELLE ZONE CARDIO ===\n" + "\n".join(zone_strs))
    except Exception as e:
        extra_lines.append(f"=== TEMPO NELLE ZONE CARDIO ===\nNon disponibile ({e})")

    # 3. Intermedi / Lap (Splits)
    try:
        splits_data = client.get_activity_splits(act_id)
        laps = (splits_data or {}).get("lapDTOs", []) if isinstance(splits_data, dict) else []
        if laps:
            lap_strs = []
            for idx, lap in enumerate(laps, start=1):
                dist_m = lap.get("distance") or 0
                dur_s = lap.get("duration") or 0
                spd = lap.get("averageSpeed") or 0
                l_pace = format_pace(spd)
                l_hr = lap.get("averageHR", "N/D")
                l_max_hr = lap.get("maxHR", "N/D")
                l_cad = lap.get("averageRunCadence", "N/D")
                if isinstance(l_cad, float):
                    l_cad = f"{l_cad:.0f}"
                l_pwr = lap.get("averagePower", "N/D")
                l_elev_gain = lap.get("elevationGain", 0) or 0
                l_elev_loss = lap.get("elevationLoss", 0) or 0
                l_gct = lap.get("groundContactTime", "N/D")
                l_stride = lap.get("strideLength", "N/D")
                if isinstance(l_stride, (int, float)):
                    l_stride = f"{l_stride:.1f}cm"

                lap_strs.append(
                    f"  Lap {idx:02d}: {dist_m/1000:.2f}km in {format_seconds(dur_s)} | "
                    f"Passo: {l_pace} | FC: {l_hr}/{l_max_hr} bpm | "
                    f"Cad: {l_cad} spm | Falcata: {l_stride} | GCT: {l_gct}ms | "
                    f"Pot: {l_pwr}W | D+/D-: +{l_elev_gain:.0f}/-{l_elev_loss:.0f}m"
                )
            extra_lines.append("=== DETTAGLIO LAP / INTERMEDI ===\n" + "\n".join(lap_strs))
    except Exception as e:
        extra_lines.append(f"=== DETTAGLIO LAP / INTERMEDI ===\nNon disponibile ({e})")

    return "\n\n".join(extra_lines)


def build_activity_data(client, act):
    act_id = str(act.get("activityId"))
    act_type = (act.get("activityType") or {}).get("typeKey", "Sconosciuta")

    # Filtro: elabora solo le attività di corsa
    #if act_type != "running":
        #return None, None, act_id, act_type

    act_name = act.get("activityName", "Corsa")
    start_time = act.get("startTimeLocal", "N/D")

    # Durate e Distanza
    distance_km = (act.get("distance") or 0) / 1000
    duration_s = act.get("duration") or 0
    moving_s = act.get("movingDuration") or duration_s
    elapsed_s = act.get("elapsedDuration") or duration_s
    pause_s = max(0, elapsed_s - duration_s)

    # Velocità e Passo
    avg_speed = act.get("averageSpeed") or 0
    max_speed = act.get("maxSpeed") or 0
    pace_str = format_pace(avg_speed)
    max_pace_str = format_pace(max_speed)

    # Cardio
    avg_hr = act.get("averageHR", "N/D")
    max_hr = act.get("maxHR", "N/D")

    # Altimetria
    elev_gain = act.get("elevationGain")
    elev_loss = act.get("elevationLoss")
    min_elev = act.get("minElevation")
    max_elev = act.get("maxElevation")

    # Dinamiche di corsa
    avg_cad = act.get("averageRunningCadenceInStepsPerMinute")
    max_cad = act.get("maxRunningCadenceInStepsPerMinute")
    stride_cm = act.get("avgStrideLength")
    vert_osc = act.get("avgVerticalOscillation")
    vert_ratio = act.get("avgVerticalRatio")
    gct = act.get("avgGroundContactTime")
    gct_bal = act.get("avgGroundContactBalance")
    steps = act.get("steps", "N/D")

    # Potenza
    avg_pwr = act.get("avgPower", "N/D")
    max_pwr = act.get("maxPower", "N/D")
    norm_pwr = act.get("normPower", "N/D")

    # Fisiologia e Carico
    aer_te = act.get("aerobicTrainingEffect", "N/D")
    anaer_te = act.get("anaerobicTrainingEffect", "N/D")
    te_label = act.get("trainingEffectLabel", "N/D")
    load = act.get("activityTrainingLoad", "N/D")
    vo2max = act.get("vO2MaxValue", "N/D")
    calories = act.get("calories", "N/D")
    water_ml = act.get("waterEstimated", "N/D")

    # Formattazione sicura valori numerici opzionali
    cad_str = f"{avg_cad:.0f} spm (Max: {max_cad:.0f})" if isinstance(avg_cad, (int, float)) and isinstance(max_cad, (int, float)) else f"{avg_cad or 'N/D'} spm"
    stride_str = f"{stride_cm:.1f} cm" if isinstance(stride_cm, (int, float)) else "N/D"
    osc_str = f"{vert_osc:.1f} cm" if isinstance(vert_osc, (int, float)) else "N/D"
    vratio_str = f"{vert_ratio:.1f}%" if isinstance(vert_ratio, (int, float)) else "N/D"
    gct_str = f"{gct:.0f} ms" if isinstance(gct, (int, float)) else "N/D"
    gct_bal_str = f"{gct_bal:.1f}% L / {100 - gct_bal:.1f}% R" if isinstance(gct_bal, (int, float)) else "N/D"
    elev_str = f"+{elev_gain:.0f}m / -{elev_loss:.0f}m" if isinstance(elev_gain, (int, float)) and isinstance(elev_loss, (int, float)) else "N/D"
    quota_str = f"Min {min_elev:.0f}m / Max {max_elev:.0f}m" if isinstance(min_elev, (int, float)) and isinstance(max_elev, (int, float)) else "N/D"
    load_str = f"{load:.0f}" if isinstance(load, (int, float)) else str(load)

    # Riepilogo compatto per l'intestazione del messaggio Telegram
    telegram_header = (
        f"📌 {act_name} ({start_time})\n"
        f"📏 Distanza: {distance_km:.2f} km | ⏱️ Durata: {format_seconds(duration_s)} (Pause: {format_seconds(pause_s)})\n"
        f"⚡ Passo medio: {pace_str} ({avg_speed * 3.6:.1f} km/h)\n"
        f"❤️ FC: {avg_hr} bpm (Max: {max_hr} bpm)\n"
        f"🦶 Cadenza: {cad_str} | Falcata: {stride_str}\n"
        f"⛰️ Dislivello: {elev_str} | ⚡ Potenza: {avg_pwr}W (NP: {norm_pwr}W)\n"
        f"📈 Training Effect: {te_label} (Aer: {aer_te} / Anaer: {anaer_te}) | Load: {load_str} | VO2Max: {vo2max}"
    )

    # Scarica i dati avanzati extra (Meteo, Zone HR, Laps)
    print(f"Scarico dati avanzati extra (Lap, Zone Cardio, Meteo) per l'attività {act_id}...")
    extra_details = fetch_extra_details(client, act_id)

    # Contesto completo ed esaustivo per Gemini e per il file storico .md
    full_prompt_context = (
        f"=== RIEPILOGO GENERALE ===\n"
        f"Nome Attività: {act_name}\n"
        f"Data e Ora Inizio: {start_time}\n"
        f"Tipo Allenamento: {act_type}\n"
        f"Distanza: {distance_km:.2f} km\n"
        f"Durata Timer Attivo: {format_seconds(duration_s)}\n"
        f"Durata in Movimento: {format_seconds(moving_s)}\n"
        f"Durata Totale (Elapsed): {format_seconds(elapsed_s)} (Tempo in pausa: {format_seconds(pause_s)})\n"
        f"Passo Medio: {pace_str} ({avg_speed * 3.6:.1f} km/h) | Passo Picco: {max_pace_str}\n"
        f"Dislivello: {elev_str} | Quota: {quota_str}\n\n"
        f"=== FISIOLOGIA E CARICO ===\n"
        f"FC Media: {avg_hr} bpm | FC Max: {max_hr} bpm\n"
        f"Training Effect Label: {te_label}\n"
        f"Training Effect Aerobico: {aer_te} | Anaerobico: {anaer_te}\n"
        f"Training Load Acuto: {load_str}\n"
        f"VO2Max Stimato: {vo2max}\n"
        f"Calorie: {calories} kcal | Sudorazione stimata: {water_ml} ml\n\n"
        f"=== BIOMECCANICA, DINAMICHE DI CORSA E POTENZA ===\n"
        f"Cadenza: {cad_str} | Passi Totali: {steps}\n"
        f"Lunghezza Media Falcata: {stride_str}\n"
        f"Oscillazione Verticale: {osc_str} | Rapporto Verticale: {vratio_str}\n"
        f"Tempo Contatto con il Suolo (GCT): {gct_str} | Bilanciamento GCT: {gct_bal_str}\n"
        f"Potenza Media: {avg_pwr} W | Potenza Normalizzata (NP): {norm_pwr} W | Potenza Max: {max_pwr} W\n\n"
        f"{extra_details}"
    )

    return telegram_header, full_prompt_context, act_id, act_type


def analyze_with_gemini(training_data, training_plan, history):
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY non trovata: controlla il file .env")

    client = genai.Client(
        api_key=api_key,
        http_options=types.HttpOptions(timeout=60_000),  # millisecondi
    )

    system_instruction = (
        "Agisci come un allenatore di atletica severo, esigente, analitico e orientato ai risultati. "
        "Non essere accondiscendente e non fare complimenti gratuiti. "
        "L'atleta (31 anni, 1.85m, 96 kg) si sta preparando per la Mezza delle Terre Verdiane con un passo target di 5:35 min/km "
        "e alterna corsa su strada a uscite in mountain bike. "
        "Riceverai lo storico degli allenamenti precedenti, il piano di allenamento previsto e tutte le metriche avanzate della sessione odierna "
        "(inclusi lap chilometrici, tempo nelle zone cardio, dinamiche di corsa, potenza, pause ed condizioni meteo). "
        "Individua nel piano l'allenamento corrispondente e confrontalo rigorosamente con quanto eseguito. "
        "Fornisci un feedback tecnico strutturato:\n"
        "1) Aderenza al piano e gestione pause: valuta se passo, distanza, distribuzione nelle zone cardio ed eventuali pause (elapsed vs duration) rispettano la seduta prevista.\n"
        "2) Analisi fisiologica e tenuta dei Lap: valuta l'andamento dei singoli lap (regolarità, positive/negative split, tenuta delle ripetute) e calcola la deriva cardiaca tra la prima e la seconda metà in relazione a passo, dislivello e meteo.\n"
        "3) Analisi biomeccanica: valuta cadenza, falcata, tempo di contatto al suolo (GCT), oscillazione verticale e potenza in relazione al peso dell'atleta (96 kg).\n"
        "4) Direttiva operativa: cosa correggere tassativamente nella prossima uscita basandoti anche sul confronto con lo storico."
    )

    full_contents = (
        f"--- STORICO ALLENAMENTI E FEEDBACK PRECEDENTI ---\n{history}\n\n"
        f"--- PIANO DI ALLENAMENTO ---\n{training_plan}\n\n"
        f"--- DATI COMPLETI ALLENAMENTO ODIERNO ---\n{training_data}"
    )

    # Elenco di modelli da provare in ordine (separati da virgola, configurabile nel .env)
    models_env = os.environ.get("GEMINI_MODELS", DEFAULT_MODELS)
    models = [m.strip() for m in models_env.split(",") if m.strip()]

    config = types.GenerateContentConfig(
        system_instruction=system_instruction,
        temperature=0.5,
    )

    last_error = None
    for model in models:
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                print(f"Chiamo Gemini ({model}), tentativo {attempt}/{MAX_ATTEMPTS}...")
                response = client.models.generate_content(
                    model=model,
                    contents=full_contents,
                    config=config,
                )
                return response.text
            except genai_errors.ClientError as e:
                # 404 = modello non disponibile, 429 = quota esaurita / non abilitato:
                # inutile riprovare, passa al modello successivo.
                if getattr(e, "code", None) in (404, 429):
                    print(f"Modello {model} non utilizzabile (errore {e.code}). Passo al successivo.")
                    last_error = e
                    break
                raise
            except (genai_errors.ServerError, httpx.TimeoutException, httpx.TransportError) as e:
                # 500/503: sovraccarico temporaneo, riprova con attesa crescente
                last_error = e
                if attempt < MAX_ATTEMPTS:
                    wait = 5 * 2 ** (attempt - 1)
                    print(f"Gemini ({model}) non disponibile (tentativo {attempt}/{MAX_ATTEMPTS}). Riprovo tra {wait}s...")
                    time.sleep(wait)
                else:
                    print(f"Gemini ({model}) ancora non disponibile. Passo al modello successivo.")

    raise last_error


def send_telegram_message(text):
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not bot_token or not chat_id:
        raise RuntimeError("TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID non trovati nel .env")

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"

    # Telegram ha un limite rigido di 4096 caratteri per singolo messaggio:
    # se il report è molto lungo lo spezza in blocchi per non far fallire l'invio.
    max_len = 4000
    chunks = [text[i:i + max_len] for i in range(0, len(text), max_len)]

    for chunk in chunks:
        # Testo semplice, senza parse_mode: caratteri come "_" (es. mountain_biking)
        # o "*" nel testo dell'AI farebbero fallire il Markdown di Telegram.
        payload = {"chat_id": chat_id, "text": chunk}

        response = requests.post(url, json=payload, timeout=30)
        if not response.ok:
            # Non usare raise_for_status(): stamperebbe l'URL con il token del bot.
            try:
                motivo = response.json().get("description", response.text)
            except ValueError:
                motivo = response.text
            raise RuntimeError(f"Telegram ha risposto {response.status_code}: {motivo}")


if __name__ == "__main__":
    try:
        garmin = init_garmin()
        print("Login Garmin OK. Leggo le ultime attività...")
        new_activities = get_new_activities(garmin)

        if not new_activities:
            print("Nessun nuovo allenamento da notificare.")
            sys.exit(0)

        piano_allenamento = get_training_plan()

        for act in new_activities:
            telegram_header, full_training_data, activity_id, act_type = build_activity_data(garmin, act)

            if not full_training_data:
                print(f"Attività {activity_id} ignorata (tipo: {act_type}, non è 'running').")
                # Aggiorna comunque l'ID per non rielaborare questa attività non-running al prossimo avvio
                #with open(LAST_ACTIVITY_FILE, "w") as f:
                    #f.write(activity_id)
                continue

            print(f"Nuova attività di corsa {activity_id} trovata. Analisi con Gemini...")
            storico = read_history()

            # Se Gemini fallisce l'eccezione sale al blocco except finale: nessun invio
            # e nessun salvataggio dell'ID, cosi' l'attivita' viene riprovata al prossimo avvio.
            analisi = analyze_with_gemini(full_training_data, piano_allenamento, storico)

            messaggio = (
                "🏃‍♂️ Nuovo Allenamento Rilevato\n\n"
                f"{telegram_header}\n\n"
                f"🤖 Analisi AI:\n{analisi}"
            )

            print("Analisi ricevuta. Invio su Telegram...")
            send_telegram_message(messaggio)

            # Salva tutti i dati completi (inclusi lap e zone) e il feedback nello storico .md
            update_history(activity_id, full_training_data, analisi)

            # Aggiorna il file con il nuovo ID solo dopo l'invio riuscito
            #with open(LAST_ACTIVITY_FILE, "w") as f:
                #f.write(activity_id)

            print(f"Report inviato e storico aggiornato per l'attività {activity_id}.")

    except Exception as e:
        print(f"\nErrore: {e}")
        print("L'attività NON è stata segnata come elaborata: verrà riprovata al prossimo avvio.")
        sys.exit(1)