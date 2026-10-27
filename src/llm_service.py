"""
llm_service.py - Integrazione con Google Gemini per l'analisi AI.

Gestisce la catena di fallback multi-modello, il retry esponenziale
e l'orchestrazione del Multi-Agent Debate (Fase 4: Fisiologo vs Tattico vs Giudice).
"""

import asyncio
import time

import httpx
from google import genai
from google.genai import errors as genai_errors
from google.genai import types

from src.config import GEMINI_API_KEY, GEMINI_MODELS, MAX_ATTEMPTS, PROMPTS_DIR
from src.debate import run_multi_agent_debate


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


def _analyze_single_agent_fallback(
    training_data: str, training_plan: str, history: str
) -> str:
    """Fallback monolitico su singolo agente nel caso di fallimento del debate."""
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
                print(f"Fallback Coach ({model}), tentativo {attempt}/{MAX_ATTEMPTS}...")
                response = client.models.generate_content(
                    model=model,
                    contents=full_contents,
                    config=config,
                )
                if response and response.text:
                    return response.text
            except genai_errors.ClientError as e:
                if getattr(e, "code", None) in (404, 429):
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
                    time.sleep(wait)

    raise last_error or RuntimeError("Fallback single-agent fallito su tutti i modelli.")


async def analyze_with_gemini_async(
    training_data: str, training_plan: str, history: str
) -> str:
    """Esegue l'analisi asincrona tramite Multi-Agent Debate con fallback automatico."""
    try:
        return await run_multi_agent_debate(training_data, training_plan, history)
    except Exception as e:
        print(f"⚠️ Multi-Agent Debate non riuscito ({e}). Attivazione fallback a coach singolo...")
        return await asyncio.to_thread(
            _analyze_single_agent_fallback, training_data, training_plan, history
        )


def analyze_with_gemini(
    training_data: str, training_plan: str, history: str
) -> str:
    """Interfaccia principale sincrona: lancia il Multi-Agent Debate gestendo l'event loop."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        # Se siamo già dentro un event loop attivo (es. bot Telegram o worker asincrono)
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(
                asyncio.run,
                analyze_with_gemini_async(training_data, training_plan, history)
            ).result()
    else:
        return asyncio.run(
            analyze_with_gemini_async(training_data, training_plan, history)
        )
