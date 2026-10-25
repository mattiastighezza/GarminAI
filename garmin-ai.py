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
load_dotenv(Path(__file__).parent / ".env")

# File per memorizzare l'ID dell'ultima attività elaborata
LAST_ACTIVITY_FILE = os.path.expanduser("~/.garmin_last_id.txt")
TOKEN_DIR = os.path.expanduser("~/.garmin_tokens")

# Modelli Gemini provati in ordine: se uno e' sovraccarico/non disponibile passa al successivo
DEFAULT_MODELS = "gemini-3.5-flash,gemini-3.8-flash,gemini-3.7-flash,gemini-3.1-flash-lite"
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


def get_new_activity_prompt(client):
    activities = client.get_activities(0, 1)
    if not activities:
        return None, None

    last_act = activities[0]
    act_id = str(last_act.get("activityId"))

    # Controllo se l'attività è già stata elaborata
    if os.path.exists(LAST_ACTIVITY_FILE):
        with open(LAST_ACTIVITY_FILE, "r") as f:
            if act_id == f.read().strip():
                return None, None  # Nessuna nuova attività

    act_type = (last_act.get("activityType") or {}).get("typeKey", "Sconosciuta")
    distance_km = (last_act.get("distance") or 0) / 1000
    duration_s = last_act.get("duration") or 0
    avg_hr = last_act.get("averageHR", "N/D")
    max_hr = last_act.get("maxHR", "N/D")
    avg_speed = last_act.get("averageSpeed") or 0

    pace_str = "N/D"
    if avg_speed > 0:
        pace_min = (1000 / avg_speed) / 60
        pace_str = f"{int(pace_min)}:{int((pace_min % 1) * 60):02d} min/km"

    time_str = str(timedelta(seconds=int(duration_s)))

    prompt_context = (
        f"Tipo Allenamento: {act_type}\n"
        f"Distanza: {distance_km:.2f} km\n"
        f"Durata: {time_str}\n"
        f"Passo/Velocità media: {pace_str} (o {avg_speed * 3.6:.1f} km/h)\n"
        f"FC Media: {avg_hr} bpm\n"
        f"FC Max: {max_hr} bpm\n"
    )

    return prompt_context, act_id


def analyze_with_gemini(training_data):
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY non trovata: controlla il file .env")

    client = genai.Client(
        api_key=api_key,
        http_options=types.HttpOptions(timeout=60_000),  # millisecondi
    )

    system_instruction = (
        "Sei un preparatore atletico esperto. "
        "L'utente si sta preparando per la Mezza delle Terre Verdiane con un passo target di 5:35 min/km "
        "e alterna corsa su strada a uscite in mountain bike. "
        "Analizza le metriche, valuta lo sforzo e fornisci un feedback tecnico e conciso (massimo 3 frasi)."
    )

    # Elenco di modelli da provare in ordine (separati da virgola, configurabile nel .env)
    models_env = os.environ.get("GEMINI_MODELS", DEFAULT_MODELS)
    models = [m.strip() for m in models_env.split(",") if m.strip()]

    config = types.GenerateContentConfig(
        system_instruction=system_instruction,
        temperature=0.7,
    )

    last_error = None
    for model in models:
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                print(f"Chiamo Gemini ({model}), tentativo {attempt}/{MAX_ATTEMPTS}...")
                response = client.models.generate_content(
                    model=model,
                    contents=training_data,
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
    # Testo semplice, senza parse_mode: caratteri come "_" (es. mountain_biking)
    # o "*" nel testo dell'AI farebbero fallire il Markdown di Telegram.
    payload = {"chat_id": chat_id, "text": text}

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
        print("Login Garmin OK. Leggo l'ultima attività...")
        dati_allenamento, activity_id = get_new_activity_prompt(garmin)

        if dati_allenamento:
            print(f"Nuova attività {activity_id} trovata. Analisi con Gemini...")
            # Se Gemini fallisce l'eccezione sale al blocco except finale: nessun invio
            # e nessun salvataggio dell'ID, cosi' l'attivita' viene riprovata al prossimo avvio.
            analisi = analyze_with_gemini(dati_allenamento)

            messaggio = (
                "🏃‍♂️ Nuovo Allenamento Rilevato\n\n"
                f"{dati_allenamento}\n"
                f"🤖 Analisi AI:\n{analisi}"
            )

            print("Analisi ricevuta. Invio su Telegram...")
            send_telegram_message(messaggio)

            # Aggiorna il file con il nuovo ID solo dopo l'invio riuscito
            #with open(LAST_ACTIVITY_FILE, "w") as f:
                #f.write(activity_id)

            print(f"Report inviato per l'attività {activity_id}.")
        else:
            print("Nessun nuovo allenamento da notificare.")

    except Exception as e:
        print(f"\nErrore: {e}")
        print("L'attività NON è stata segnata come elaborata: verrà riprovata al prossimo avvio.")
        sys.exit(1)