"""
debate.py - Orchestratore del Multi-Agent Debate (Fase 4).

Architettura:
- Agente 1 (Il Fisiologo - Avvocato Difensore): analisi biologica, metabolica, peso (96kg), drift cardiaco ed EF.
- Agente 2 (Il Tattico di Pista - Accusatore Rigido): geometria corsa, split, target 5:35, pause, zero scuse.
- Agente 3 (Head Coach - Giudice Supremo): contraddittorio sui dati reali e verdetto finale in 4 punti.

Round 1: Esecuzione parallela (Fisiologo + Tattico) via asyncio.gather().
Round 2: Sintesi e verdetto del Giudice.
Include fallback automatico al prompt coach tradizionale in caso di imprevisti.
"""

import asyncio
import time
from pathlib import Path

import httpx
from google import genai
from google.genai import errors as genai_errors
from google.genai import types

from src.config import GEMINI_API_KEY, GEMINI_MODELS, MAX_ATTEMPTS, PROMPTS_DIR


def load_prompt_file(filename: str) -> str:
    """Carica un file di prompt dalla cartella prompts/."""
    file_path = PROMPTS_DIR / filename
    if not file_path.exists():
        raise FileNotFoundError(f"Prompt non trovato: {file_path}")
    with open(file_path, "r", encoding="utf-8") as f:
        return f.read().strip()


def _get_client() -> genai.Client:
    """Crea e restituisce il client ufficiale google-genai."""
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY non trovata: controlla il file .env")
    return genai.Client(
        api_key=GEMINI_API_KEY,
        http_options=types.HttpOptions(timeout=60_000),
    )


async def call_model_with_fallback(
    system_instruction: str,
    user_content: str,
    temperature: float = 0.5,
    agent_name: str = "Agente",
) -> str:
    """Chiama Gemini provando i modelli in sequenza con retry esponenziale.

    Esegue la chiamata sincrona SDK tramite asyncio.to_thread per consentire
    l'esecuzione parallela non bloccante.
    """
    client = _get_client()
    models = [m.strip() for m in GEMINI_MODELS.split(",") if m.strip()]
    config = types.GenerateContentConfig(
        system_instruction=system_instruction,
        temperature=temperature,
    )

    last_error = None
    for model in models:
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                print(f"[{agent_name}] Chiamo Gemini ({model}), tentativo {attempt}/{MAX_ATTEMPTS}...")
                response = await asyncio.to_thread(
                    client.models.generate_content,
                    model=model,
                    contents=user_content,
                    config=config,
                )
                if response and response.text:
                    return response.text
                raise RuntimeError(f"Risposta vuota ricevuta da {model}")

            except genai_errors.ClientError as e:
                # 404 = modello non disponibile, 429 = quota esaurita: skip immediato
                if getattr(e, "code", None) in (404, 429):
                    print(
                        f"[{agent_name}] Modello {model} non disponibile (errore {e.code}). "
                        "Passo al modello successivo."
                    )
                    last_error = e
                    break
                raise
            except (
                genai_errors.ServerError,
                httpx.TimeoutException,
                httpx.TransportError,
                Exception,
            ) as e:
                last_error = e
                if attempt < MAX_ATTEMPTS:
                    wait = 5 * 2 ** (attempt - 1)
                    print(
                        f"[{agent_name}] Errore transitorio ({model}, {e}). "
                        f"Riprovo tra {wait}s..."
                    )
                    await asyncio.sleep(wait)
                else:
                    print(
                        f"[{agent_name}] Tentativi esauriti per {model}. "
                        "Passo al modello successivo."
                    )

    raise last_error or RuntimeError(f"[{agent_name}] Tutti i modelli hanno fallito.")


async def run_multi_agent_debate(
    training_data: str,
    training_plan: str,
    history: str,
) -> str:
    """Esegue l'intero dibattito multi-agente a due round:

    1. Round 1: Il Fisiologo e Il Tattico analizzano contemporaneamente i dati.
    2. Spacing di sicurezza per rispettare il rate limit del Free Tier (15 RPM).
    3. Round 2: Il Giudice Supremo legge dati reali + le due tesi contrapposte ed emette il verdetto finale.
    """
    fisiologo_prompt = load_prompt_file("fisiologo_system.md")
    tattico_prompt = load_prompt_file("tattico_system.md")
    giudice_prompt = load_prompt_file("giudice_system.md")

    # Contesto comune per il Round 1
    debate_input = (
        f"--- STORICO ALLENAMENTI RECENTI ---\n{history}\n\n"
        f"--- PIANO DI ALLENAMENTO ---\n{training_plan}\n\n"
        f"--- DATI TELEMETRICI DELLA SESSIONE ---\n{training_data}"
    )

    print("\n🥊 [Debate] Avvio Round 1 in parallelo: Fisiologo (Difesa) vs Tattico (Accusa)...")

    # Round 1 in parallelo
    results = await asyncio.gather(
        call_model_with_fallback(
            system_instruction=fisiologo_prompt,
            user_content=debate_input,
            temperature=0.6,
            agent_name="Fisiologo",
        ),
        call_model_with_fallback(
            system_instruction=tattico_prompt,
            user_content=debate_input,
            temperature=0.4,
            agent_name="Tattico",
        ),
        return_exceptions=True,
    )

    tesi_fisiologo = results[0]
    tesi_tattico = results[1]

    # Verifica esito Round 1
    if isinstance(tesi_fisiologo, Exception):
        print(f"⚠️ Errore tesi Fisiologo: {tesi_fisiologo}")
        tesi_fisiologo = "Tesi fisiologica non disponibile per errore tecnico."
    else:
        print("✅ [Debate] Tesi del Fisiologo completata.")

    if isinstance(tesi_tattico, Exception):
        print(f"⚠️ Errore tesi Tattico: {tesi_tattico}")
        tesi_tattico = "Requisitoria tattica non disponibile per errore tecnico."
    else:
        print("✅ [Debate] Requisitoria del Tattico completata.")

    # ── STAMPA DI DEBUG A TERMINALE ──────────────────────────────────────
    print("\n" + "=" * 70)
    print("🔬 [DEBUG TERMINALE] ANALISI AGENTE 1 (IL FISIOLOGO):")
    print("=" * 70)
    print(tesi_fisiologo)
    print("=" * 70)

    print("\n" + "=" * 70)
    print("⏱️ [DEBUG TERMINALE] ANALISI AGENTE 2 (IL TATTICO):")
    print("=" * 70)
    print(tesi_tattico)
    print("=" * 70 + "\n")
    # ─────────────────────────────────────────────────────────────────────

    # Spacing protettivo per il Free Tier (15 RPM)
    await asyncio.sleep(2)

    # Costruzione contesto per il Round 2 (Giudice)
    judge_input = (
        f"=== DATI REALI DELLA SESSIONE (TELEMETRIA E METEO) ===\n{training_data}\n\n"
        f"=== PIANO DI ALLENAMENTO ===\n{training_plan}\n\n"
        f"=== STORICO ALLENAMENTI ===\n{history}\n\n"
        f"=== ANALISI TECNICA INTERNA 1 (ASPETTI METABOLICI E FISIOLOGICI) ===\n{tesi_fisiologo}\n\n"
        f"=== ANALISI TECNICA INTERNA 2 (ASPETTI TATTICI E GEOMETRIA CORSA) ===\n{tesi_tattico}\n\n"
        "Ora produci il tuo verdetto e report operativo finale per l'atleta. "
        "RICORDA: parla direttamente come unico Head Coach. NON citare e NON fare alcun "
        "riferimento alle analisi interne, al Fisiologo, al Tattico o al dibattito."
    )

    print("\n⚖️ [Debate] Avvio Round 2: L'Head Coach (Giudice Supremo) valuta il dibattito...")
    verdetto_giudice = await call_model_with_fallback(
        system_instruction=giudice_prompt,
        user_content=judge_input,
        temperature=0.5,
        agent_name="HeadCoach-Giudice",
    )
    print("✅ [Debate] Verdetto finale emesso con successo.")

    return verdetto_giudice
