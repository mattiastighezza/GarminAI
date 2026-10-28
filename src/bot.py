"""
bot.py - Bot Telegram interattivo per Onboarding e gestione profilo (Fase 1).

Fornisce:
- Tastiera persistente a pulsanti sempre visibile sotto la barra di chat:
  [ 📋 Profilo ] [ 🏃‍♂️ Ultima Run ]
  [ ⚖️ Peso ] [ 📏 Altezza ] [ ❤️ Soglie FC ]
  [ 📋 Piano ] [ ⚡ Target ] [ 📖 Aiuto ]
- Pulsanti Inline interattivi direttamente nei messaggi:
  - Nello Step 2 dell'Onboarding (conferma default cardio o personalizza).
  - Nello Step 3 dell'Onboarding (salta inserimento piano).
  - Nello Step 4 dell'Onboarding (selezione 0, 5, 10 attività storiche).
  - Sotto la scheda /profilo e /start per azioni rapide con un click.
- Flusso guidato di onboarding (/start) con ConversationHandler compatibile con click e testo.
- Comandi rapidi di aggiornamento e consultazione (/peso, /altezza, /fc, /piano, /profilo, /ultimarun).
- Controllo di sicurezza sull'ID mittente (TELEGRAM_CHAT_ID).
"""

import asyncio
import logging
import re
from typing import Any

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    Update,
)
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from src.config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
from src.profile_manager import (
    compute_bmi,
    format_profile_summary,
    load_profile,
    parse_height,
    parse_hr_thresholds,
    parse_step1_inputs,
    parse_weight,
    reset_profile,
    update_field,
)
from src.storage import (
    get_last_run_summary,
    get_training_plan,
    save_training_plan,
)

# Configurazione logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("GarminAIBot")

# Stati della conversazione di onboarding
STEP_BODY, STEP_CARDIO, STEP_PLAN, STEP_HISTORY = range(4)


def is_authorized(chat_id: int | str) -> bool:
    """Verifica che la richiesta provenga dalla chat configurata nel .env."""
    if not TELEGRAM_CHAT_ID:
        return True  # Se non configurato, accetta per facilitare setup iniziale
    return str(chat_id).strip() == str(TELEGRAM_CHAT_ID).strip()


def get_main_keyboard() -> ReplyKeyboardMarkup:
    """Restituisce la tastiera fissa a pulsanti sempre visibile sotto la chat."""
    keyboard = [
        ["📋 Profilo", "🏃‍♂️ Ultima Run"],
        ["⚖️ Peso", "📏 Altezza", "❤️ Soglie FC"],
        ["📋 Piano", "⚡ Target", "📖 Aiuto"],
    ]
    return ReplyKeyboardMarkup(
        keyboard,
        resize_keyboard=True,
        is_persistent=True,
    )


def get_profile_inline_keyboard() -> InlineKeyboardMarkup:
    """Restituisce pulsanti inline cliccabili direttamente sotto la scheda profilo."""
    keyboard = [
        [
            InlineKeyboardButton("⚖️ Aggiorna Peso", callback_data="btn_peso"),
            InlineKeyboardButton("📏 Aggiorna Altezza", callback_data="btn_altezza"),
        ],
        [
            InlineKeyboardButton("❤️ Soglie Cardio", callback_data="btn_fc"),
            InlineKeyboardButton("🏃‍♂️ Ultima Run", callback_data="btn_ultimarun"),
        ],
        [
            InlineKeyboardButton("🔄 Riesegui Onboarding", callback_data="btn_reset_onb"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


# ── HANDLER ONBOARDING (/start) ──────────────────────────────────────────────


async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Entry point per /start: avvia onboarding se non completato, altrimenti mostra scheda."""
    if not is_authorized(update.effective_chat.id):
        await update.message.reply_text(
            "⛔ Accesso non autorizzato. Questo bot è riservato all'atleta titolare."
        )
        return ConversationHandler.END

    profile = load_profile()

    if profile.get("onboarding_completato", False):
        summary = format_profile_summary(profile)
        msg = (
            "👋 Ciao! Il tuo profilo atleta è configurato e attivo.\n\n"
            f"{summary}\n\n"
            "Tocca uno dei pulsanti della tastiera in basso per interagire rapidamente con il coach!"
        )
        await update.message.reply_text(
            msg,
            reply_markup=get_main_keyboard(),
        )
        # Mostra anche i pulsanti inline per azione immediata
        await update.message.reply_text(
            "💡 Azioni rapide con un click:",
            reply_markup=get_profile_inline_keyboard(),
        )
        return ConversationHandler.END

    # Avvio flusso onboarding guidato
    welcome_msg = (
        "🏃‍♂️ Benvenuto nel tuo Garmin AI Coach!\n\n"
        "Configuriamo il tuo profilo atleta in 4 semplici passaggi.\n\n"
        "👉 Step 1/4: Dati Antropometrici\n"
        "Indica la tua età, altezza e peso separati da virgola (es. `58, 1.85, 74` oppure `58, 185cm, 74kg`).\n\n"
        "*(Se ometti l'altezza, es. `58, 74`, verrà mantenuta l'altezza standard di 1.85 m)*\n\n"
        "Digita /annulla in qualsiasi momento per interrompere."
    )
    await update.message.reply_text(welcome_msg, reply_markup=ReplyKeyboardRemove())
    return STEP_BODY


async def step_body_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Step 1: Riceve e valida età, altezza e peso."""
    text = update.message.text or ""
    age, height, weight = parse_step1_inputs(text)

    if age is None or weight is None:
        await update.message.reply_text(
            "⚠️ Formato non riconosciuto.\n"
            "Inserisci almeno età e peso separati da virgola (es. `58, 1.85, 74` o `58, 74`).\n\n"
            "Riprova oppure digita /annulla."
        )
        return STEP_BODY

    update_field("eta", age)
    update_field("peso_kg", weight)
    profile = load_profile()
    if not profile.get("peso_iniziale_kg"):
        update_field("peso_iniziale_kg", weight)

    if height:
        update_field("altezza_m", height)
        alt_str = f"{height} m"
    else:
        alt_str = f"{profile.get('altezza_m', 1.85)} m (predefinita)"

    alt_effettiva = height or profile.get("altezza_m", 1.85)
    bmi_val, bmi_cat = compute_bmi(weight, alt_effettiva)

    # Pulsanti inline visibili direttamente nel messaggio dello Step 2
    inline_kb = [
        [
            InlineKeyboardButton(
                "✅ Usa Default (202 Max, 178 SAFC)", callback_data="cardio_default"
            )
        ],
        [
            InlineKeyboardButton("⏭️ Salta", callback_data="cardio_skip")
        ],
    ]
    reply_markup = InlineKeyboardMarkup(inline_kb)

    msg = (
        f"✅ Dati registrati: {age} anni | {alt_str} | {weight} kg (IMC: {bmi_val} - {bmi_cat})!\n\n"
        "👉 Step 2/4: Soglie Fisiologiche e Cardio\n"
        "Le soglie FC permettono all'AI di valutare la deriva cardiaca e le zone di allenamento.\n\n"
        "• Clicca sul pulsante qui sotto per confermare i valori default (**202 bpm Max, 178 bpm SAFC**);\n"
        "• Oppure digita in chat i tuoi valori personalizzati separati da virgola (es. `195, 172`)."
    )
    await update.message.reply_text(msg, reply_markup=reply_markup)
    return STEP_CARDIO


async def handle_cardio_choice(update: Update, context: ContextTypes.DEFAULT_TYPE, choice_text: str) -> int:
    """Logica comune per processare la scelta cardio (da click inline o testo)."""
    text = choice_text.strip().lower()

    if "default" in text:
        update_field("fc_max", 202)
        update_field("safc", 178)
        reply = "✅ Impostate soglie default: 1° Valore (FC Max) 202 bpm | 2° Valore (SAFC) 178 bpm."
    elif "skip" in text or "salta" in text:
        reply = "ℹ️ Soglie cardio lasciate invariate."
    else:
        fc_max, safc = parse_hr_thresholds(choice_text)
        if fc_max is not None:
            update_field("fc_max", fc_max)
        if safc is not None:
            update_field("safc", safc)
        reply = (
            f"✅ Soglie registrate:\n"
            f"• 1° Valore (FC Max): {fc_max or 'invariata'} bpm\n"
            f"• 2° Valore (Soglia SAFC): {safc or 'invariata'} bpm"
        )

    inline_kb = [
        [InlineKeyboardButton("⏭️ Salta inserimento piano", callback_data="plan_skip")]
    ]
    reply_markup = InlineKeyboardMarkup(inline_kb)

    msg = (
        f"{reply}\n\n"
        "👉 Step 3/4: Piano di Allenamento\n"
        "Hai una tabella settimanale o un piano di allenamento?\n\n"
        "• Incolla qui in chat il testo del tuo piano;\n"
        "• Oppure tocca il pulsante 'Salta inserimento piano' qui sotto."
    )

    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.message.reply_text(msg, reply_markup=reply_markup)
    else:
        await update.message.reply_text(msg, reply_markup=reply_markup)

    return STEP_PLAN


async def step_cardio_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Step 2 via messaggio di testo."""
    return await handle_cardio_choice(update, context, update.message.text or "")


async def step_cardio_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Step 2 via click pulsante inline."""
    query = update.callback_query
    data = query.data
    return await handle_cardio_choice(update, context, data)


async def handle_plan_choice(update: Update, context: ContextTypes.DEFAULT_TYPE, plan_text: str) -> int:
    """Logica comune per il piano di allenamento."""
    text = plan_text.strip()
    if text.lower() in ("plan_skip", "salta", "/salta", "skip"):
        reply = "ℹ️ Piano saltato per il momento. Potrai aggiungerlo in seguito con `/piano <testo>`."
    else:
        save_training_plan(text)
        reply = f"✅ Piano di allenamento memorizzato con successo ({len(text)} caratteri salvati)!"

    inline_kb = [
        [
            InlineKeyboardButton("0 (Nessuna)", callback_data="hist_0"),
            InlineKeyboardButton("5 (Consigliato)", callback_data="hist_5"),
            InlineKeyboardButton("10 (Dettagliato)", callback_data="hist_10"),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(inline_kb)

    msg = (
        f"{reply}\n\n"
        "👉 Step 4/4: Importazione Storico Garmin\n"
        "Quante attività passate vuoi importare per dare contesto pregresso all'AI Coach?\n\n"
        "Tocca uno dei pulsanti qui sotto:\n"
        "• 0: Storico pulito da zero\n"
        "• 5: Ultime 5 attività (Consigliato)\n"
        "• 10: Ultime 10 attività"
    )

    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.message.reply_text(msg, reply_markup=reply_markup)
    else:
        await update.message.reply_text(msg, reply_markup=reply_markup)

    return STEP_HISTORY


async def step_plan_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Step 3 via testo incollato."""
    return await handle_plan_choice(update, context, update.message.text or "")


async def step_plan_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Step 3 via click inline Salta."""
    query = update.callback_query
    return await handle_plan_choice(update, context, query.data)


async def handle_history_choice(update: Update, context: ContextTypes.DEFAULT_TYPE, choice_val: str) -> int:
    """Logica comune per importazione storico pregresso e chiusura onboarding."""
    val = choice_val.replace("hist_", "").strip()
    if val not in ("0", "5", "10"):
        msg_err = "⚠️ Risposta non valida. Tocca uno dei pulsanti (0, 5, 10)."
        if update.callback_query:
            await update.callback_query.answer()
            await update.callback_query.message.reply_text(msg_err)
        else:
            await update.message.reply_text(msg_err)
        return STEP_HISTORY

    count = int(val)
    send_target = update.callback_query.message if update.callback_query else update.message
    if update.callback_query:
        await update.callback_query.answer()

    if count > 0:
        await send_target.reply_text(
            f"⏳ Connessione a Garmin e importazione di {count} sessioni in corso..."
        )
        try:
            is_mock = context.application.bot_data.get("is_mock", False)
            if is_mock:
                from src.mock_client import MockGarminClient
                client = MockGarminClient()
            else:
                from src.garmin_client import init_garmin
                client = await asyncio.to_thread(init_garmin)

            from src.garmin_client import import_historical_activities
            imported_count = await asyncio.to_thread(
                import_historical_activities, client, count
            )
            await send_target.reply_text(
                f"✅ Importate con successo {imported_count} attività storiche nello storico locale!"
            )
        except Exception as e:
            logger.warning("Errore importazione storico in onboarding: %s", e)
            await send_target.reply_text(
                f"⚠️ Non è stato possibile scaricare le attività da Garmin ({e}).\n"
                "Nessun problema: lo storico si arricchirà con le prossime uscite."
            )

    update_field("onboarding_completato", True)
    profile = load_profile()
    summary = format_profile_summary(profile)

    final_msg = (
        "🎉 Configurazione Onboarding Completata con Successo!\n\n"
        f"{summary}\n\n"
        "Il tuo AI Coach è pienamente operativo.\n"
        "Da adesso in poi puoi usare comodamente la tastiera a pulsanti in basso "
        "oppure i comandi rapidi per interagire con il coach."
    )
    await send_target.reply_text(
        final_msg,
        reply_markup=get_main_keyboard(),
    )
    return ConversationHandler.END


async def step_history_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Step 4 via testo."""
    return await handle_history_choice(update, context, update.message.text or "")


async def step_history_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Step 4 via click inline."""
    query = update.callback_query
    return await handle_history_choice(update, context, query.data)


async def cancel_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Annulla la procedura di onboarding."""
    await update.message.reply_text(
        "❌ Procedura interrotta. Puoi riprenderla in qualsiasi momento con /start.",
        reply_markup=get_main_keyboard(),
    )
    return ConversationHandler.END


# ── COMANDI RAPIDI & BOTTONI MENU ────────────────────────────────────────────


async def peso_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Comando /peso [valore] o click su pulsante '⚖️ Peso'."""
    if not is_authorized(update.effective_chat.id):
        return

    profile = load_profile()
    current_weight = profile.get("peso_kg", 74.0)
    initial_weight = profile.get("peso_iniziale_kg", current_weight)
    height = profile.get("altezza_m", 1.85)

    if not context.args:
        bmi_val, bmi_cat = compute_bmi(current_weight, height)
        trend_tot = round(current_weight - initial_weight, 1)
        trend_str = f" [Trend da inizio: {trend_tot:+.1f} kg]" if trend_tot != 0 else ""
        await update.message.reply_text(
            f"⚖️ Peso corporeo registrato: {current_weight} kg{trend_str}\n"
            f"📊 Indice Massa Corporea (IMC): {bmi_val} ({bmi_cat})\n\n"
            "Per aggiornarlo scrivi:\n"
            "`/peso <valore>` (es. `/peso 73.8` oppure `/peso 73,5`)",
            reply_markup=get_main_keyboard(),
        )
        return

    arg = " ".join(context.args)
    new_weight = parse_weight(arg)

    if new_weight is None:
        await update.message.reply_text(
            "⚠️ Valore non valido. Specifica un peso tra 40 e 200 kg (es. `/peso 73.5`).",
            reply_markup=get_main_keyboard(),
        )
        return

    diff = round(new_weight - current_weight, 1)
    update_field("peso_kg", new_weight)
    bmi_val, bmi_cat = compute_bmi(new_weight, height)
    trend_tot = round(new_weight - initial_weight, 1)

    diff_str = f" ({diff:+.1f} kg dall'ultimo check)" if diff != 0 else " (invariato)"
    trend_str = f"\n📈 Trend da inizio: {trend_tot:+.1f} kg" if trend_tot != 0 else ""

    msg = (
        "⚖️ Peso Corporeo Aggiornato!\n\n"
        f"• Valore precedente: {current_weight} kg\n"
        f"• Nuovo valore: {new_weight} kg{diff_str}{trend_str}\n"
        f"• Indice Massa Corporea (IMC): {bmi_val} ({bmi_cat})\n\n"
        "Il Fisiologo e il Coach utilizzeranno questo peso nelle prossime valutazioni."
    )
    await update.message.reply_text(msg, reply_markup=get_main_keyboard())


async def altezza_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Comando /altezza [valore] o click su '📏 Altezza'."""
    if not is_authorized(update.effective_chat.id):
        return

    profile = load_profile()
    current_height = profile.get("altezza_m", 1.85)
    weight = profile.get("peso_kg", 74.0)

    if not context.args:
        bmi_val, bmi_cat = compute_bmi(weight, current_height)
        await update.message.reply_text(
            f"📏 Altezza attuale: {current_height} m\n"
            f"📊 IMC calcolato: {bmi_val} ({bmi_cat})\n\n"
            "Per aggiornarla scrivi:\n"
            "`/altezza <valore>` (es. `/altezza 1.85` o `/altezza 185`)",
            reply_markup=get_main_keyboard(),
        )
        return

    arg = " ".join(context.args)
    new_height = parse_height(arg)

    if new_height is None:
        await update.message.reply_text(
            "⚠️ Valore non valido. Inserisci un'altezza compresa tra 1.20 e 2.30 m (es. `1.85` o `185`).",
            reply_markup=get_main_keyboard(),
        )
        return

    update_field("altezza_m", new_height)
    bmi_val, bmi_cat = compute_bmi(weight, new_height)

    msg = (
        "📏 Altezza Aggiornata!\n\n"
        f"• Nuova altezza: {new_height} m\n"
        f"• Indice Massa Corporea (IMC): {bmi_val} ({bmi_cat})\n\n"
        "Il Tattico e il Fisiologo calibreranno biomeccanica e cadenza sulla tua statura."
    )
    await update.message.reply_text(msg, reply_markup=get_main_keyboard())


async def fc_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Comando /fc o /soglie [max] [safc] o click su '❤️ Soglie FC'."""
    if not is_authorized(update.effective_chat.id):
        return

    profile = load_profile()
    current_max = profile.get("fc_max", 202)
    current_safc = profile.get("safc", 178)

    if not context.args:
        await update.message.reply_text(
            "❤️ SOGLIE CARDIACHE ATTUALI:\n"
            f"• 1° Valore (FC Max): {current_max} bpm\n"
            f"• 2° Valore (Soglia Anaerobica SAFC): {current_safc} bpm\n\n"
            "Per aggiornarle scrivi:\n"
            "`/fc <fc_max> [safc]` (es. `/fc 198 178` oppure `/fc 198, 178`)\n\n"
            "💡 Regola: il 1° valore imposta SEMPRE la FC Max, il 2° valore la SAFC.\n"
            "💡 Oppure usa i comandi singoli: `/fcmax <valore>` o `/safc <valore>`.",
            reply_markup=get_main_keyboard(),
        )
        return

    arg = " ".join(context.args)
    new_max, new_safc = parse_hr_thresholds(arg)

    if new_max is None and new_safc is None:
        await update.message.reply_text(
            "⚠️ Valori non validi.\n"
            "Specifica prima la FC Max (100-240 bpm) e poi la SAFC (80-220 bpm).\n"
            "Esempio: `/fc 198 178` o `/fc 198, 178`",
            reply_markup=get_main_keyboard(),
        )
        return

    # Salva sempre rispettando l'ordine
    if new_max is not None:
        update_field("fc_max", new_max)
    if new_safc is not None:
        update_field("safc", new_safc)

    p_updated = load_profile()
    msg = (
        "❤️ Soglie Cardio Aggiornate!\n\n"
        f"• 1° Valore (FC Max): {p_updated.get('fc_max')} bpm\n"
        f"• 2° Valore (Soglia Anaerobica SAFC): {p_updated.get('safc')} bpm\n\n"
        "Le prossime sessioni valuteranno le zone cardiache su queste nuove soglie."
    )
    await update.message.reply_text(msg, reply_markup=get_main_keyboard())


async def fcmax_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Comando /fcmax <valore>: aggiorna unicamente la FC Max."""
    if not is_authorized(update.effective_chat.id):
        return

    profile = load_profile()
    current_max = profile.get("fc_max", 202)

    if not context.args:
        await update.message.reply_text(
            f"❤️ FC Max attuale: {current_max} bpm.\n\n"
            "Per aggiornarla scrivi: `/fcmax <valore>` (es. `/fcmax 198`).",
            reply_markup=get_main_keyboard(),
        )
        return

    nums = [int(n) for n in re.findall(r"\b\d{2,3}\b", " ".join(context.args))]
    if not nums or not (100 <= nums[0] <= 240):
        await update.message.reply_text("⚠️ Valore FC Max non valido (range 100-240 bpm).")
        return

    update_field("fc_max", nums[0])
    await update.message.reply_text(
        f"✅ FC Max aggiornata a: {nums[0]} bpm!",
        reply_markup=get_main_keyboard(),
    )


async def safc_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Comando /safc <valore>: aggiorna unicamente la Soglia Anaerobica (SAFC)."""
    if not is_authorized(update.effective_chat.id):
        return

    profile = load_profile()
    current_safc = profile.get("safc", 178)

    if not context.args:
        await update.message.reply_text(
            f"❤️ Soglia Anaerobica (SAFC) attuale: {current_safc} bpm.\n\n"
            "Per aggiornarla scrivi: `/safc <valore>` (es. `/safc 178`).",
            reply_markup=get_main_keyboard(),
        )
        return

    nums = [int(n) for n in re.findall(r"\b\d{2,3}\b", " ".join(context.args))]
    if not nums or not (80 <= nums[0] <= 220):
        await update.message.reply_text("⚠️ Valore SAFC non valido (range 80-220 bpm).")
        return

    update_field("safc", nums[0])
    await update.message.reply_text(
        f"✅ Soglia Anaerobica (SAFC) aggiornata a: {nums[0]} bpm!",
        reply_markup=get_main_keyboard(),
    )


async def piano_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Comando /piano [testo] o click su '📋 Piano'."""
    if not is_authorized(update.effective_chat.id):
        return

    full_text = update.message.text or ""
    parts = full_text.split(None, 1)

    if len(parts) == 1 or not context.args:
        current_plan = get_training_plan()
        await update.message.reply_text(
            "📋 PIANO DI ALLENAMENTO ATTUALE:\n"
            "────────────────────────────────\n"
            f"{current_plan}\n\n"
            "────────────────────────────────\n"
            "💡 Per aggiornarlo scrivi: `/piano <incolla qui il tuo nuovo piano>`",
            reply_markup=get_main_keyboard(),
        )
        return

    new_plan = parts[1].strip()
    save_training_plan(new_plan)
    await update.message.reply_text(
        f"✅ Piano di allenamento aggiornato con successo!\n"
        f"Salvati {len(new_plan)} caratteri in `piano_allenamento.txt`.",
        reply_markup=get_main_keyboard(),
    )


async def profilo_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Comando /profilo o click su '📋 Profilo'."""
    if not is_authorized(update.effective_chat.id):
        return

    summary = format_profile_summary()
    await update.message.reply_text(
        summary,
        reply_markup=get_main_keyboard(),
    )
    await update.message.reply_text(
        "💡 Azioni rapide:",
        reply_markup=get_profile_inline_keyboard(),
    )


async def target_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Comando /target [passo] o click su '⚡ Target'."""
    if not is_authorized(update.effective_chat.id):
        return

    profile = load_profile()
    current_target = profile.get("passo_target", "5:35 min/km")

    if not context.args:
        await update.message.reply_text(
            f"⚡ Passo target gara attuale: {current_target}\n\n"
            "Per aggiornarlo scrivi: `/target <passo>` (es. `/target 5:30` oppure `/target 5:25 min/km`).",
            reply_markup=get_main_keyboard(),
        )
        return

    new_target = " ".join(context.args).strip()
    if not new_target.endswith("min/km"):
        new_target = f"{new_target} min/km"

    update_field("passo_target", new_target)
    await update.message.reply_text(
        f"✅ Passo target gara aggiornato a: {new_target}!\n"
        "Il Tattico e il Coach confronteranno le sedute su questo obiettivo.",
        reply_markup=get_main_keyboard(),
    )


async def gara_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Comando /gara [nome]."""
    if not is_authorized(update.effective_chat.id):
        return

    profile = load_profile()
    current_gara = profile.get("obiettivo_gara", "N/D")

    if not context.args:
        await update.message.reply_text(
            f"🎯 Gara obiettivo attuale: {current_gara}\n\n"
            "Per aggiornarla scrivi: `/gara <nome della gara>` (es. `/gara Mezza delle Terre Verdiane`).",
            reply_markup=get_main_keyboard(),
        )
        return

    new_gara = " ".join(context.args).strip()
    update_field("obiettivo_gara", new_gara)
    await update.message.reply_text(
        f"✅ Gara obiettivo aggiornata a: {new_gara}!",
        reply_markup=get_main_keyboard(),
    )


async def ultimarun_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Comando /ultimarun o click su '🏃‍♂️ Ultima Run'."""
    if not is_authorized(update.effective_chat.id):
        return

    last_summary = get_last_run_summary()
    if not last_summary:
        await update.message.reply_text(
            "ℹ️ Nessun allenamento registrato nello storico locale al momento.",
            reply_markup=get_main_keyboard(),
        )
        return

    msg = f"🏃‍♂️ **ULTIMA SESSIONE REGISTRATA**\n\n{last_summary}"
    await update.message.reply_text(msg, reply_markup=get_main_keyboard())


async def reset_onboarding_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Comando /reset_onboarding: reimposta l'onboarding per consentire una nuova configurazione."""
    if not is_authorized(update.effective_chat.id):
        return

    reset_profile()
    await update.message.reply_text(
        "🔄 Profilo atleta resettato!\n\n"
        "Invia ora `/start` per riavviare la procedura guidata a 4 step con i pulsanti a schermo.",
        reply_markup=ReplyKeyboardRemove(),
    )


async def aiuto_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Comando /aiuto o click su '📖 Aiuto'."""
    if not is_authorized(update.effective_chat.id):
        return

    help_text = (
        "📖 GUIDA COMANDI GARMIN AI COACH\n"
        "───────────────────────────────\n"
        "Tocca i pulsanti della tastiera in basso oppure digita:\n\n"
        "• /profilo - Visualizza scheda anagrafica, FC e IMC\n"
        "• /peso <valore> - Aggiorna il peso corporeo (es. `/peso 73.8`)\n"
        "• /altezza <valore> - Imposta l'altezza in m o cm (es. `/altezza 1.85`)\n"
        "• /fc <max> [safc] - Aggiorna FC Max e SAFC (es. `/fc 195 172`)\n"
        "• /ultimarun - Consulta l'ultima corsa e il report del coach\n"
        "• /piano [testo] - Mostra o aggiorna la tabella di allenamento\n"
        "• /target <passo> - Aggiorna il passo gara (es. `/target 5:30`)\n"
        "• /gara <nome> - Aggiorna la gara obiettivo\n"
        "• /reset_onboarding - Riesegue l'onboarding guidato iniziale\n"
        "• /start - Riapre il menu o avvia l'onboarding\n"
        "───────────────────────────────"
    )
    await update.message.reply_text(help_text, reply_markup=get_main_keyboard())


# ── HANDLER CALLBACK PULSANTI INLINE GLOBALI ──────────────────────────────────


async def global_inline_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Gestisce i click sui bottoni inline sotto /profilo o /start."""
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "btn_peso":
        await query.message.reply_text(
            "⚖️ Per aggiornare il tuo peso scrivi:\n`/peso <valore>` (es. `/peso 73.8`)",
            reply_markup=get_main_keyboard(),
        )
    elif data == "btn_altezza":
        await query.message.reply_text(
            "📏 Per aggiornare l'altezza scrivi:\n`/altezza <valore>` (es. `/altezza 1.85` o `185`)",
            reply_markup=get_main_keyboard(),
        )
    elif data == "btn_fc":
        await query.message.reply_text(
            "❤️ Per aggiornare le soglie FC scrivi:\n`/fc <fc_max> [safc]` (es. `/fc 195 172`)",
            reply_markup=get_main_keyboard(),
        )
    elif data == "btn_ultimarun":
        last_summary = get_last_run_summary()
        if last_summary:
            await query.message.reply_text(
                f"🏃‍♂️ **ULTIMA SESSIONE REGISTRATA**\n\n{last_summary}",
                reply_markup=get_main_keyboard(),
            )
        else:
            await query.message.reply_text(
                "ℹ️ Nessun allenamento registrato nello storico locale al momento.",
                reply_markup=get_main_keyboard(),
            )
    elif data == "btn_reset_onb":
        reset_profile()
        await query.message.reply_text(
            "🔄 Profilo resettato. Digita `/start` per riavviare la procedura guidata!",
            reply_markup=ReplyKeyboardRemove(),
        )


# ── RUNNER DEL BOT ───────────────────────────────────────────────────────────


def build_application(is_mock: bool = False):
    """Costruisce e restituisce l'Application di python-telegram-bot."""
    try:
        from telegram.ext import (
            ApplicationBuilder,
            CallbackQueryHandler,
            CommandHandler,
            ConversationHandler,
            MessageHandler,
            filters,
        )
    except ImportError:
        raise RuntimeError(
            "Libreria 'python-telegram-bot' non trovata.\n"
            "Per utilizzare il bot interattivo esegui: pip install \"python-telegram-bot[job-queue]\""
        )

    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN non configurato nel .env")

    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    app.bot_data["is_mock"] = is_mock

    # Handler conversazionale per l'onboarding con supporto sia a testo che pulsanti inline
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start_handler)],
        states={
            STEP_BODY: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, step_body_handler)
            ],
            STEP_CARDIO: [
                CallbackQueryHandler(step_cardio_callback_handler),
                MessageHandler(filters.TEXT & ~filters.COMMAND, step_cardio_text_handler),
            ],
            STEP_PLAN: [
                CallbackQueryHandler(step_plan_callback_handler),
                MessageHandler(filters.TEXT & ~filters.COMMAND, step_plan_text_handler),
            ],
            STEP_HISTORY: [
                CallbackQueryHandler(step_history_callback_handler),
                MessageHandler(filters.TEXT & ~filters.COMMAND, step_history_text_handler),
            ],
        },
        fallbacks=[CommandHandler("annulla", cancel_handler)],
    )

    app.add_handler(conv_handler)

    # Comandi slash canonici
    app.add_handler(CommandHandler("peso", peso_command))
    app.add_handler(CommandHandler("altezza", altezza_command))
    app.add_handler(CommandHandler("fc", fc_command))
    app.add_handler(CommandHandler("soglie", fc_command))
    app.add_handler(CommandHandler("fcmax", fcmax_command))
    app.add_handler(CommandHandler("safc", safc_command))
    app.add_handler(CommandHandler("piano", piano_command))
    app.add_handler(CommandHandler("profilo", profilo_command))
    app.add_handler(CommandHandler("target", target_command))
    app.add_handler(CommandHandler("gara", gara_command))
    app.add_handler(CommandHandler("ultimarun", ultimarun_command))
    app.add_handler(CommandHandler("reset_onboarding", reset_onboarding_command))
    app.add_handler(CommandHandler("aiuto", aiuto_command))
    app.add_handler(CommandHandler("help", aiuto_command))

    # Mappatura dei pulsanti della tastiera fissa (Reply Keyboard)
    app.add_handler(MessageHandler(filters.Regex("^📋 Profilo$"), profilo_command))
    app.add_handler(MessageHandler(filters.Regex("^🏃‍♂️ Ultima Run$"), ultimarun_command))
    app.add_handler(MessageHandler(filters.Regex("^⚖️ Peso$"), peso_command))
    app.add_handler(MessageHandler(filters.Regex("^📏 Altezza$"), altezza_command))
    app.add_handler(MessageHandler(filters.Regex("^❤️ Soglie FC$"), fc_command))
    app.add_handler(MessageHandler(filters.Regex("^📋 Piano$"), piano_command))
    app.add_handler(MessageHandler(filters.Regex("^⚡ Target$"), target_command))
    app.add_handler(MessageHandler(filters.Regex("^📖 Aiuto$"), aiuto_command))

    # Callback query per i bottoni inline generici (sotto /profilo)
    app.add_handler(CallbackQueryHandler(global_inline_callback_handler))

    return app


def run_bot(is_mock: bool = False) -> None:
    """Avvia il polling del bot Telegram in modalità standalone."""
    print("🤖 Avvio Garmin AI Telegram Bot (Polling)...")
    if is_mock:
        print("🧪 [MOCK MODE] Le operazioni storiche useranno il dataset locale.")
    app = build_application(is_mock=is_mock)
    print("🚀 Bot in ascolto su Telegram. Premi CTRL+C per arrestarlo.")
    app.run_polling()


if __name__ == "__main__":
    import sys
    is_mock = "--mock" in sys.argv
    run_bot(is_mock=is_mock)
