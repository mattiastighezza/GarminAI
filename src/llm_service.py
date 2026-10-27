"""
llm_service.py - Integrazione con Google Gemini per l'analisi AI.

Gestisce la catena di fallback multi-modello, il retry esponenziale
e il caricamento del system prompt da file esterno.
"""

import time

import httpx
from google import genai
from google.genai import errors as genai_errors
from google.genai import types

from src.config import GEMINI_API_KEY, GEMINI_MODELS, MAX_ATTEMPTS, PROMPTS_DIR


def _load_system_prompt() -> str:
    """Carica il system prompt dal file esterno prompts/coach_system.md."""
    prompt_file = PROMPTS_DIR / "coach_system.md"
    if not prompt_file.exists():
        raise FileNotFoundError(
            f"System prompt non trovato: {prompt_file}\n"
            "Verifica che il file prompts/coach_system.md esista nella root del progetto."
        )
    with open(prompt_file, "r", encoding="utf-8") as f:
        return f.read().strip()


def analyze_with_gemini(
    training_data: str, training_plan: str, history: str
) -> str:
    """Invia i dati dell'allenamento a Gemini e restituisce l'analisi testuale.

    Prova i modelli in ordine di priorità con retry esponenziale sugli
    errori transitori e skip immediato su 404/429.
    """
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY non trovata: controlla il file .env")

    client = genai.Client(
        api_key=GEMINI_API_KEY,
        http_options=types.HttpOptions(timeout=60_000),
    )

    system_instruction = _load_system_prompt()

    full_contents = (
        f"--- STORICO ALLENAMENTI E FEEDBACK PRECEDENTI ---\n{history}\n\n"
        f"--- PIANO DI ALLENAMENTO ---\n{training_plan}\n\n"
        f"--- DATI COMPLETI ALLENAMENTO ODIERNO ---\n{training_data}"
    )

    models = [m.strip() for m in GEMINI_MODELS.split(",") if m.strip()]

    config = types.GenerateContentConfig(
        system_instruction=system_instruction,
        temperature=0.5,
    )

    last_error = None
    for model in models:
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                print(f"Chiamo Gemini ({model}), tentativo {attempt}/{MAX_ATTEMPTS}...")
                response = client.models.generate_content(
                    model=model,
                    contents=full_contents,
                    config=config,
                )
                return response.text
            except genai_errors.ClientError as e:
                # 404 = modello non disponibile, 429 = quota esaurita:
                # inutile riprovare, passa al modello successivo.
                if getattr(e, "code", None) in (404, 429):
                    print(
                        f"Modello {model} non utilizzabile (errore {e.code}). "
                        "Passo al successivo."
                    )
                    last_error = e
                    break
                raise
            except (
                genai_errors.ServerError,
                httpx.TimeoutException,
                httpx.TransportError,
            ) as e:
                last_error = e
                if attempt < MAX_ATTEMPTS:
                    wait = 5 * 2 ** (attempt - 1)
                    print(
                        f"Gemini ({model}) non disponibile "
                        f"(tentativo {attempt}/{MAX_ATTEMPTS}). Riprovo tra {wait}s..."
                    )
                    time.sleep(wait)
                else:
                    print(
                        f"Gemini ({model}) ancora non disponibile. "
                        "Passo al modello successivo."
                    )

    raise last_error
