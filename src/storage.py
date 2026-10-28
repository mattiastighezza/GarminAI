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


def save_training_plan(text: str) -> None:
    """Salva o aggiorna il testo del piano di allenamento su file."""
    with open(PIANO_FILE, "w", encoding="utf-8") as f:
        f.write(text.strip())


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


def get_last_run_summary() -> str | None:
    """Estrae il testo dell'ultima sessione registrata (dati + report coach) dallo storico."""
    if not STORICO_FILE.exists():
        return None

    with open(STORICO_FILE, "r", encoding="utf-8") as f:
        content = f.read().strip()

    if not content:
        return None

    # Cerca l'ultimo blocco '## Attività '
    parts = content.split("## Attività ")
    if len(parts) > 1:
        last_block = "## Attività " + parts[-1].strip()
        # Se c'è un divisore successivo '---', prendi solo fino a lì
        sub_parts = last_block.split("\n---\n")
        summary = sub_parts[0].strip()
        # Limita la lunghezza a max 3800 caratteri per stare in un unico messaggio Telegram
        if len(summary) > 3800:
            summary = summary[:3800] + "\n\n... (report troncato per lunghezza)"
        return summary

    # Fallback se non ci sono ancora blocchi '## Attività '
    lines = [line for line in content.splitlines() if line.strip()]
    if lines:
        return "\n".join(lines[-25:])

    return None
