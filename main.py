"""
main.py - Entry point dell'applicazione GarminAI.

Orchestratore principale: recupera le nuove attività da Garmin,
le analizza tramite il Multi-Agent Debate (Gemini) e invia il report su Telegram.
Supporta il flag '--mock' per testare la pipeline offline a costo zero.
"""

import sys

from src.garmin_client import init_garmin, get_new_activities
from src.llm_service import analyze_with_gemini
from src.notifier import send_telegram_message
from src.storage import (
    get_training_plan,
    read_history,
    update_history,
    save_last_activity_id,
)
from src.telemetry import build_activity_data


def main() -> None:
    is_mock = "--mock" in sys.argv
    is_bot = "--bot" in sys.argv

    if is_bot:
        from src.bot import run_bot
        run_bot(is_mock=is_mock)
        return

    if is_mock:
        print("🧪 [MOCK MODE] Avvio con dataset locale (mock_data/running_activity.json)...")
        from src.mock_client import MockGarminClient
        garmin = MockGarminClient()
        new_activities = garmin.get_activities()
    else:
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

        print(f"Nuova attività di corsa {activity_id} trovata. Analisi con Gemini Debate...")
        storico = read_history()

        # Esegue il Multi-Agent Debate a 3 agenti (Fisiologo vs Tattico -> Head Coach)
        analisi = analyze_with_gemini(full_training_data, piano_allenamento, storico)

        messaggio = (
            "🏃‍♂️ Nuovo Allenamento Rilevato\n\n"
            f"{telegram_header}\n\n"
            f"🤖 Analisi AI:\n{analisi}"
        )

        if is_mock:
            print("\n" + "=" * 70)
            print("🏁 REPORT FINALE DEL COACH (SIMULAZIONE MOCK):")
            print("=" * 70)
            print(messaggio)
            print("=" * 70 + "\n")
            # In modalità mock prova a notificare Telegram se configurato, senza bloccare il flusso
            try:
                send_telegram_message(messaggio)
                print("📨 Notifica Telegram inviata anche in modalità mock.")
            except Exception as e:
                print(f"ℹ️ Invio Telegram saltato in modalità mock ({e}).")
            print(f"✅ Test mock completato per attività {activity_id}. (Puntatore di produzione non modificato)")
        else:
            print("Analisi ricevuta. Invio su Telegram...")
            send_telegram_message(messaggio)

            # Salva dati completi e feedback nello storico
            update_history(activity_id, full_training_data, analisi)

            # Salva l'ID dell'attività per non riprocessarla più ai successivi avvii
            save_last_activity_id(activity_id)

            print(f"Report inviato, storico aggiornato e ID {activity_id} segnato come elaborato.")


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
