"""
garmin_client.py - Autenticazione e fetch attività da Garmin Connect.
"""

import os

from garminconnect import Garmin

from src.config import GARMIN_EMAIL, GARMIN_PASSWORD, LAST_ACTIVITY_FILE, TOKEN_DIR


def init_garmin() -> Garmin:
    """Inizializza il client Garmin riutilizzando i token OAuth salvati."""
    if not GARMIN_EMAIL or not GARMIN_PASSWORD:
        raise RuntimeError(
            "GARMIN_EMAIL / GARMIN_PASSWORD non trovati: controlla il file .env"
        )

    print(f"Login Garmin con l'email: {GARMIN_EMAIL}")

    client = Garmin(
        GARMIN_EMAIL,
        GARMIN_PASSWORD,
        prompt_mfa=lambda: input("Codice MFA Garmin: "),
    )
    client.login(TOKEN_DIR)
    return client


def get_new_activities(client: Garmin) -> list[dict]:
    """Restituisce le attività successive all'ultima elaborata.

    Scarica le ultime 5 attività per gestire caricamenti multipli.
    Se il file last_id non esiste restituisce solo la più recente.
    """
    activities = client.get_activities(0, 5)
    if not activities:
        return []

    last_id = None
    if os.path.exists(LAST_ACTIVITY_FILE):
        with open(LAST_ACTIVITY_FILE, "r") as f:
            last_id = f.read().strip()

    # Ordine cronologico: dalla più vecchia alla più recente
    activities.reverse()

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

    # Se last_id non trovato tra le ultime 5, le elabora tutte
    if not found_last:
        return activities

    return new_activities


def import_historical_activities(client: Garmin, count: int) -> int:
    """Scarica e memorizza le ultime N attività in formato sintetico nello storico.
    
    Operazione quota-safe (nessuna chiamata a Gemini). Aggiorna anche LAST_ACTIVITY_FILE
    all'attività più recente per evitare di riprocessarla.
    """
    if count <= 0:
        return 0

    activities = client.get_activities(0, count)
    if not activities:
        return 0

    # Ordine cronologico: dalla più vecchia alla più recente
    activities.reverse()

    from src.config import STORICO_FILE
    from src.storage import save_last_activity_id
    from src.telemetry import format_pace, format_seconds

    lines = []
    for act in activities:
        act_id = str(act.get("activityId"))
        act_name = act.get("activityName", "Attività")
        act_type = (act.get("activityType") or {}).get("typeKey", "unknown")
        start_time = act.get("startTimeLocal", "N/D")
        dist_km = (act.get("distance") or 0) / 1000
        dur_s = act.get("duration") or 0
        avg_speed = act.get("averageSpeed") or 0
        pace = format_pace(avg_speed)
        avg_hr = act.get("averageHR", "N/D")
        load = act.get("activityTrainingLoad", "N/D")
        if isinstance(load, (int, float)):
            load = f"{load:.0f}"

        lines.append(
            f"- [{start_time}] {act_name} ({act_type}): {dist_km:.2f} km in {format_seconds(dur_s)} | "
            f"Passo: {pace} | FC: {avg_hr} bpm | Load: {load} (ID: {act_id})"
        )

    # Scrive nello storico
    with open(STORICO_FILE, "a", encoding="utf-8") as f:
        f.write("## Import Storico Pregresso (Onboarding)\n" + "\n".join(lines) + "\n\n---\n\n")

    # Aggiorna last_activity_id con l'attività più recente
    last_act_id = str(activities[-1].get("activityId"))
    save_last_activity_id(last_act_id)

    return len(lines)
