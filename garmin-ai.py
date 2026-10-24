import os
import requests
from datetime import timedelta
from garminconnect import Garmin
from google import genai
from google.genai import types

# File per memorizzare l'ID dell'ultima attività elaborata
LAST_ACTIVITY_FILE = os.path.expanduser("~/.garmin_last_id.txt")

def init_garmin():
    email = os.environ.get("GARMIN_EMAIL")
    password = os.environ.get("GARMIN_PASSWORD")
    token_dir = os.path.expanduser("~/.garmin_tokens")
    
    client = Garmin(email, password)
    client.login(token_store=token_dir)
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
            last_saved_id = f.read().strip()
            if act_id == last_saved_id:
                return None, None  # Nessuna nuova attività

    act_type = last_act.get("activityType", {}).get("typeKey", "Sconosciuta")
    distance_km = last_act.get("distance", 0) / 1000
    duration_s = last_act.get("duration", 0)
    avg_hr = last_act.get("averageHR", "N/D")
    max_hr = last_act.get("maxHR", "N/D")
    avg_speed = last_act.get("averageSpeed", 0)
    
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
    client = genai.Client()
    system_instruction = (
        "Sei un preparatore atletico esperto. "
        "L'utente si sta preparando per la Mezza delle Terre Verdiane con un passo target di 5:35 min/km "
        "e alterna corsa su strada a uscite in mountain bike. "
        "Analizza le metriche, valuta lo sforzo e fornisci un feedback tecnico e conciso (massimo 3 frasi)."
    )
    
    response = client.models.generate_content(
        model='gemini-2.5-flash',
        contents=training_data,
        config=types.GenerateContentConfig(
            system_instruction=system_instruction,
            temperature=0.7,
        )
    )
    return response.text

def send_telegram_message(text):
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
    
    response = requests.post(url, json=payload)
    response.raise_for_status()

if __name__ == "__main__":
    try:
        garmin = init_garmin()
        dati_allenamento, activity_id = get_new_activity_prompt(garmin)
        
        if dati_allenamento:
            analisi = analyze_with_gemini(dati_allenamento)
            
            messaggio = (
                f"🏃‍♂️ *Nuovo Allenamento Rilevato*\n\n"
                f"{dati_allenamento}\n"
                f"🤖 *Analisi AI:*\n{analisi}"
            )
            
            send_telegram_message(messaggio)
            
            # Aggiorna il file con il nuovo ID solo dopo l'invio riuscito
            with open(LAST_ACTIVITY_FILE, "w") as f:
                f.write(activity_id)
                
            print(f"Report inviato per l'attività {activity_id}.")
        else:
            print("Nessun nuovo allenamento da notificare.")
            
    except Exception as e:
        print(f"Errore: {e}")