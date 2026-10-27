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
