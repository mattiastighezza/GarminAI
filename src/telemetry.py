"""
telemetry.py - Estrazione, formattazione e calcolo metriche telemetriche.

Contiene le funzioni di conversione (velocità → passo, secondi → durata),
l'estrazione dei dettagli avanzati (meteo, zone HR, lap) e il calcolo
matematico locale della deriva cardiaca / Efficiency Factor.
"""

from datetime import timedelta

from garminconnect import Garmin


# ── Funzioni di formattazione ──────────────────────────────────────────────


def format_pace(speed_m_s: float) -> str:
    """Converte una velocità in m/s in passo min/km."""
    if not speed_m_s or speed_m_s <= 0:
        return "N/D"
    pace_min = (1000 / speed_m_s) / 60
    mins = int(pace_min)
    secs = int(round((pace_min - mins) * 60))
    if secs == 60:
        mins += 1
        secs = 0
    return f"{mins}:{secs:02d} min/km"


def format_seconds(seconds: float | None) -> str:
    """Converte un valore in secondi in una stringa h:mm:ss."""
    if seconds is None:
        return "N/D"
    return str(timedelta(seconds=int(round(seconds))))


# ── Calcolo Deriva Cardiaca & Efficiency Factor ───────────────────────────


def compute_cardiac_drift(laps: list[dict]) -> dict | None:
    """Calcola la deriva cardiaca confrontando la prima e la seconda metà dei lap.

    Restituisce un dizionario con i dati della deriva, oppure None se i dati
    non sono sufficienti per il calcolo.
    """
    valid_laps = [
        lap for lap in laps
        if lap.get("averageHR") and lap.get("averageSpeed")
    ]
    if len(valid_laps) < 2:
        return None

    mid = len(valid_laps) // 2
    first_half = valid_laps[:mid]
    second_half = valid_laps[mid:]

    def _weighted_avg(lap_list: list[dict], key: str) -> float:
        """Media pesata sulla durata di ciascun lap."""
        total_dur = sum(lap.get("duration", 0) for lap in lap_list) or 1
        return sum(
            lap.get(key, 0) * (lap.get("duration", 0) / total_dur)
            for lap in lap_list
        )

    hr_first = _weighted_avg(first_half, "averageHR")
    hr_second = _weighted_avg(second_half, "averageHR")
    pace_first = _weighted_avg(first_half, "averageSpeed")
    pace_second = _weighted_avg(second_half, "averageSpeed")

    # Efficiency Factor = velocità (m/min) / FC
    ef_first = (pace_first * 60 / hr_first) if hr_first else 0
    ef_second = (pace_second * 60 / hr_second) if hr_second else 0

    drift_pct = ((hr_second - hr_first) / hr_first * 100) if hr_first else 0
    ef_change_pct = ((ef_second - ef_first) / ef_first * 100) if ef_first else 0

    return {
        "hr_first_half": round(hr_first, 1),
        "hr_second_half": round(hr_second, 1),
        "drift_pct": round(drift_pct, 1),
        "ef_first_half": round(ef_first, 3),
        "ef_second_half": round(ef_second, 3),
        "ef_change_pct": round(ef_change_pct, 1),
        "pace_first_half": format_pace(pace_first),
        "pace_second_half": format_pace(pace_second),
    }


# ── Estrazione dettagli extra ─────────────────────────────────────────────


def fetch_extra_details(client: Garmin, act_id: str) -> str:
    """Scarica e formatta meteo, zone cardio e lap per un'attività."""
    extra_lines = []

    # 1. Meteo della sessione
    try:
        weather = client.get_activity_weather(act_id)
        if isinstance(weather, dict) and weather:
            temp_f = weather.get("temp")
            temp_c = (
                f"{(temp_f - 32) * 5 / 9:.1f}°C"
                if isinstance(temp_f, (int, float))
                else "N/D"
            )
            apparent_f = weather.get("apparentTemp")
            app_c = (
                f"{(apparent_f - 32) * 5 / 9:.1f}°C"
                if isinstance(apparent_f, (int, float))
                else "N/D"
            )
            rh = weather.get("relativeHumidity", "N/D")
            wind_speed = weather.get("windSpeed", "N/D")
            cond = (weather.get("weatherTypeDTO") or {}).get("desc", "N/D")
            extra_lines.append(
                f"=== METEO ===\n"
                f"Condizioni: {cond} | Temp: {temp_c} (Percepita: {app_c}) | "
                f"Umidità: {rh}% | Vento: {wind_speed}"
            )
    except Exception as e:
        extra_lines.append(f"=== METEO ===\nNon disponibile ({e})")

    # 2. Tempo nelle Zone Cardio
    try:
        hr_zones = client.get_activity_hr_in_timezones(act_id)
        if isinstance(hr_zones, list) and hr_zones:
            zone_strs = []
            total_zone_secs = sum(z.get("secsInZone", 0) for z in hr_zones) or 1
            for z in sorted(hr_zones, key=lambda x: x.get("zoneNumber", 0)):
                z_num = z.get("zoneNumber", "?")
                secs = z.get("secsInZone", 0)
                low_hr = z.get("zoneLowBoundary", "?")
                pct = (secs / total_zone_secs) * 100
                zone_strs.append(
                    f"  - Zona {z_num} (>={low_hr} bpm): {format_seconds(secs)} ({pct:.1f}%)"
                )
            extra_lines.append(
                "=== TEMPO NELLE ZONE CARDIO ===\n" + "\n".join(zone_strs)
            )
    except Exception as e:
        extra_lines.append(f"=== TEMPO NELLE ZONE CARDIO ===\nNon disponibile ({e})")

    # 3. Intermedi / Lap (Splits)
    laps = []
    try:
        splits_data = client.get_activity_splits(act_id)
        laps = (
            (splits_data or {}).get("lapDTOs", [])
            if isinstance(splits_data, dict)
            else []
        )
        if laps:
            lap_strs = []
            for idx, lap in enumerate(laps, start=1):
                dist_m = lap.get("distance") or 0
                dur_s = lap.get("duration") or 0
                spd = lap.get("averageSpeed") or 0
                l_pace = format_pace(spd)
                l_hr = lap.get("averageHR", "N/D")
                l_max_hr = lap.get("maxHR", "N/D")
                l_cad = lap.get("averageRunCadence", "N/D")
                if isinstance(l_cad, float):
                    l_cad = f"{l_cad:.0f}"
                l_pwr = lap.get("averagePower", "N/D")
                l_elev_gain = lap.get("elevationGain", 0) or 0
                l_elev_loss = lap.get("elevationLoss", 0) or 0
                l_gct = lap.get("groundContactTime", "N/D")
                l_stride = lap.get("strideLength", "N/D")
                if isinstance(l_stride, (int, float)):
                    l_stride = f"{l_stride:.1f}cm"

                lap_strs.append(
                    f"  Lap {idx:02d}: {dist_m / 1000:.2f}km in {format_seconds(dur_s)} | "
                    f"Passo: {l_pace} | FC: {l_hr}/{l_max_hr} bpm | "
                    f"Cad: {l_cad} spm | Falcata: {l_stride} | GCT: {l_gct}ms | "
                    f"Pot: {l_pwr}W | D+/D-: +{l_elev_gain:.0f}/-{l_elev_loss:.0f}m"
                )
            extra_lines.append(
                "=== DETTAGLIO LAP / INTERMEDI ===\n" + "\n".join(lap_strs)
            )
    except Exception as e:
        extra_lines.append(f"=== DETTAGLIO LAP / INTERMEDI ===\nNon disponibile ({e})")

    # 4. Calcolo locale della Deriva Cardiaca / Efficiency Factor
    if laps:
        drift = compute_cardiac_drift(laps)
        if drift:
            extra_lines.append(
                "=== DERIVA CARDIACA & EFFICIENCY FACTOR (calcolo locale) ===\n"
                f"  1ª Metà: FC {drift['hr_first_half']} bpm | Passo {drift['pace_first_half']} | EF {drift['ef_first_half']}\n"
                f"  2ª Metà: FC {drift['hr_second_half']} bpm | Passo {drift['pace_second_half']} | EF {drift['ef_second_half']}\n"
                f"  Deriva Cardiaca: {drift['drift_pct']:+.1f}% | Variazione EF: {drift['ef_change_pct']:+.1f}%"
            )

    return "\n\n".join(extra_lines)


# ── Costruzione dati completi attività ─────────────────────────────────────


def build_activity_data(
    client: Garmin, act: dict
) -> tuple[str | None, str | None, str, str]:
    """Costruisce header Telegram e contesto completo per Gemini.

    Restituisce (telegram_header, full_prompt_context, act_id, act_type).
    Se l'attività non genera dati utili restituisce (None, None, act_id, act_type).
    """
    act_id = str(act.get("activityId"))
    act_type = (act.get("activityType") or {}).get("typeKey", "Sconosciuta")
    act_name = act.get("activityName", "Corsa")
    start_time = act.get("startTimeLocal", "N/D")

    # Durate e Distanza
    distance_km = (act.get("distance") or 0) / 1000
    duration_s = act.get("duration") or 0
    moving_s = act.get("movingDuration") or duration_s
    elapsed_s = act.get("elapsedDuration") or duration_s
    pause_s = max(0, elapsed_s - duration_s)

    # Velocità e Passo
    avg_speed = act.get("averageSpeed") or 0
    max_speed = act.get("maxSpeed") or 0
    pace_str = format_pace(avg_speed)
    max_pace_str = format_pace(max_speed)

    # Cardio
    avg_hr = act.get("averageHR", "N/D")
    max_hr = act.get("maxHR", "N/D")

    # Altimetria
    elev_gain = act.get("elevationGain")
    elev_loss = act.get("elevationLoss")
    min_elev = act.get("minElevation")
    max_elev = act.get("maxElevation")

    # Dinamiche di corsa
    avg_cad = act.get("averageRunningCadenceInStepsPerMinute")
    max_cad = act.get("maxRunningCadenceInStepsPerMinute")
    stride_cm = act.get("avgStrideLength")
    vert_osc = act.get("avgVerticalOscillation")
    vert_ratio = act.get("avgVerticalRatio")
    gct = act.get("avgGroundContactTime")
    gct_bal = act.get("avgGroundContactBalance")
    steps = act.get("steps", "N/D")

    # Potenza
    avg_pwr = act.get("avgPower", "N/D")
    max_pwr = act.get("maxPower", "N/D")
    norm_pwr = act.get("normPower", "N/D")

    # Fisiologia e Carico
    aer_te = act.get("aerobicTrainingEffect", "N/D")
    anaer_te = act.get("anaerobicTrainingEffect", "N/D")
    te_label = act.get("trainingEffectLabel", "N/D")
    load = act.get("activityTrainingLoad", "N/D")
    vo2max = act.get("vO2MaxValue", "N/D")
    calories = act.get("calories", "N/D")
    water_ml = act.get("waterEstimated", "N/D")

    # Formattazione sicura valori numerici opzionali
    cad_str = (
        f"{avg_cad:.0f} spm (Max: {max_cad:.0f})"
        if isinstance(avg_cad, (int, float)) and isinstance(max_cad, (int, float))
        else f"{avg_cad or 'N/D'} spm"
    )
    stride_str = f"{stride_cm:.1f} cm" if isinstance(stride_cm, (int, float)) else "N/D"
    osc_str = f"{vert_osc:.1f} cm" if isinstance(vert_osc, (int, float)) else "N/D"
    vratio_str = f"{vert_ratio:.1f}%" if isinstance(vert_ratio, (int, float)) else "N/D"
    gct_str = f"{gct:.0f} ms" if isinstance(gct, (int, float)) else "N/D"
    gct_bal_str = (
        f"{gct_bal:.1f}% L / {100 - gct_bal:.1f}% R"
        if isinstance(gct_bal, (int, float))
        else "N/D"
    )
    elev_str = (
        f"+{elev_gain:.0f}m / -{elev_loss:.0f}m"
        if isinstance(elev_gain, (int, float)) and isinstance(elev_loss, (int, float))
        else "N/D"
    )
    quota_str = (
        f"Min {min_elev:.0f}m / Max {max_elev:.0f}m"
        if isinstance(min_elev, (int, float)) and isinstance(max_elev, (int, float))
        else "N/D"
    )
    load_str = f"{load:.0f}" if isinstance(load, (int, float)) else str(load)

    # Riepilogo compatto per l'intestazione del messaggio Telegram
    telegram_header = (
        f"📌 {act_name} ({start_time})\n"
        f"📏 Distanza: {distance_km:.2f} km | ⏱️ Durata: {format_seconds(duration_s)} (Pause: {format_seconds(pause_s)})\n"
        f"⚡ Passo medio: {pace_str} ({avg_speed * 3.6:.1f} km/h)\n"
        f"❤️ FC: {avg_hr} bpm (Max: {max_hr} bpm)\n"
        f"🦶 Cadenza: {cad_str} | Falcata: {stride_str}\n"
        f"⛰️ Dislivello: {elev_str} | ⚡ Potenza: {avg_pwr}W (NP: {norm_pwr}W)\n"
        f"📈 Training Effect: {te_label} (Aer: {aer_te} / Anaer: {anaer_te}) | Load: {load_str} | VO2Max: {vo2max}"
    )

    # Scarica i dati avanzati extra (Meteo, Zone HR, Laps, Deriva Cardiaca)
    print(
        f"Scarico dati avanzati extra (Lap, Zone Cardio, Meteo, Deriva) per l'attività {act_id}..."
    )
    extra_details = fetch_extra_details(client, act_id)

    # Contesto completo ed esaustivo per Gemini e per il file storico .md
    full_prompt_context = (
        f"=== RIEPILOGO GENERALE ===\n"
        f"Nome Attività: {act_name}\n"
        f"Data e Ora Inizio: {start_time}\n"
        f"Tipo Allenamento: {act_type}\n"
        f"Distanza: {distance_km:.2f} km\n"
        f"Durata Timer Attivo: {format_seconds(duration_s)}\n"
        f"Durata in Movimento: {format_seconds(moving_s)}\n"
        f"Durata Totale (Elapsed): {format_seconds(elapsed_s)} (Tempo in pausa: {format_seconds(pause_s)})\n"
        f"Passo Medio: {pace_str} ({avg_speed * 3.6:.1f} km/h) | Passo Picco: {max_pace_str}\n"
        f"Dislivello: {elev_str} | Quota: {quota_str}\n\n"
        f"=== FISIOLOGIA E CARICO ===\n"
        f"FC Media: {avg_hr} bpm | FC Max: {max_hr} bpm\n"
        f"Training Effect Label: {te_label}\n"
        f"Training Effect Aerobico: {aer_te} | Anaerobico: {anaer_te}\n"
        f"Training Load Acuto: {load_str}\n"
        f"VO2Max Stimato: {vo2max}\n"
        f"Calorie: {calories} kcal | Sudorazione stimata: {water_ml} ml\n\n"
        f"=== BIOMECCANICA, DINAMICHE DI CORSA E POTENZA ===\n"
        f"Cadenza: {cad_str} | Passi Totali: {steps}\n"
        f"Lunghezza Media Falcata: {stride_str}\n"
        f"Oscillazione Verticale: {osc_str} | Rapporto Verticale: {vratio_str}\n"
        f"Tempo Contatto con il Suolo (GCT): {gct_str} | Bilanciamento GCT: {gct_bal_str}\n"
        f"Potenza Media: {avg_pwr} W | Potenza Normalizzata (NP): {norm_pwr} W | Potenza Max: {max_pwr} W\n\n"
        f"{extra_details}"
    )

    return telegram_header, full_prompt_context, act_id, act_type
