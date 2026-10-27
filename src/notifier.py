"""
notifier.py - Invio notifiche su Telegram.
"""

import requests

from src.config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID


def send_telegram_message(text: str) -> None:
    """Invia un messaggio su Telegram, spezzandolo in chunk da ≤4000 caratteri.

    Non usa parse_mode per evitare errori con caratteri speciali (_, *, ecc.)
    presenti nel testo generato dall'AI.
    """
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID non trovati nel .env"
        )

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"

    max_len = 4000
    chunks = [text[i : i + max_len] for i in range(0, len(text), max_len)]

    for chunk in chunks:
        payload = {"chat_id": TELEGRAM_CHAT_ID, "text": chunk}
        response = requests.post(url, json=payload, timeout=30)

        if not response.ok:
            # Non usare raise_for_status(): stamperebbe l'URL con il token del bot.
            try:
                motivo = response.json().get("description", response.text)
            except ValueError:
                motivo = response.text
            raise RuntimeError(
                f"Telegram ha risposto {response.status_code}: {motivo}"
            )
