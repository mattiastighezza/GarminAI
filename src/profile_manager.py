"""
profile_manager.py - Gestione persistenza e validazione del profilo atleta.

Salva e carica i dati anagrafici e fisiologici da 'profilo_atleta.json',
supporta aggiornamenti puntuali (es. peso, altezza, soglie FC, passo target, piano),
calcola l'IMC (Indice di Massa Corporea) e il trend del peso corporeo, e genera
la rappresentazione testuale sia per Telegram che per i prompt di Gemini.
"""

from datetime import datetime
import json
import re
from typing import Any

from src.config import PROFILO_FILE

# Parametri di default
DEFAULT_PROFILE: dict[str, Any] = {
    "eta": 31,
    "peso_kg": 96.0,
    "peso_iniziale_kg": 96.0,
    "altezza_m": 1.85,
    "fc_max": 202,
    "safc": 178,
    "passo_target": "5:35 min/km",
    "obiettivo_gara": "Mezza delle Terre Verdiane (21.097 km)",
    "onboarding_completato": False,
    "ultimo_aggiornamento": None,
}


def load_profile() -> dict[str, Any]:
    """Carica il profilo atleta da file JSON. Se assente, lo inizializza con i default."""
    if not PROFILO_FILE.exists():
        profile = DEFAULT_PROFILE.copy()
        profile["ultimo_aggiornamento"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        save_profile(profile)
        return profile

    try:
        with open(PROFILO_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        print(f"⚠️ Errore lettura {PROFILO_FILE}: {e}. Ricreo profilo di fallback.")
        data = {}

    # Assicura presenza di tutte le chiavi minime (compatibilità in avanti)
    updated = False
    for k, v in DEFAULT_PROFILE.items():
        if k not in data:
            data[k] = v
            updated = True

    if updated:
        save_profile(data)

    return data


def save_profile(profile: dict[str, Any]) -> None:
    """Salva il profilo atleta su disco formattato in JSON."""
    profile["ultimo_aggiornamento"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(PROFILO_FILE, "w", encoding="utf-8") as f:
        json.dump(profile, f, indent=2, ensure_ascii=False)


def update_field(key: str, value: Any) -> dict[str, Any]:
    """Aggiorna un singolo parametro del profilo e persiste le modifiche."""
    profile = load_profile()
    profile[key] = value
    save_profile(profile)
    return profile


def compute_bmi(peso_kg: float, altezza_m: float) -> tuple[float, str]:
    """Calcola l'Indice di Massa Corporea (IMC = kg / m^2) e la classe di peso."""
    if not altezza_m or altezza_m <= 0:
        return 0.0, "N/D"
    bmi = peso_kg / (altezza_m ** 2)
    if bmi < 18.5:
        categoria = "Sottopeso"
    elif bmi < 25.0:
        categoria = "Normopeso"
    elif bmi < 30.0:
        categoria = "Sovrappeso"
    else:
        categoria = "Obesità"
    return round(bmi, 1), categoria


def parse_weight(val: str) -> float | None:
    """Valida ed estrae il peso corporeo (supporta virgola/punto, range 40-200 kg)."""
    cleaned = val.strip().replace(",", ".").lower().replace("kg", "").strip()
    try:
        weight = float(cleaned)
        if 40.0 <= weight <= 200.0:
            return round(weight, 1)
        return None
    except ValueError:
        return None


def parse_height(val: str) -> float | None:
    """Valida ed estrae l'altezza in metri (supporta es. '1.85', '1,85', '185', '185cm')."""
    cleaned = val.strip().replace(",", ".").lower().replace("cm", "").replace("m", "").strip()
    try:
        num = float(cleaned)
        # Se espresso in centimetri (es. 185)
        if 120.0 <= num <= 230.0:
            return round(num / 100.0, 2)
        # Se espresso già in metri (es. 1.85)
        if 1.20 <= num <= 2.30:
            return round(num, 2)
        return None
    except ValueError:
        return None


def parse_age(val: str) -> int | None:
    """Valida ed estrae l'età (range 15-100 anni)."""
    cleaned = val.strip().replace("anni", "").strip()
    try:
        age = int(cleaned)
        if 15 <= age <= 100:
            return age
        return None
    except ValueError:
        return None


def parse_hr_thresholds(val: str) -> tuple[int | None, int | None]:
    """Estrae FC Max e Soglia Anaerobica (SAFC) rispettando rigorosamente l'ordine posizionale.
    
    Regola tassativa:
    - 1° valore = FC Max (frequenza cardiaca massima, 100-240 bpm)
    - 2° valore = SAFC (soglia anaerobica, 80-220 bpm)
    Nessun riordinamento automatico o min/max.
    """
    nums = [int(n) for n in re.findall(r"\b\d{2,3}\b", val)]
    if not nums:
        return None, None

    fc_max = None
    safc = None

    # Il primo numero inserito è SEMPRE la FC Max
    if len(nums) >= 1:
        val_max = nums[0]
        if 100 <= val_max <= 240:
            fc_max = val_max

    # Il secondo numero inserito è SEMPRE la SAFC
    if len(nums) >= 2:
        val_safc = nums[1]
        if 80 <= val_safc <= 220:
            safc = val_safc

    return fc_max, safc


def parse_fc_max(val: str) -> int | None:
    """Valida ed estrae la frequenza cardiaca massima (FC Max, range 100-240 bpm)."""
    nums = [int(n) for n in re.findall(r"\b\d{2,3}\b", val)]
    if nums and 100 <= nums[0] <= 240:
        return nums[0]
    return None


def parse_safc(val: str) -> int | None:
    """Valida ed estrae la Soglia Anaerobica (SAFC, range 80-220 bpm)."""
    nums = [int(n) for n in re.findall(r"\b\d{2,3}\b", val)]
    if nums and 80 <= nums[0] <= 220:
        return nums[0]
    return None


def parse_step1_inputs(text: str) -> tuple[int | None, float | None, float | None]:
    """Estrae età, altezza e peso.
    
    Supporta:
    - 3 valori: '31, 1.85, 96' oppure '31, 185, 96' (Età, Altezza, Peso)
    - 2 valori: '31, 96' (Età e Peso, altezza mantenuta)
    """
    parts = [p.strip() for p in re.split(r"[,;]+", text) if p.strip()]
    if not parts:
        parts = text.split()

    if len(parts) >= 3:
        age = parse_age(parts[0])
        height = parse_height(parts[1])
        weight = parse_weight(parts[2])
        return age, height, weight

    if len(parts) == 2:
        age = parse_age(parts[0])
        weight = parse_weight(parts[1])
        return age, None, weight

    return None, None, None


def format_profile_summary(profile: dict[str, Any] | None = None) -> str:
    """Restituisce una stringa leggibile ed elegante con la scheda completa dell'atleta."""
    p = profile or load_profile()
    eta = p.get("eta", "N/D")
    peso = p.get("peso_kg", "N/D")
    peso_ini = p.get("peso_iniziale_kg", peso)
    alt = p.get("altezza_m", 1.85)
    fc_max = p.get("fc_max", "N/D")
    safc = p.get("safc", "N/D")
    target = p.get("passo_target", "N/D")
    gara = p.get("obiettivo_gara", "N/D")
    status_onb = "✅ Completato" if p.get("onboarding_completato") else "⏳ Da completare"

    # Calcolo IMC
    bmi_str = "N/D"
    if isinstance(peso, (int, float)) and isinstance(alt, (int, float)):
        bmi_val, bmi_cat = compute_bmi(float(peso), float(alt))
        bmi_str = f"{bmi_val} ({bmi_cat})"

    # Calcolo Trend Peso da inizio monitoraggio
    trend_str = ""
    if isinstance(peso, (int, float)) and isinstance(peso_ini, (int, float)):
        delta_tot = round(float(peso) - float(peso_ini), 1)
        if delta_tot != 0:
            trend_str = f" [Trend: {delta_tot:+.1f} kg da inizio]"

    return (
        "📋 SCHEDA PROFILO ATLETA\n"
        "───────────────────────\n"
        f"👤 Età: {eta} anni\n"
        f"📏 Altezza: {alt} m\n"
        f"⚖️ Peso Corporeo: {peso} kg{trend_str}\n"
        f"📊 Indice Massa Corporea (IMC): {bmi_str}\n"
        f"❤️ Soglie FC: Max {fc_max} bpm | Soglia SAFC {safc} bpm\n"
        f"🎯 Obiettivo Gara: {gara}\n"
        f"⚡ Passo Target Gara: {target}\n"
        f"🕒 Ultimo Aggiornamento: {p.get('ultimo_aggiornamento', 'N/D')}\n"
        f"🚀 Stato Onboarding: {status_onb}\n"
        "───────────────────────"
    )


def get_profile_prompt_context(profile: dict[str, Any] | None = None) -> str:
    """Formatta i dati del profilo per l'iniezione dinamica nei prompt di Gemini."""
    p = profile or load_profile()
    peso = p.get("peso_kg", 96.0)
    alt = p.get("altezza_m", 1.85)
    fc_max = p.get("fc_max", 202)
    safc = p.get("safc", 178)
    bmi_val, bmi_cat = compute_bmi(float(peso), float(alt)) if alt else (0, "N/D")

    return (
        "=== PROFILO ATLETA & PARAMETRI DINAMICI ===\n"
        f"Età: {p.get('eta', 31)} anni | Altezza: {alt} m | Peso Corporeo Attuale: {peso} kg (IMC: {bmi_val} - {bmi_cat})\n"
        f"Frequenza Cardiaca Massima (FC Max): {fc_max} bpm | Soglia Anaerobica (SAFC): {safc} bpm\n"
        f"Gara Obiettivo: {p.get('obiettivo_gara', 'Mezza delle Terre Verdiane')}\n"
        f"Passo Target Gara: {p.get('passo_target', '5:35 min/km')}\n"
        "DIRETTIVA VINCOLANTE PER GLI AGENTI:\n"
        "Utilizza SEMPRE e UNICAMENTE i valori correnti sopra specificati (peso, altezza, FC Max, SAFC, passo target). "
        "Adatta il calcolo del costo metabolico al km (+35-40% rispetto a un runner di 70 kg proporzionato alla massa reale), "
        "la dispersione termica, l'impatto biomeccanico articolare (GCT e oscillazione verticale) e la valutazione delle zone cardiache "
        "rigorosamente sulla base di questa scheda dinamica."
    )


def reset_profile() -> dict[str, Any]:
    """Resetta il profilo ai valori di default consentendo un nuovo onboarding."""
    profile = DEFAULT_PROFILE.copy()
    profile["onboarding_completato"] = False
    save_profile(profile)
    return profile
