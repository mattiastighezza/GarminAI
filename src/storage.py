"""
storage.py - Persistenza locale: piano di allenamento, storico e last activity ID.
"""

import os

from src.config import LAST_ACTIVITY_FILE, PIANO_FILE, STORICO_FILE


def get_training_plan() -> str:
    """Legge il piano di allenamento da file. Restituisce un fallback se assente."""
    if PIANO_FILE.exists():
        with open(PIANO_FILE, "r", encoding="utf-8") as f:
            return f.read().strip()
    return "Nessun piano di allenamento fornito. Valuta la sessione isolatamente."


def read_history() -> str:
    """Legge gli ultimi 6000 caratteri dello storico allenamenti."""
    if STORICO_FILE.exists():
        with open(STORICO_FILE, "r", encoding="utf-8") as f:
            return f.read()[-6000:]
    return "Nessun allenamento precedente registrato."


def update_history(act_id: str, full_data: str, feedback: str) -> None:
    """Appende una nuova sessione (dati + analisi AI) allo storico."""
    with open(STORICO_FILE, "a", encoding="utf-8") as f:
        f.write(
            f"## Attività {act_id}\n"
            f"{full_data}\n\n"
            f"**Analisi Coach:**\n{feedback}\n\n"
            f"---\n\n"
        )


def save_last_activity_id(act_id: str) -> None:
    """Salva l'ID dell'ultima attività elaborata con successo."""
    with open(LAST_ACTIVITY_FILE, "w") as f:
        f.write(act_id)


def get_last_activity_id() -> str | None:
    """Legge l'ID dell'ultima attività elaborata. None se il file non esiste."""
    if os.path.exists(LAST_ACTIVITY_FILE):
        with open(LAST_ACTIVITY_FILE, "r") as f:
            return f.read().strip() or None
    return None
