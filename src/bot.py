"""
bot.py - Bot Telegram interattivo per Onboarding e gestione profilo (Fase 1 e Fase 1.1).

Fornisce:
- Hamburger Menu Button nativo ('set_my_commands'): lista comandi nativa Telegram sempre
  accessibile a sinistra del campo di inserimento testo.
- Interfaccia Always-Interactive (Zero schermate senza tasti): tastiera di default, opzioni inline
  e pulsante di annullamento sempre visibili durante ogni passaggio.
- Acquisizione Dati Atomica (Step Singoli):
  Step 1: Età -> Step 2: Altezza -> Step 3: Peso -> Step 4: FC Max -> Step 5: SAFC -> Step 6: Piano -> Step 7: Storico.
- Tastiera persistente fissa sotto la barra di scrittura (Reply Keyboard):
  [ 📋 Profilo ] [ 🏃‍♂️ Ultima Run ]
  [ ⚖️ Peso ] [ 📏 Altezza ] [ ❤️ Soglie FC ]
  [ 📋 Piano ] [ ⚡ Target ] [ 📜 Lista Comandi ]
- Pulsanti Inline interattivi direttamente nei messaggi per default, skip e azioni veloci.
- Comandi rapidi (/menu, /peso, /altezza, /fc, /fcmax, /safc, /piano, /profilo, /ultimarun, /target, /gara, /reset_onboarding, /aiuto).
- Controllo di sicurezza sull'ID mittente (TELEGRAM_CHAT_ID).
"""

import asyncio
import logging
import re
from typing import Any

from telegram import (
    BotCommand,
    BotCommandScopeChat,
    BotCommandScopeDefault,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    MenuButtonCommands,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    Update,
)
from telegram.ext import (
    Application,
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
    parse_age,
    parse_fc_max,
    parse_height,
    parse_hr_thresholds,
    parse_safc,
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
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger("GarminAIBot")

# Stati della conversazione di onboarding atomico a 7 step
(
    STEP_AGE,
    STEP_HEIGHT,
    STEP_WEIGHT,
    STEP_FCMAX,
    STEP_SAFC,
    STEP_PLAN,
    STEP_HISTORY,
) = range(7)


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
        ["📋 Piano", "⚡ Target", "📜 Lista Comandi"],
    ]
    return ReplyKeyboardMarkup(
        keyboard,
        resize_keyboard=True,
        is_persistent=True,
    )


def get_cancel_keyboard() -> ReplyKeyboardMarkup:
    """Tastiera fissa contestuale durante l'input: garantisce zero schermate senza tasti."""
    return ReplyKeyboardMarkup(
        [["❌ Annulla"]],
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
            InlineKeyboardButton("📜 Lista Comandi", callback_data="btn_menu"),
            InlineKeyboardButton("🔄 Riesegui Onboarding", callback_data="btn_reset_onb"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


def get_commands_inline_keyboard() -> InlineKeyboardMarkup:
    """Restituisce una tastiera inline interattiva con tutti i comandi disponibili."""
    keyboard = [
        [
            InlineKeyboardButton("🏃‍♂️ Ultima Run", callback_data="btn_ultimarun"),
            InlineKeyboardButton("📋 Profilo Atleta", callback_data="btn_profilo"),
        ],
        [
            InlineKeyboardButton("⚖️ Aggiorna Peso", callback_data="btn_peso"),
            InlineKeyboardButton("📏 Aggiorna Altezza", callback_data="btn_altezza"),
            InlineKeyboardButton("❤️ Soglie FC", callback_data="btn_fc"),
        ],
        [
            InlineKeyboardButton("📋 Tabella Piano", callback_data="btn_piano"),
            InlineKeyboardButton("⚡ Passo Target", callback_data="btn_target"),
            InlineKeyboardButton("🎯 Gara Obiettivo", callback_data="btn_gara"),
        ],
        [
            InlineKeyboardButton("🔄 Riesegui Onboarding", callback_data="btn_reset_onb"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


async def set_bot_commands(application: Application) -> None:
    """Configura la lista comandi nativa Telegram e attiva il pulsante Menu."""
    commands = [
        BotCommand("start", "Avvia o apri il menu principale"),
        BotCommand("menu", "Mostra la lista completa dei comandi"),
        BotCommand("profilo", "Scheda anagrafica, FC e parametri atleta"),
        BotCommand("ultimarun", "Ultima sessione e report AI coach"),
        BotCommand("peso", "Visualizza o aggiorna peso (es. /peso 73.8)"),
        BotCommand("altezza", "Visualizza o aggiorna altezza (es. /altezza 1.85)"),
        BotCommand("fc", "Aggiorna entrambe le soglie FC (/fc 195 172)"),
        BotCommand("fcmax", "Aggiorna solo FC Max (es. /fcmax 202)"),
        BotCommand("safc", "Aggiorna solo Soglia SAFC (es. /safc 178)"),
        BotCommand("piano", "Visualizza o imposta tabella allenamento"),
        BotCommand("target", "Aggiorna passo gara obiettivo (es. /target 5:35)"),
        BotCommand("gara", "Aggiorna nome della gara obiettivo"),
        BotCommand("reset_onboarding", "Reimposta profilo e riesegui onboarding"),
        BotCommand("aiuto", "Guida comandi e istruzioni d'uso"),
    ]
    try:
        # 1. Configura comandi a livello globale (default)
        await application.bot.set_my_commands(commands, scope=BotCommandScopeDefault())
        # 2. Attiva esplicitamente il pulsante nativo Menu (MenuButtonCommands) a sinistra della barra testo
        await application.bot.set_chat_menu_button(menu_button=MenuButtonCommands())
        logger.info("Menu nativo Telegram (set_my_commands + MenuButtonCommands) configurato.")

        # 3. Se TELEGRAM_CHAT_ID è valorizzato, imposta immediatamente anche lo scope specifico della chat
        # per forzare l'aggiornamento istantaneo dell'interfaccia client senza attendere la cache
        if TELEGRAM_CHAT_ID:
            try:
                cid = int(str(TELEGRAM_CHAT_ID).strip())
                await application.bot.set_my_commands(commands, scope=BotCommandScopeChat(chat_id=cid))
                await application.bot.set_chat_menu_button(chat_id=cid, menu_button=MenuButtonCommands())
                logger.info("Menu nativo Telegram registrato istantaneamente per chat_id=%s", cid)
            except Exception as e_cid:
                logger.debug("Configurazione chat-specific menu: %s", e_cid)
    except Exception as e:
        logger.warning("Impossibile registrare set_my_commands: %s", e)


# ── HANDLER ONBOARDING ATOMICO (/start) ──────────────────────────────────────


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
        await update.message.reply_text(
            "💡 Azioni rapide con un click:",
            reply_markup=get_profile_inline_keyboard(),
        )
        return ConversationHandler.END

    # Avvio flusso onboarding guidato atomico (Step 1/7)
    welcome_msg = (
        "🏃‍♂️ **Benvenuto nel tuo Garmin AI Coach!**\n\n"
        "Configuriamo il tuo profilo atleta in **7 passaggi singoli atomici** "
        "(un solo dato per volta, zero separatori a virgola).\n\n"
        "👉 **Step 1/7: Età**\n"
        "Quanti anni hai? Inserisci solo il numero (es. `31` o `58`).\n\n"
        "*(Tocca '❌ Annulla' in qualsiasi momento per interrompere)*"
    )
    inline_kb = [
        [InlineKeyboardButton("❌ Annulla Procedura", callback_data="onb_cancel")]
    ]
    await update.message.reply_text(
        welcome_msg,
        reply_markup=get_cancel_keyboard(),
    )
    await update.message.reply_text(
        "💡 Inserisci la tua età nella casella di testo:",
        reply_markup=InlineKeyboardMarkup(inline_kb),
    )
    return STEP_AGE


async def start_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Entry point da pulsante inline '🚀 Avvia Onboarding'."""
    query = update.callback_query
    await query.answer()

    if not is_authorized(query.message.chat_id):
        await query.message.reply_text(
            "⛔ Accesso non autorizzato. Questo bot è riservato all'atleta titolare."
        )
        return ConversationHandler.END

    welcome_msg = (
        "🏃‍♂️ **Benvenuto nel tuo Garmin AI Coach!**\n\n"
        "Configuriamo il tuo profilo atleta in **7 passaggi singoli atomici** "
        "(un solo dato per volta, zero separatori a virgola).\n\n"
        "👉 **Step 1/7: Età**\n"
        "Quanti anni hai? Inserisci solo il numero (es. `31` o `58`).\n\n"
        "*(Tocca '❌ Annulla' in qualsiasi momento per interrompere)*"
    )
    inline_kb = [
        [InlineKeyboardButton("❌ Annulla Procedura", callback_data="onb_cancel")]
    ]
    await query.message.reply_text(
        welcome_msg,
        reply_markup=get_cancel_keyboard(),
    )
    await query.message.reply_text(
        "💡 Inserisci la tua età nella casella di testo:",
        reply_markup=InlineKeyboardMarkup(inline_kb),
    )
    return STEP_AGE


async def step_age_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Step 1/7: Riceve e valida l'età anagrafica."""
    text = (update.message.text or "").strip()
    if text in ("❌ Annulla", "annulla", "/annulla"):
        return await cancel_handler(update, context)

    age = parse_age(text)
    if age is None:
        inline_kb = [
            [InlineKeyboardButton("❌ Annulla Procedura", callback_data="onb_cancel")]
        ]
        await update.message.reply_text(
            "⚠️ Valore età non valido.\n"
            "Inserisci un'età compresa tra 15 e 100 anni (es. `31` o `58`).\n\n"
            "Riprova oppure tocca '❌ Annulla':",
            reply_markup=InlineKeyboardMarkup(inline_kb),
        )
        return STEP_AGE

    update_field("eta", age)

    inline_kb = [
        [InlineKeyboardButton("⏭️ Mantieni Default (1.85 m)", callback_data="height_default")],
        [InlineKeyboardButton("❌ Annulla", callback_data="onb_cancel")],
    ]
    msg = (
        f"✅ Età registrata: **{age} anni**!\n\n"
        "👉 **Step 2/7: Altezza**\n"
        "Quanto sei alto? Inserisci l'altezza in metri o centimetri (es. `1.85` o `185`).\n\n"
        "• Oppure tocca il pulsante '⏭️ Mantieni Default (1.85 m)' qui sotto."
    )
    await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(inline_kb))
    return STEP_HEIGHT


async def handle_height_choice(update: Update, context: ContextTypes.DEFAULT_TYPE, choice_val: str) -> int:
    """Elabora l'altezza (da testo o callback)."""
    text = choice_val.strip().lower()

    if "default" in text:
        height = 1.85
        alt_str = "1.85 m (predefinita)"
    else:
        height = parse_height(choice_val)
        if height is None:
            err_msg = (
                "⚠️ Valore altezza non valido.\n"
                "Inserisci un'altezza compresa tra 1.20 e 2.30 m (es. `1.85` o `185`), "
                "oppure tocca il pulsante per il default (1.85 m):"
            )
            inline_kb = [
                [InlineKeyboardButton("⏭️ Default (1.85 m)", callback_data="height_default")],
                [InlineKeyboardButton("❌ Annulla", callback_data="onb_cancel")],
            ]
            if update.callback_query:
                await update.callback_query.answer()
                await update.callback_query.message.reply_text(
                    err_msg, reply_markup=InlineKeyboardMarkup(inline_kb)
                )
            else:
                await update.message.reply_text(
                    err_msg, reply_markup=InlineKeyboardMarkup(inline_kb)
                )
            return STEP_HEIGHT
        alt_str = f"{height} m"

    update_field("altezza_m", height)

    send_target = update.callback_query.message if update.callback_query else update.message
    if update.callback_query:
        await update.callback_query.answer()

    inline_kb = [
        [InlineKeyboardButton("❌ Annulla", callback_data="onb_cancel")]
    ]
    msg = (
        f"✅ Altezza registrata: **{alt_str}**!\n\n"
        "👉 **Step 3/7: Peso Corporeo**\n"
        "Qual è il tuo peso attuale in kg? (es. `96.0` o `74.5`).\n\n"
        "💡 *Il peso corporeo è determinante per il calcolo del costo energetico al km "
        "(+35-40% per atleti di peso elevato), dell'IMC e dell'impatto biomeccanico articolare.*"
    )
    await send_target.reply_text(msg, reply_markup=InlineKeyboardMarkup(inline_kb))
    return STEP_WEIGHT


async def step_height_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Step 2/7 via testo inserito."""
    text = (update.message.text or "").strip()
    if text in ("❌ Annulla", "annulla", "/annulla"):
        return await cancel_handler(update, context)
    return await handle_height_choice(update, context, text)


async def step_height_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Step 2/7 via click su pulsante inline default."""
    query = update.callback_query
    return await handle_height_choice(update, context, query.data)


async def step_weight_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Step 3/7: Riceve e valida il peso corporeo."""
    text = (update.message.text or "").strip()
    if text in ("❌ Annulla", "annulla", "/annulla"):
        return await cancel_handler(update, context)

    weight = parse_weight(text)
    if weight is None:
        inline_kb = [
            [InlineKeyboardButton("❌ Annulla Procedura", callback_data="onb_cancel")]
        ]
        await update.message.reply_text(
            "⚠️ Valore peso non valido.\n"
            "Inserisci un peso valido compreso tra 40 e 200 kg (es. `96.0` o `74.5`).\n\n"
            "Riprova oppure tocca '❌ Annulla':",
            reply_markup=InlineKeyboardMarkup(inline_kb),
        )
        return STEP_WEIGHT

    update_field("peso_kg", weight)
    profile = load_profile()
    if not profile.get("peso_iniziale_kg"):
        update_field("peso_iniziale_kg", weight)

    height = profile.get("altezza_m", 1.85)
    bmi_val, bmi_cat = compute_bmi(weight, height)

    inline_kb = [
        [InlineKeyboardButton("✅ Usa Default (202 bpm)", callback_data="fcmax_default")],
        [InlineKeyboardButton("❌ Annulla", callback_data="onb_cancel")],
    ]
    msg = (
        f"✅ Peso registrato: **{weight} kg** (IMC: {bmi_val} - {bmi_cat})!\n\n"
        "👉 **Step 4/7: Frequenza Cardiaca Massima (FC Max)**\n"
        "Qual è la tua frequenza cardiaca massima in bpm? (es. `202`).\n\n"
        "• Tocca '✅ Usa Default (202 bpm)' qui sotto per confermare il valore di riferimento;\n"
        "• Oppure digita in chat il tuo valore personalizzato (100-240 bpm)."
    )
    await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(inline_kb))
    return STEP_FCMAX


async def handle_fcmax_choice(update: Update, context: ContextTypes.DEFAULT_TYPE, choice_val: str) -> int:
    """Elabora la FC Max (da testo o callback)."""
    text = choice_val.strip().lower()

    if "default" in text:
        fc_max = 202
        desc = "202 bpm (predefinita)"
    else:
        fc_max = parse_fc_max(choice_val)
        if fc_max is None:
            err_msg = (
                "⚠️ Valore FC Max non valido (range 100-240 bpm).\n"
                "Digita un numero intero (es. `202`) oppure tocca '✅ Usa Default (202 bpm)':"
            )
            inline_kb = [
                [InlineKeyboardButton("✅ Usa Default (202 bpm)", callback_data="fcmax_default")],
                [InlineKeyboardButton("❌ Annulla", callback_data="onb_cancel")],
            ]
            if update.callback_query:
                await update.callback_query.answer()
                await update.callback_query.message.reply_text(
                    err_msg, reply_markup=InlineKeyboardMarkup(inline_kb)
                )
            else:
                await update.message.reply_text(
                    err_msg, reply_markup=InlineKeyboardMarkup(inline_kb)
                )
            return STEP_FCMAX
        desc = f"{fc_max} bpm"

    update_field("fc_max", fc_max)

    send_target = update.callback_query.message if update.callback_query else update.message
    if update.callback_query:
        await update.callback_query.answer()

    inline_kb = [
        [InlineKeyboardButton("✅ Usa Default (178 bpm)", callback_data="safc_default")],
        [InlineKeyboardButton("❌ Annulla", callback_data="onb_cancel")],
    ]
    msg = (
        f"✅ FC Max registrata: **{desc}**!\n\n"
        "👉 **Step 5/7: Soglia Anaerobica (SAFC)**\n"
        "A quanti bpm si colloca la tua soglia anaerobica? (es. `178`).\n\n"
        "• Tocca '✅ Usa Default (178 bpm)' qui sotto per confermare il valore di riferimento;\n"
        "• Oppure digita in chat il tuo valore personalizzato (80-220 bpm)."
    )
    await send_target.reply_text(msg, reply_markup=InlineKeyboardMarkup(inline_kb))
    return STEP_SAFC


async def step_fcmax_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Step 4/7 via testo."""
    text = (update.message.text or "").strip()
    if text in ("❌ Annulla", "annulla", "/annulla"):
        return await cancel_handler(update, context)
    return await handle_fcmax_choice(update, context, text)


async def step_fcmax_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Step 4/7 via callback inline."""
    query = update.callback_query
    return await handle_fcmax_choice(update, context, query.data)


async def handle_safc_choice(update: Update, context: ContextTypes.DEFAULT_TYPE, choice_val: str) -> int:
    """Elabora la Soglia Anaerobica SAFC (da testo o callback)."""
    text = choice_val.strip().lower()

    if "default" in text:
        safc = 178
        desc = "178 bpm (predefinita)"
    else:
        safc = parse_safc(choice_val)
        if safc is None:
            err_msg = (
                "⚠️ Valore SAFC non valido (range 80-220 bpm).\n"
                "Digita un numero intero (es. `178`) oppure tocca '✅ Usa Default (178 bpm)':"
            )
            inline_kb = [
                [InlineKeyboardButton("✅ Usa Default (178 bpm)", callback_data="safc_default")],
                [InlineKeyboardButton("❌ Annulla", callback_data="onb_cancel")],
            ]
            if update.callback_query:
                await update.callback_query.answer()
                await update.callback_query.message.reply_text(
                    err_msg, reply_markup=InlineKeyboardMarkup(inline_kb)
                )
            else:
                await update.message.reply_text(
                    err_msg, reply_markup=InlineKeyboardMarkup(inline_kb)
                )
            return STEP_SAFC
        desc = f"{safc} bpm"

    update_field("safc", safc)

    send_target = update.callback_query.message if update.callback_query else update.message
    if update.callback_query:
        await update.callback_query.answer()

    inline_kb = [
        [InlineKeyboardButton("⏭️ Salta Inserimento Piano", callback_data="plan_skip")],
        [InlineKeyboardButton("❌ Annulla", callback_data="onb_cancel")],
    ]
    msg = (
        f"✅ Soglia Anaerobica (SAFC) registrata: **{desc}**!\n\n"
        "👉 **Step 6/7: Tabella / Piano di Allenamento**\n"
        "Hai un programma settimanale o una tabella di allenamento?\n\n"
        "• Incolla qui in chat il testo della tabella;\n"
        "• Oppure tocca '⏭️ Salta Inserimento Piano' qui sotto per farlo in un secondo momento."
    )
    await send_target.reply_text(msg, reply_markup=InlineKeyboardMarkup(inline_kb))
    return STEP_PLAN


async def step_safc_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Step 5/7 via testo."""
    text = (update.message.text or "").strip()
    if text in ("❌ Annulla", "annulla", "/annulla"):
        return await cancel_handler(update, context)
    return await handle_safc_choice(update, context, text)


async def step_safc_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Step 5/7 via callback inline."""
    query = update.callback_query
    return await handle_safc_choice(update, context, query.data)


async def handle_plan_choice(update: Update, context: ContextTypes.DEFAULT_TYPE, plan_text: str) -> int:
    """Elabora il piano di allenamento."""
    text = plan_text.strip()
    if text.lower() in ("plan_skip", "salta", "/salta", "skip"):
        reply = "ℹ️ Piano saltato per il momento. Potrai aggiungerlo in seguito con `/piano <testo>`."
    else:
        save_training_plan(text)
        reply = f"✅ Piano di allenamento memorizzato con successo ({len(text)} caratteri salvati)!"

    send_target = update.callback_query.message if update.callback_query else update.message
    if update.callback_query:
        await update.callback_query.answer()

    inline_kb = [
        [
            InlineKeyboardButton("0 (Nessuna)", callback_data="hist_0"),
            InlineKeyboardButton("5 (Consigliato)", callback_data="hist_5"),
            InlineKeyboardButton("10 (Dettagliato)", callback_data="hist_10"),
        ],
        [
            InlineKeyboardButton("❌ Annulla", callback_data="onb_cancel"),
        ],
    ]
    msg = (
        f"{reply}\n\n"
        "👉 **Step 7/7: Importazione Storico Garmin**\n"
        "Quante attività passate vuoi importare per dare contesto pregresso all'AI Coach?\n\n"
        "Tocca uno dei pulsanti qui sotto:\n"
        "• 0: Storico pulito da zero\n"
        "• 5: Ultime 5 attività (Consigliato)\n"
        "• 10: Ultime 10 attività"
    )
    await send_target.reply_text(msg, reply_markup=InlineKeyboardMarkup(inline_kb))
    return STEP_HISTORY


async def step_plan_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Step 6/7 via testo."""
    text = (update.message.text or "").strip()
    if text in ("❌ Annulla", "annulla", "/annulla"):
        return await cancel_handler(update, context)
    return await handle_plan_choice(update, context, text)


async def step_plan_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Step 6/7 via click inline Salta."""
    query = update.callback_query
    return await handle_plan_choice(update, context, query.data)


async def handle_history_choice(update: Update, context: ContextTypes.DEFAULT_TYPE, choice_val: str) -> int:
    """Importa lo storico pregresso e conclude l'onboarding atomico."""
    val = choice_val.replace("hist_", "").strip()
    send_target = update.callback_query.message if update.callback_query else update.message

    if val not in ("0", "5", "10"):
        msg_err = "⚠️ Scelta non valida. Tocca uno dei pulsanti (0, 5, 10) oppure '❌ Annulla':"
        inline_kb = [
            [
                InlineKeyboardButton("0 (Nessuna)", callback_data="hist_0"),
                InlineKeyboardButton("5 (Consigliato)", callback_data="hist_5"),
                InlineKeyboardButton("10 (Dettagliato)", callback_data="hist_10"),
            ],
            [
                InlineKeyboardButton("❌ Annulla", callback_data="onb_cancel"),
            ],
        ]
        if update.callback_query:
            await update.callback_query.answer()
            await update.callback_query.message.reply_text(msg_err, reply_markup=InlineKeyboardMarkup(inline_kb))
        else:
            await update.message.reply_text(msg_err, reply_markup=InlineKeyboardMarkup(inline_kb))
        return STEP_HISTORY

    count = int(val)
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
                f"✅ Importate con successo {imported_count} attività nello storico locale!"
            )
        except Exception as e:
            logger.warning("Errore importazione storico in onboarding: %s", e)
            await send_target.reply_text(
                f"⚠️ Non è stato possibile scaricare le attività da Garmin ({e}).\n"
                "Nessun problema: lo storico si arricchirà progressivamente con le prossime corse."
            )

    update_field("onboarding_completato", True)
    profile = load_profile()
    summary = format_profile_summary(profile)

    final_msg = (
        "🎉 **Configurazione Onboarding Completata con Successo!**\n\n"
        f"{summary}\n\n"
        "Il tuo AI Coach è ora pienamente operativo ed allineato ai tuoi parametri!\n"
        "Usa i comandi nativi del Menu ☰ (a sinistra del campo di testo) "
        "oppure la tastiera a pulsanti sempre attiva in basso."
    )
    await send_target.reply_text(
        final_msg,
        reply_markup=get_main_keyboard(),
    )
    return ConversationHandler.END


async def step_history_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Step 7/7 via testo."""
    text = (update.message.text or "").strip()
    if text in ("❌ Annulla", "annulla", "/annulla"):
        return await cancel_handler(update, context)
    return await handle_history_choice(update, context, text)


async def step_history_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Step 7/7 via click inline."""
    query = update.callback_query
    return await handle_history_choice(update, context, query.data)


async def onb_cancel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Annulla la procedura guidata via click su pulsante inline."""
    query = update.callback_query
    await query.answer()
    await query.message.reply_text(
        "❌ Procedura di configurazione interrotta.\n"
        "Puoi riprenderla in qualsiasi momento digitando `/start`.",
        reply_markup=get_main_keyboard(),
    )
    return ConversationHandler.END


async def cancel_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Annulla la procedura di onboarding (da comando o testo '❌ Annulla')."""
    msg = (
        "❌ Procedura di configurazione interrotta.\n"
        "Puoi riprenderla in qualsiasi momento digitando `/start`."
    )
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.message.reply_text(
            msg,
            reply_markup=get_main_keyboard(),
        )
    elif update.message:
        await update.message.reply_text(
            msg,
            reply_markup=get_main_keyboard(),
        )
    return ConversationHandler.END


# ── COMANDI RAPIDI & BOTTONI MENU ────────────────────────────────────────────


async def peso_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Comando /peso [valore] o click su pulsante '⚖️ Peso'."""
    if not is_authorized(update.effective_chat.id):
        return

    profile = load_profile()
    current_weight = profile.get("peso_kg", 96.0)
    initial_weight = profile.get("peso_iniziale_kg", current_weight)
    height = profile.get("altezza_m", 1.85)

    if not context.args:
        bmi_val, bmi_cat = compute_bmi(current_weight, height)
        trend_tot = round(current_weight - initial_weight, 1)
        trend_str = f" [Trend da inizio: {trend_tot:+.1f} kg]" if trend_tot != 0 else ""
        inline_kb = [
            [InlineKeyboardButton("📋 Scheda Profilo", callback_data="btn_profilo")],
        ]
        await update.message.reply_text(
            f"⚖️ Peso corporeo registrato: {current_weight} kg{trend_str}\n"
            f"📊 Indice Massa Corporea (IMC): {bmi_val} ({bmi_cat})\n\n"
            "Per aggiornarlo scrivi:\n"
            "`/peso <valore>` (es. `/peso 73.8` oppure `/peso 73,5`)",
            reply_markup=InlineKeyboardMarkup(inline_kb),
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
    weight = profile.get("peso_kg", 96.0)

    if not context.args:
        bmi_val, bmi_cat = compute_bmi(weight, current_height)
        inline_kb = [
            [InlineKeyboardButton("📋 Scheda Profilo", callback_data="btn_profilo")],
        ]
        await update.message.reply_text(
            f"📏 Altezza attuale: {current_height} m\n"
            f"📊 IMC calcolato: {bmi_val} ({bmi_cat})\n\n"
            "Per aggiornarla scrivi:\n"
            "`/altezza <valore>` (es. `/altezza 1.85` o `/altezza 185`)",
            reply_markup=InlineKeyboardMarkup(inline_kb),
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
        inline_kb = [
            [InlineKeyboardButton("📋 Scheda Profilo", callback_data="btn_profilo")],
        ]
        await update.message.reply_text(
            "❤️ SOGLIE CARDIACHE ATTUALI:\n"
            f"• 1° Valore (FC Max): {current_max} bpm\n"
            f"• 2° Valore (Soglia Anaerobica SAFC): {current_safc} bpm\n\n"
            "Per aggiornarle scrivi:\n"
            "`/fc <fc_max> [safc]` (es. `/fc 198 178` oppure `/fc 198, 178`)\n\n"
            "💡 Regola: il 1° valore imposta SEMPRE la FC Max, il 2° valore la SAFC.\n"
            "💡 Oppure usa i comandi singoli: `/fcmax <valore>` o `/safc <valore>`.",
            reply_markup=InlineKeyboardMarkup(inline_kb),
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

    val = parse_fc_max(" ".join(context.args))
    if val is None:
        await update.message.reply_text(
            "⚠️ Valore FC Max non valido (range 100-240 bpm).",
            reply_markup=get_main_keyboard(),
        )
        return

    update_field("fc_max", val)
    await update.message.reply_text(
        f"✅ FC Max aggiornata a: {val} bpm!",
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

    val = parse_safc(" ".join(context.args))
    if val is None:
        await update.message.reply_text(
            "⚠️ Valore SAFC non valido (range 80-220 bpm).",
            reply_markup=get_main_keyboard(),
        )
        return

    update_field("safc", val)
    await update.message.reply_text(
        f"✅ Soglia Anaerobica (SAFC) aggiornata a: {val} bpm!",
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
    inline_kb = [
        [InlineKeyboardButton("🚀 Avvia Onboarding", callback_data="btn_start_onb")],
        [InlineKeyboardButton("📋 Scheda Profilo", callback_data="btn_profilo")],
    ]
    await update.message.reply_text(
        "🔄 Profilo atleta resettato!\n\n"
        "Tocca '🚀 Avvia Onboarding' qui sotto oppure invia `/start` per riavviare "
        "la procedura guidata atomica a 7 passaggi.",
        reply_markup=InlineKeyboardMarkup(inline_kb),
    )


async def menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Mostra la lista completa, scorrevole e interattiva di tutti i comandi disponibili."""
    if not is_authorized(update.effective_chat.id):
        return

    text = (
        "📜 **LISTA COMPLETA DEI COMANDI DISPONIBILI**\n"
        "─────────────────────────────────\n"
        "Scorri questa lista per consultare tutti i comandi, oppure tocca i pulsanti interattivi sottostanti:\n\n"
        "🏃‍♂️ **ALLENAMENTO & TABELLA**\n"
        "• `/ultimarun` — Mostra l'ultimo allenamento registrato e il verdetto AI\n"
        "• `/piano` — Visualizza o aggiorna la tabella settimanale (`/piano <testo>`)\n"
        "• `/target` — Modifica il passo gara obiettivo (es. `/target 5:35 min/km`)\n"
        "• `/gara` — Modifica la gara programmata (es. `/gara Mezza Terre Verdiane`)\n\n"
        "👤 **PROFILO & FISIOLOGIA ATLETA**\n"
        "• `/profilo` — Scheda anagrafica, IMC calcolato, trend del peso e soglie FC\n"
        "• `/peso` — Registra o aggiorna il peso corporeo (es. `/peso 73.8`)\n"
        "• `/altezza` — Imposta l'altezza in metri o cm (es. `/altezza 1.85`)\n"
        "• `/fc` — Aggiorna entrambe le soglie FC (`/fc <max> <safc>`, es. `/fc 195 172`)\n"
        "• `/fcmax` — Aggiorna singolarmente solo la FC Max (es. `/fcmax 202`)\n"
        "• `/safc` — Aggiorna singolarmente solo la Soglia Anaerobica (es. `/safc 178`)\n\n"
        "⚙️ **CONFIGURAZIONE & SISTEMA**\n"
        "• `/start` — Avvia la configurazione iniziale o mostra la scheda atleta\n"
        "• `/menu` — Riapre questa lista completa e scorrevole dei comandi\n"
        "• `/reset_onboarding` — Resetta il profilo e riavvia la procedura guidata a 7 step\n"
        "• `/aiuto` — Guida rapida e sintesi\n"
        "─────────────────────────────────\n"
        "💡 *Tocca uno dei pulsanti qui sotto per un'azione rapida:*"
    )
    await update.message.reply_text(
        text,
        reply_markup=get_commands_inline_keyboard(),
    )


# Alias per retrocompatibilità
aiuto_command = menu_command


# ── HANDLER CALLBACK PULSANTI INLINE GLOBALI ──────────────────────────────────


async def global_inline_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Gestisce i click sui bottoni inline sotto /profilo o /start."""
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "btn_peso":
        await query.message.reply_text(
            "⚖️ Per aggiornare il tuo peso scrivi:\n`/peso <valore>` (es. `/peso 73.8`)\n\n"
            "💡 Oppure tocca il pulsante '⚖️ Peso' sulla tastiera in basso.",
            reply_markup=get_main_keyboard(),
        )
    elif data == "btn_altezza":
        await query.message.reply_text(
            "📏 Per aggiornare l'altezza scrivi:\n`/altezza <valore>` (es. `/altezza 1.85` o `185`)",
            reply_markup=get_main_keyboard(),
        )
    elif data == "btn_fc":
        await query.message.reply_text(
            "❤️ Per aggiornare le soglie FC scrivi:\n`/fc <fc_max> [safc]` (es. `/fc 195 172`)\n"
            "Oppure usa `/fcmax <valore>` o `/safc <valore>`.",
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
    elif data == "btn_profilo":
        summary = format_profile_summary()
        await query.message.reply_text(
            summary,
            reply_markup=get_main_keyboard(),
        )
        await query.message.reply_text(
            "💡 Azioni rapide:",
            reply_markup=get_profile_inline_keyboard(),
        )
    elif data == "btn_menu":
        text = (
            "📜 **LISTA COMPLETA DEI COMANDI DISPONIBILI**\n"
            "─────────────────────────────────\n"
            "Scorri questa lista per consultare tutti i comandi, oppure tocca i pulsanti interattivi sottostanti:\n\n"
            "🏃‍♂️ **ALLENAMENTO & TABELLA**\n"
            "• `/ultimarun` — Mostra l'ultimo allenamento registrato e il verdetto AI\n"
            "• `/piano` — Visualizza o aggiorna la tabella settimanale (`/piano <testo>`)\n"
            "• `/target` — Modifica il passo gara obiettivo (es. `/target 5:35 min/km`)\n"
            "• `/gara` — Modifica la gara programmata (es. `/gara Mezza Terre Verdiane`)\n\n"
            "👤 **PROFILO & FISIOLOGIA ATLETA**\n"
            "• `/profilo` — Scheda anagrafica, IMC calcolato, trend del peso e soglie FC\n"
            "• `/peso` — Registra o aggiorna il peso corporeo (es. `/peso 73.8`)\n"
            "• `/altezza` — Imposta l'altezza in metri o cm (es. `/altezza 1.85`)\n"
            "• `/fc` — Aggiorna entrambe le soglie FC (`/fc <max> <safc>`, es. `/fc 195 172`)\n"
            "• `/fcmax` — Aggiorna singolarmente solo la FC Max (es. `/fcmax 202`)\n"
            "• `/safc` — Aggiorna singolarmente solo la Soglia Anaerobica (es. `/safc 178`)\n\n"
            "⚙️ **CONFIGURAZIONE & SISTEMA**\n"
            "• `/start` — Avvia la configurazione iniziale o mostra la scheda atleta\n"
            "• `/menu` — Riapre questa lista completa e scorrevole dei comandi\n"
            "• `/reset_onboarding` — Resetta il profilo e riavvia la procedura guidata a 7 step\n"
            "• `/aiuto` — Guida rapida e sintesi\n"
            "─────────────────────────────────"
        )
        await query.message.reply_text(
            text,
            reply_markup=get_commands_inline_keyboard(),
        )
    elif data == "btn_piano":
        current_plan = get_training_plan()
        await query.message.reply_text(
            f"📋 **PIANO DI ALLENAMENTO ATTUALE:**\n"
            "────────────────────────────────\n"
            f"{current_plan}\n\n"
            "────────────────────────────────\n"
            "💡 Per aggiornarlo scrivi: `/piano <incolla qui il tuo nuovo piano>`",
            reply_markup=get_main_keyboard(),
        )
    elif data == "btn_target":
        profile = load_profile()
        target = profile.get("passo_target", "5:35 min/km")
        await query.message.reply_text(
            f"⚡ Passo target attuale: **{target}**\n\n"
            "Per aggiornarlo scrivi: `/target <passo>` (es. `/target 5:30`)",
            reply_markup=get_main_keyboard(),
        )
    elif data == "btn_gara":
        profile = load_profile()
        gara = profile.get("obiettivo_gara", "N/D")
        await query.message.reply_text(
            f"🎯 Gara obiettivo attuale: **{gara}**\n\n"
            "Per aggiornarla scrivi: `/gara <nome>` (es. `/gara Mezza Terre Verdiane`)",
            reply_markup=get_main_keyboard(),
        )
    elif data == "btn_reset_onb":
        reset_profile()
        inline_kb = [
            [InlineKeyboardButton("🚀 Avvia Onboarding", callback_data="btn_start_onb")],
        ]
        await query.message.reply_text(
            "🔄 Profilo resettato.\n"
            "Tocca '🚀 Avvia Onboarding' qui sotto o digita `/start` per riavviare la procedura guidata!",
            reply_markup=InlineKeyboardMarkup(inline_kb),
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

    app = (
        ApplicationBuilder()
        .token(TELEGRAM_BOT_TOKEN)
        .post_init(set_bot_commands)
        .build()
    )
    app.bot_data["is_mock"] = is_mock

    # Handler conversazionale per onboarding atomico a 7 step
    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("start", start_handler),
            CallbackQueryHandler(start_callback_handler, pattern="^btn_start_onb$"),
            MessageHandler(filters.Regex(r"^(🚀 Avvia Onboarding|Avvia Onboarding)$"), start_handler),
        ],
        states={
            STEP_AGE: [
                CallbackQueryHandler(onb_cancel_callback, pattern="^onb_cancel$"),
                MessageHandler(filters.Regex(r"^(❌ Annulla|annulla|/annulla)$"), cancel_handler),
                MessageHandler(filters.TEXT & ~filters.COMMAND, step_age_handler),
            ],
            STEP_HEIGHT: [
                CallbackQueryHandler(onb_cancel_callback, pattern="^onb_cancel$"),
                CallbackQueryHandler(step_height_callback_handler, pattern="^height_"),
                MessageHandler(filters.Regex(r"^(❌ Annulla|annulla|/annulla)$"), cancel_handler),
                MessageHandler(filters.TEXT & ~filters.COMMAND, step_height_text_handler),
            ],
            STEP_WEIGHT: [
                CallbackQueryHandler(onb_cancel_callback, pattern="^onb_cancel$"),
                MessageHandler(filters.Regex(r"^(❌ Annulla|annulla|/annulla)$"), cancel_handler),
                MessageHandler(filters.TEXT & ~filters.COMMAND, step_weight_handler),
            ],
            STEP_FCMAX: [
                CallbackQueryHandler(onb_cancel_callback, pattern="^onb_cancel$"),
                CallbackQueryHandler(step_fcmax_callback_handler, pattern="^fcmax_"),
                MessageHandler(filters.Regex(r"^(❌ Annulla|annulla|/annulla)$"), cancel_handler),
                MessageHandler(filters.TEXT & ~filters.COMMAND, step_fcmax_text_handler),
            ],
            STEP_SAFC: [
                CallbackQueryHandler(onb_cancel_callback, pattern="^onb_cancel$"),
                CallbackQueryHandler(step_safc_callback_handler, pattern="^safc_"),
                MessageHandler(filters.Regex(r"^(❌ Annulla|annulla|/annulla)$"), cancel_handler),
                MessageHandler(filters.TEXT & ~filters.COMMAND, step_safc_text_handler),
            ],
            STEP_PLAN: [
                CallbackQueryHandler(onb_cancel_callback, pattern="^onb_cancel$"),
                CallbackQueryHandler(step_plan_callback_handler, pattern="^plan_"),
                MessageHandler(filters.Regex(r"^(❌ Annulla|annulla|/annulla)$"), cancel_handler),
                MessageHandler(filters.TEXT & ~filters.COMMAND, step_plan_text_handler),
            ],
            STEP_HISTORY: [
                CallbackQueryHandler(onb_cancel_callback, pattern="^onb_cancel$"),
                CallbackQueryHandler(step_history_callback_handler, pattern="^hist_"),
                MessageHandler(filters.Regex(r"^(❌ Annulla|annulla|/annulla)$"), cancel_handler),
                MessageHandler(filters.TEXT & ~filters.COMMAND, step_history_text_handler),
            ],
        },
        fallbacks=[
            CommandHandler("annulla", cancel_handler),
            MessageHandler(filters.Regex(r"^(❌ Annulla|annulla)$"), cancel_handler),
            CallbackQueryHandler(onb_cancel_callback, pattern="^onb_cancel$"),
        ],
        per_message=False,
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
    app.add_handler(CommandHandler("menu", menu_command))
    app.add_handler(CommandHandler("comandi", menu_command))
    app.add_handler(CommandHandler("aiuto", menu_command))
    app.add_handler(CommandHandler("help", menu_command))

    # Mappatura dei pulsanti della tastiera fissa (Reply Keyboard)
    app.add_handler(MessageHandler(filters.Regex("^📋 Profilo$"), profilo_command))
    app.add_handler(MessageHandler(filters.Regex("^🏃‍♂️ Ultima Run$"), ultimarun_command))
    app.add_handler(MessageHandler(filters.Regex("^⚖️ Peso$"), peso_command))
    app.add_handler(MessageHandler(filters.Regex("^📏 Altezza$"), altezza_command))
    app.add_handler(MessageHandler(filters.Regex("^❤️ Soglie FC$"), fc_command))
    app.add_handler(MessageHandler(filters.Regex("^📋 Piano$"), piano_command))
    app.add_handler(MessageHandler(filters.Regex("^⚡ Target$"), target_command))
    app.add_handler(MessageHandler(filters.Regex(r"^(📜 Lista Comandi|📜 Menu Comandi|📖 Aiuto)$"), menu_command))

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
