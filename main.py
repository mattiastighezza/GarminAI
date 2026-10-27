"""
main.py - Entry point dell'applicazione GarminAI.

Orchestratore principale: recupera le nuove attività da Garmin,
le analizza tramite Gemini e invia il report su Telegram.
"""

import sys

from src.garmin_client import init_garmin, get_new_activities
from src.llm_service import analyze_with_gemini
from src.notifier import send_telegram_message
from src.storage import get_training_plan, read_history, update_history
from src.telemetry import build_activity_data


def main() -> None:
    garmin = init_garmin()
    print("Login Garmin OK. Leggo le ultime attività...")
    new_activities = get_new_activities(garmin)

    if not new_activities:
        print("Nessun nuovo allenamento da notificare.")
        return

    piano_allenamento = get_training_plan()

    for act in new_activities:
        telegram_header, full_training_data, activity_id, act_type = (
            build_activity_data(garmin, act)
        )

        if not full_training_data:
            print(
                f"Attività {activity_id} ignorata (tipo: {act_type}, "
                "non è 'running')."
            )
            continue

        print(f"Nuova attività di corsa {activity_id} trovata. Analisi con Gemini...")
        storico = read_history()

        # Se Gemini fallisce l'eccezione sale: nessun invio e nessun
        # salvataggio dell'ID, così l'attività viene riprovata al prossimo avvio.
        analisi = analyze_with_gemini(full_training_data, piano_allenamento, storico)

        messaggio = (
            "🏃‍♂️ Nuovo Allenamento Rilevato\n\n"
            f"{telegram_header}\n\n"
            f"🤖 Analisi AI:\n{analisi}"
        )

        print("Analisi ricevuta. Invio su Telegram...")
        send_telegram_message(messaggio)

        # Salva dati completi e feedback nello storico
        update_history(activity_id, full_training_data, analisi)

        print(f"Report inviato e storico aggiornato per l'attività {activity_id}.")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\nErrore: {e}")
        print(
            "L'attività NON è stata segnata come elaborata: "
            "verrà riprovata al prossimo avvio."
        )
        sys.exit(1)
