"""
config.py - Configurazione centralizzata e costanti di progetto.

Carica le variabili d'ambiente dal .env e definisce tutti i path e i
default usati nel resto dell'applicazione.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

# ── Directory di base del progetto (la cartella che contiene /src) ──────────
BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

# ── Path dei file di persistenza ───────────────────────────────────────────
LAST_ACTIVITY_FILE = os.path.expanduser("~/.garmin_last_id.txt")
TOKEN_DIR = os.path.expanduser("~/.garmin_tokens")
PIANO_FILE = BASE_DIR / "piano_allenamento.txt"
STORICO_FILE = BASE_DIR / "storico_allenamenti.md"
PROFILO_FILE = BASE_DIR / "profilo_atleta.json"
PROMPTS_DIR = BASE_DIR / "prompts"

# ── Garmin ─────────────────────────────────────────────────────────────────
GARMIN_EMAIL = os.environ.get("GARMIN_EMAIL")
GARMIN_PASSWORD = os.environ.get("GARMIN_PASSWORD")

# ── Gemini ─────────────────────────────────────────────────────────────────
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
DEFAULT_MODELS = "gemini-3.5-flash,gemini-3.8-flash,gemini-3.7-flash,gemini-3.1-flash-lite,gemini-2.5-flash"
GEMINI_MODELS = os.environ.get("GEMINI_MODELS", DEFAULT_MODELS)
MAX_ATTEMPTS = 3  # tentativi per modello in caso di errore transitorio

# ── Telegram ───────────────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
