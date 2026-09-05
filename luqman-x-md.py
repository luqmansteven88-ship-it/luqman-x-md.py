import json
import logging
import os
import random
import re
import time
import html
from collections import defaultdict, deque
from pathlib import Path

from telegram import (
    Update,
    ChatPermissions,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    InlineQueryResultArticle,
    InputTextMessageContent,
    CopyTextButton,
)
from telegram.constants import ChatMemberStatus, ParseMode
from telegram.error import BadRequest, Forbidden
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    InlineQueryHandler,
    ContextTypes,
    filters,
)
import qrcode


# ============================================================
# CONFIGURATION
# ============================================================
BOT_NAME = "LUQMAN X MD"
OWNER_NAME = "LUQMAN SJ"
OWNER_ID = 7847425637  # <-- PUT YOUR TELEGRAM USER ID HERE
OWNER_WHATSAPP = "+255678716839"

# IMPORTANT:
# Put your NEW token in an environment variable named BOT_TOKEN.
# Never paste your token into this file.
TOKEN = "8712244204:AAGwbH3Y0aNd4ssgkpqWFD7gjRppgTXCT0M"

DATA_FILE = Path("luqman_data.json")
MODE = "public"
VERSION = "7.0.0"

logging.basicConfig(
    format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("luqman-x-md")


# ============================================================
# PERSISTENT DATA
# ============================================================
DEFAULT_DATA = {
    "groups": {},
    "notes": {},
    "stats": {"users": 0, "messages": 0},
    "sudo": [],
}


def load_data():
    if not DATA_FILE.exists():
        return DEFAULT_DATA.copy()
    try:
        with DATA_FILE.open("r", encoding="utf-8") as f:
            data = json.load(f)
        for key, value in DEFAULT_DATA.items():
            data.setdefault(key, value.copy() if isinstance(value, dict) else list(value))
        return data
    except (OSError, json.JSONDecodeError):
        logger.exception("Could not load data file. Starting with defaults.")
        return DEFAULT_DATA.copy()


DATA = load_data()


def save_data():
    tmp = DATA_FILE.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(DATA, f, ensure_ascii=False, indent=2)
    tmp.replace(DATA_FILE)


def group_settings(chat_id):
    key = str(chat_id)
    DATA["groups"].setdefault(
        key,
        {
            "antilink": False,
            "antisticker": False,
            "antispam": False,
            "antiflood": False,
            "welcome": True,
            "rules": "",
            "welcome_text": "",
            "warnings": {},
        },
    )
    return DATA["groups"][key]


# Runtime flood tracking
FLOOD_TRACKER = defaultdict(lambda: defaultdict(lambda: deque(maxlen=20)))


# ============================================================
# TEXT / UI HELPERS
# ============================================================
def esc(value):
    return html.escape(str(value), quote=False)


def footer(text):
    return f"{text}\n\n<i>— LUQMAN X MD • {VERSION}</i>"


def is_owner_or_sudo(user_id):
    return user_id == OWNER_ID or user_id in DATA.get("sudo", [])


async def is_admin(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id=None):
    chat = update.effective_chat
    if not chat or chat.type not in ("group", "supergroup"):
        return False
    user_id = user_id or update.effective_user.id
    try:
        member = await context.bot.get_chat_member(chat.id, user_id)
        return member.status in (ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER)
    except (BadRequest, Forbidden):
        return False


async def bot_is_admin(update, context):
    chat = update.effective_chat
    if not chat or chat.type not in ("group", "supergroup"):
        return False
    try:
        member = await context.bot.get_chat_member(chat.id, context.bot.id)
        if member.status in (ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER):
            return True
    except (BadRequest, Forbidden):
        pass

    if update.effective_message:
        await update.effective_message.reply_text(
            footer("❌ <b>Permission denied.</b>\nPlease make LUQMAN X MD an administrator first."),
            parse_mode=ParseMode.HTML,
        )
    return False


async def require_control(update, context):
    if not is_owner_or_sudo(update.effective_user.id):
        await update.effective_message.reply_text(
            footer("⛔ <b>Owner/Sudo only.</b>"),
            parse_mode=ParseMode.HTML,
        )
        return False
    if update.effective_chat.type not in ("group", "supergroup"):
        await update.effective_message.reply_text(
            footer("ℹ️ This command is designed for groups."),
            parse_mode=ParseMode.HTML,
        )
        return False
    if not await bot_is_admin(update, context):
        return False
    return True


def back_button():
    return InlineKeyboardButton("‹ Back", callback_data="menu:main")


# ============================================================
# MAIN MENU
# ============================================================
def main_menu_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🛡 Group", callback_data="menu:group"),
            InlineKeyboardButton("🧰 Tools", callback_data="menu:tools"),
        ],
        [
            InlineKeyboardButton("👤 User", callback_data="menu:user"),
            InlineKeyboardButton("🎮 Fun", callback_data="menu:fun"),
        ],
        [
            InlineKeyboardButton("⚙️ Settings", callback_data="menu:settings"),
            InlineKeyboardButton("👑 Owner", callback_data="menu:owner"),
        ],
        [
            InlineKeyboardButton("⚡ Inline Mode", switch_inline_query_current_chat=""),
        ],
    ])


def group_menu_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🚫 Ban", callback_data="help:ban"),
            InlineKeyboardButton("👢 Kick", callback_data="help:kick"),
        ],
        [
            InlineKeyboardButton("🔇 Mute", callback_data="help:mute"),
            InlineKeyboardButton("⚠️ Warn", callback_data="help:warn"),
        ],
        [
            InlineKeyboardButton("🔗 Anti-Link", callback_data="setting:antilink"),
            InlineKeyboardButton("🌊 Anti-Flood", callback_data="setting:antiflood"),
        ],
        [
            InlineKeyboardButton("🛡 Anti-Spam", callback_data="setting:antispam"),
            InlineKeyboardButton("🧩 Anti-Sticker", callback_data="setting:antisticker"),
        ],
        [
            InlineKeyboardButton("👋 Welcome", callback_data="setting:welcome"),
            InlineKeyboardButton("📜 Rules", callback_data="menu:rules"),
        ],
        [
            InlineKeyboardButton("👮 Admins", callback_data="help:admins"),
            InlineKeyboardButton("📊 Group Info", callback_data="help:ginfo"),
        ],
        [back_button()],
    ])


def tools_menu_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔤 Font", callback_data="help:font"),
            InlineKeyboardButton("🧮 Math", callback_data="help:math"),
        ],
        [
            InlineKeyboardButton("🔳 QR Code", callback_data="help:qr"),
            InlineKeyboardButton("📝 Notes", callback_data="menu:notes"),
        ],
        [InlineKeyboardButton("⏰ Remind", callback_data="help:remind")],
        [back_button()],
    ])


def user_menu_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🆔 My ID", callback_data="help:id"),
            InlineKeyboardButton("👤 My Info", callback_data="help:info"),
        ],
        [back_button()],
    ])


def fun_menu_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🎲 Dice", callback_data="fun:dice"),
            InlineKeyboardButton("🎯 Dart", callback_data="fun:dart"),
        ],
        [
            InlineKeyboardButton("⚽ Football", callback_data="fun:football"),
            InlineKeyboardButton("❤️ Love", callback_data="help:love"),
        ],
        [
            InlineKeyboardButton("😂 Joke", callback_data="fun:joke"),
        ],
        [back_button()],
    ])


def settings_keyboard(chat_id):
    s = group_settings(chat_id)

    def label(icon, name, key):
        return f"{icon} {name}: {'ON' if s[key] else 'OFF'}"

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(label("🔗", "Anti-Link", "antilink"), callback_data="toggle:antilink"),
            InlineKeyboardButton(label("🧩", "Sticker", "antisticker"), callback_data="toggle:antisticker"),
        ],
        [
            InlineKeyboardButton(label("🛡", "Anti-Spam", "antispam"), callback_data="toggle:antispam"),
            InlineKeyboardButton(label("🌊", "Anti-Flood", "antiflood"), callback_data="toggle:antiflood"),
        ],
        [
            InlineKeyboardButton(label("👋", "Welcome", "welcome"), callback_data="toggle:welcome"),
        ],
        [InlineKeyboardButton("📜 View Rules", callback_data="menu:rules")],
        [back_button()],
    ])


# ============================================================
# COMMAND HELP
# ============================================================
COMMAND_HELP = {
    "ban": "Reply to a member's message with /ban.",
    "kick": "Reply to a member's message with /kick.",
    "mute": "Reply to a member's message with /mute.",
    "unmute": "Reply to a member's message with /unmute.",
    "warn": "Reply to a member's message with /warn. 3 warnings = ban.",
    "unwarn": "Reply to a member's message with /unwarn.",
    "admins": "Show the group's administrators.",
    "ginfo": "Show group information.",
    "font": "Usage: /font your text",
    "math": "Usage: /math 12*(4+2)",
    "qr": "Usage: /qr https://example.com",
    "id": "Show your Telegram ID.",
    "info": "Reply to a user's message with /info.",
    "love": "Reply to a user's message with /love.",
    "remind": "Usage: /remind 10m message",
}


async def help_command(update, context):
    if context.args and context.args[0].lower() in COMMAND_HELP:
        name = context.args[0].lower()
        await update.message.reply_text(
            footer(f"📘 <b>/{name}</b>\n\n{esc(COMMAND_HELP[name])}"),
            parse_mode=ParseMode.HTML,
        )
        return

    text = (
        "📚 <b>LUQMAN X MD — HELP</b>\n\n"
        "🛡 <b>Group</b>\n"
        "/ban • /kick • /mute • /unmute\n"
        "/warn • /unwarn • /admins • /ginfo\n"
        "/antilink • /antisticker • /antispam • /antiflood\n"
        "/setwelcome • /welcome • /setrules • /rules\n\n"
        "🧰 <b>Tools</b>\n"
        "/font • /math • /qr • /save • /get • /notes • /remind\n\n"
        "👤 <b>User</b>\n"
        "/id • /info\n\n"
        "🎮 <b>Fun</b>\n"
        "/dice • /dart • /football • /love • /joke\n\n"
        "👑 <b>Owner</b>\n"
        "/owner • /ownerpanel • /alive • /ping"
    )
    await update.message.reply_text(
        footer(text),
        parse_mode=ParseMode.HTML,
        reply_markup=main_menu_keyboard(),
    )


async def menu_command(update, context):
    text = (
        "🤖 <b>LUQMAN X MD</b>\n\n"
        "Welcome to your Telegram control center.\n"
        "Choose a section below."
    )
    await update.message.reply_text(
        footer(text),
        parse_mode=ParseMode.HTML,
        reply_markup=main_menu_keyboard(),
    )
async def start_command(update, context):
    text = (
        "🤖 <b>LUQMAN X MD</b>\n\n"
        "Welcome! Your Telegram assistant is online.\n\n"
        "Use /menu to open the control panel."
    )

    await update.message.reply_text(
        footer(text),
        parse_mode=ParseMode.HTML,
        reply_markup=main_menu_keyboard(),
    )


async def alive_command(update, context):
    await update.message.reply_text(
        footer(
            "🟢 <b>LUQMAN X MD is online.</b>\n\n"
            f"Version: <b>{VERSION}</b>\n"
            "Status: <b>Active</b>"
        ),
        parse_mode=ParseMode.HTML,
    )


async def ping_command(update, context):
    start = time.perf_counter()
    msg = await update.message.reply_text("⚡ Checking...")
    ms = (time.perf_counter() - start) * 1000
    await msg.edit_text(
        footer(f"⚡ <b>Pong!</b>\nResponse: <code>{ms:.0f} ms</code>"),
        parse_mode=ParseMode.HTML,
    )


async def owner_command(update, context):
    wa = OWNER_WHATSAPP.replace("+", "")
    buttons = InlineKeyboardMarkup([
        [InlineKeyboardButton("💬 Contact Owner", url=f"https://wa.me/{wa}")],
        [InlineKeyboardButton("🆔 Copy Telegram ID", copy_text=CopyTextButton(str(OWNER_ID)))],
    ])
    text = (
        "👑 <b>OWNER</b>\n\n"
        f"Name: <b>{esc(OWNER_NAME)}</b>\n"
        f"Telegram ID: <code>{OWNER_ID}</code>\n"
        f"WhatsApp: <code>{esc(OWNER_WHATSAPP)}</code>"
    )
    await update.message.reply_text(
        footer(text), parse_mode=ParseMode.HTML, reply_markup=buttons
    )


async def ownerpanel_command(update, context):
    if not is_owner_or_sudo(update.effective_user.id):
        return
    groups = len(DATA.get("groups", {}))
    users = DATA.get("stats", {}).get("users", 0)
    messages = DATA.get("stats", {}).get("messages", 0)
    text = (
        "👑 <b>OWNER CONTROL</b>\n\n"
        f"Groups tracked: <b>{groups}</b>\n"
        f"Users seen: <b>{users}</b>\n"
        f"Messages processed: <b>{messages}</b>\n"
        f"Mode: <b>{MODE.upper()}</b>"
    )
    await update.message.reply_text(footer(text), parse_mode=ParseMode.HTML)


# ============================================================
# USER TOOLS
# ============================================================
async def id_command(update, context):
    user = update.effective_user
    text = (
        "🆔 <b>IDENTIFICATION</b>\n\n"
        f"Name: <b>{esc(user.full_name)}</b>\n"
        f"Telegram ID: <code>{user.id}</code>"
    )
    await update.message.reply_text(
        footer(text),
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("Copy ID", copy_text=CopyTextButton(str(user.id)))]
        ]),
    )


async def info_command(update, context):
    user = update.effective_user
    if update.message.reply_to_message:
        user = update.message.reply_to_message.from_user

    username = f"@{user.username}" if user.username else "Not set"
    text = (
        "👤 <b>USER PROFILE</b>\n\n"
        f"Name: <b>{esc(user.full_name)}</b>\n"
        f"Username: <b>{esc(username)}</b>\n"
        f"ID: <code>{user.id}</code>\n"
        f"Bot account: <b>{'Yes' if user.is_bot else 'No'}</b>"
    )
    await update.message.reply_text(footer(text), parse_mode=ParseMode.HTML)


async def font_command(update, context):
    if not context.args:
        await update.message.reply_text(
            footer("🔤 <b>Usage:</b> <code>/font Hello world</code>"),
            parse_mode=ParseMode.HTML,
        )
        return

    text = " ".join(context.args)
    normal = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    mono = (
        "𝚊𝚋𝚌𝚍𝚎𝚏𝚐𝚑𝚒𝚓𝚔𝚕𝚖𝚗𝚘𝚙𝚚𝚛𝚜𝚝𝚞𝚟𝚠𝚡𝚢𝚣"
        "𝙰𝙱𝙲𝙳𝙴𝙵𝙶𝙷𝙸𝙹𝙺𝙻𝙼𝙽𝙾𝙿𝚀𝚁𝚂𝚃𝚄𝚅𝚆𝚇𝚈𝚉"
        "𝟶𝟷𝟸𝟹𝟺𝟻𝟼𝟽𝟾𝟿"
    )
    converted = text.translate(str.maketrans(normal, mono))
    await update.message.reply_text(
        footer(f"🔤 <b>STYLED TEXT</b>\n\n<code>{esc(converted)}</code>"),
        parse_mode=ParseMode.HTML,
    )


async def math_command(update, context):
    if not context.args:
        await update.message.reply_text(
            footer("🧮 <b>Usage:</b> <code>/math 12*(4+2)</code>"),
            parse_mode=ParseMode.HTML,
        )
        return

    expr = "".join(context.args)
    if len(expr) > 100 or not re.fullmatch(r"[0-9+\-*/(). ]+", expr):
        await update.message.reply_text(
            footer("❌ Only basic numbers and + - * / ( ) . are allowed."),
            parse_mode=ParseMode.HTML,
        )
        return

    try:
        # Restricted globals/locals; regex above prevents names and attribute access.
        result = eval(expr, {"__builtins__": {}}, {})
        await update.message.reply_text(
            footer(f"🧮 <b>RESULT</b>\n\n<code>{esc(expr)}</code> = <b>{esc(result)}</b>"),
            parse_mode=ParseMode.HTML,
        )
    except Exception:
        await update.message.reply_text(
            footer("❌ I could not calculate that expression."),
            parse_mode=ParseMode.HTML,
        )


async def qr_command(update, context):
    if not context.args:
        await update.message.reply_text(
            footer("🔳 <b>Usage:</b> <code>/qr https://example.com</code>"),
            parse_mode=ParseMode.HTML,
        )
        return

    value = " ".join(context.args).strip()
    if len(value) > 2000:
        await update.message.reply_text(
            footer("❌ The text is too long for a QR code."),
            parse_mode=ParseMode.HTML,
        )
        return

    path = Path(f"qr_{update.effective_user.id}_{int(time.time())}.png")
    try:
        img = qrcode.make(value)
        img.save(path)
        with path.open("rb") as photo:
            await update.message.reply_photo(
                photo=photo,
                caption=footer("🔳 <b>QR CODE</b>"),
                parse_mode=ParseMode.HTML,
            )
    finally:
        path.unlink(missing_ok=True)


# ============================================================
# NOTES
# ============================================================
async def save_note_command(update, context):
    if len(context.args) < 2:
        await update.message.reply_text(
            footer("📝 <b>Usage:</b> <code>/save name your text here</code>"),
            parse_mode=ParseMode.HTML,
        )
        return

    name = context.args[0].lower()
    value = " ".join(context.args[1:]).strip()
    chat_key = str(update.effective_chat.id)
    DATA["notes"].setdefault(chat_key, {})[name] = value
    save_data()
    await update.message.reply_text(
        footer(f"✅ Note <b>{esc(name)}</b> saved."),
        parse_mode=ParseMode.HTML,
    )


async def get_note_command(update, context):
    if not context.args:
        await update.message.reply_text(
            footer("📝 <b>Usage:</b> <code>/get name</code>"),
            parse_mode=ParseMode.HTML,
        )
        return

    name = context.args[0].lower()
    value = DATA.get("notes", {}).get(str(update.effective_chat.id), {}).get(name)
    if value is None:
        await update.message.reply_text(
            footer(f"❌ No note named <b>{esc(name)}</b> was found."),
            parse_mode=ParseMode.HTML,
        )
        return

    await update.message.reply_text(
        footer(f"📝 <b>{esc(name)}</b>\n\n{esc(value)}"),
        parse_mode=ParseMode.HTML,
    )


async def notes_command(update, context):
    notes = DATA.get("notes", {}).get(str(update.effective_chat.id), {})
    if not notes:
        await update.message.reply_text(
            footer("📝 No saved notes yet."),
            parse_mode=ParseMode.HTML,
        )
        return
    names = "\n".join(f"• <code>{esc(k)}</code>" for k in sorted(notes))
    await update.message.reply_text(
        footer(f"📝 <b>SAVED NOTES</b>\n\n{names}"),
        parse_mode=ParseMode.HTML,
    )


# ============================================================
# REMINDERS
# ============================================================
TIME_UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400}


async def remind_command(update, context):
    if len(context.args) < 2:
        await update.message.reply_text(
            footer("⏰ <b>Usage:</b> <code>/remind 10m drink water</code>"),
            parse_mode=ParseMode.HTML,
        )
        return

    match = re.fullmatch(r"([1-9][0-9]*)([smhd])", context.args[0].lower())
    if not match:
        await update.message.reply_text(
            footer("❌ Time must look like <code>30s</code>, <code>10m</code>, <code>2h</code> or <code>1d</code>."),
            parse_mode=ParseMode.HTML,
        )
        return

    amount = int(match.group(1))
    unit = TIME_UNITS[match.group(2)]
    seconds = amount * unit
    if seconds > 7 * 86400:
        await update.message.reply_text(
            footer("❌ The maximum reminder time is 7 days."),
            parse_mode=ParseMode.HTML,
        )
        return

    reminder_text = " ".join(context.args[1:])

    async def send_reminder(ctx):
        await ctx.bot.send_message(
            chat_id=update.effective_chat.id,
            text=footer(
                f"⏰ <b>REMINDER</b>\n\n{esc(reminder_text)}\n\n"
                f"Set by: <b>{esc(update.effective_user.full_name)}</b>"
            ),
            parse_mode=ParseMode.HTML,
        )

    context.job_queue.run_once(send_reminder, when=seconds)
    await update.message.reply_text(
        footer(f"⏰ Reminder set for <b>{esc(context.args[0])}</b>."),
        parse_mode=ParseMode.HTML,
    )


# ============================================================
# GROUP MODERATION
# ============================================================
async def target_user(update):
    if update.message.reply_to_message:
        return update.message.reply_to_message.from_user
    return None


async def ban_command(update, context):
    if not await require_control(update, context):
        return
    target = await target_user(update)
    if not target:
        await update.message.reply_text(
            footer("🚫 Reply to the member's message and use <code>/ban</code>."),
            parse_mode=ParseMode.HTML,
        )
        return
    if await is_admin(update, context, target.id):
        await update.message.reply_text(
            footer("❌ I cannot ban a group administrator."),
            parse_mode=ParseMode.HTML,
        )
        return
    try:
        await context.bot.ban_chat_member(update.effective_chat.id, target.id)
        await update.message.reply_text(
            footer(f"🚫 <b>{esc(target.full_name)}</b> has been banned."),
            parse_mode=ParseMode.HTML,
        )
    except (BadRequest, Forbidden):
        await update.message.reply_text(
            footer("❌ I could not ban that member. Check my admin permissions."),
            parse_mode=ParseMode.HTML,
        )


async def unban_command(update, context):
    if not await require_control(update, context):
        return
    target_id = None
    target = await target_user(update)
    if target:
        target_id = target.id
    elif context.args:
        try:
            target_id = int(context.args[0])
        except ValueError:
            pass

    if not target_id:
        await update.message.reply_text(
            footer("Usage: reply to a user or use <code>/unban USER_ID</code>."),
            parse_mode=ParseMode.HTML,
        )
        return

    try:
        await context.bot.unban_chat_member(update.effective_chat.id, target_id, only_if_banned=True)
        await update.message.reply_text(
            footer("✅ Member unbanned successfully."),
            parse_mode=ParseMode.HTML,
        )
    except (BadRequest, Forbidden):
        await update.message.reply_text(
            footer("❌ I could not unban that user."),
            parse_mode=ParseMode.HTML,
        )


async def mute_command(update, context):
    if not await require_control(update, context):
        return
    target = await target_user(update)
    if not target:
        await update.message.reply_text(
            footer("🔇 Reply to a member's message and use <code>/mute</code>."),
            parse_mode=ParseMode.HTML,
        )
        return
    if await is_admin(update, context, target.id):
        await update.message.reply_text(
            footer("❌ I cannot mute a group administrator."),
            parse_mode=ParseMode.HTML,
        )
        return

    try:
        await context.bot.restrict_chat_member(
            update.effective_chat.id,
            target.id,
            permissions=ChatPermissions(can_send_messages=False),
        )
        await update.message.reply_text(
            footer(f"🔇 <b>{esc(target.full_name)}</b> has been muted."),
            parse_mode=ParseMode.HTML,
        )
    except (BadRequest, Forbidden):
        await update.message.reply_text(
            footer("❌ I could not mute that member."),
            parse_mode=ParseMode.HTML,
        )


async def unmute_command(update, context):
    if not await require_control(update, context):
        return
    target = await target_user(update)
    if not target:
        await update.message.reply_text(
            footer("🔊 Reply to a member's message and use <code>/unmute</code>."),
            parse_mode=ParseMode.HTML,
        )
        return

    permissions = ChatPermissions(
        can_send_messages=True,
        can_send_audios=True,
        can_send_documents=True,
        can_send_photos=True,
        can_send_videos=True,
        can_send_video_notes=True,
        can_send_voice_notes=True,
        can_send_polls=True,
        can_send_other_messages=True,
        can_add_web_page_previews=True,
    )
    try:
        await context.bot.restrict_chat_member(
            update.effective_chat.id, target.id, permissions=permissions
        )
        await update.message.reply_text(
            footer(f"🔊 <b>{esc(target.full_name)}</b> has been unmuted."),
            parse_mode=ParseMode.HTML,
        )
    except (BadRequest, Forbidden):
        await update.message.reply_text(
            footer("❌ I could not unmute that member."),
            parse_mode=ParseMode.HTML,
        )


async def warn_command(update, context):
    if not await require_control(update, context):
        return
    target = await target_user(update)
    if not target:
        await update.message.reply_text(
            footer("⚠️ Reply to a member's message and use <code>/warn</code>."),
            parse_mode=ParseMode.HTML,
        )
        return
    if await is_admin(update, context, target.id):
        await update.message.reply_text(
            footer("❌ Administrators are not included in the warning system."),
            parse_mode=ParseMode.HTML,
        )
        return

    s = group_settings(update.effective_chat.id)
    warnings = s["warnings"]
    key = str(target.id)
    warnings[key] = int(warnings.get(key, 0)) + 1
    count = warnings[key]

    if count >= 3:
        try:
            await context.bot.ban_chat_member(update.effective_chat.id, target.id)
            warnings[key] = 0
            save_data()
            await update.message.reply_text(
                footer(f"🚨 <b>{esc(target.full_name)}</b> reached 3/3 warnings and was banned."),
                parse_mode=ParseMode.HTML,
            )
        except (BadRequest, Forbidden):
            await update.message.reply_text(
                footer("❌ 3/3 warnings reached, but I could not ban the member."),
                parse_mode=ParseMode.HTML,
            )
    else:
        save_data()
        await update.message.reply_text(
            footer(f"⚠️ <b>{esc(target.full_name)}</b> — warning <b>{count}/3</b>."),
            parse_mode=ParseMode.HTML,
        )


async def unwarn_command(update, context):
    if not await require_control(update, context):
        return
    target = await target_user(update)
    if not target:
        await update.message.reply_text(
            footer("⚠️ Reply to a member's message and use <code>/unwarn</code>."),
            parse_mode=ParseMode.HTML,
        )
        return

    s = group_settings(update.effective_chat.id)
    s["warnings"][str(target.id)] = 0
    save_data()
    await update.message.reply_text(
        footer(f"✅ Warnings cleared for <b>{esc(target.full_name)}</b>."),
        parse_mode=ParseMode.HTML,
    )


async def kick_command(update, context):
    if not await require_control(update, context):
        return
    target = await target_user(update)
    if not target:
        await update.message.reply_text(
            footer("👢 Reply to a member's message and use <code>/kick</code>."),
            parse_mode=ParseMode.HTML,
        )
        return
    if await is_admin(update, context, target.id):
        await update.message.reply_text(
            footer("❌ I cannot kick a group administrator."),
            parse_mode=ParseMode.HTML,
        )
        return

    try:
        await context.bot.ban_chat_member(update.effective_chat.id, target.id)
        await context.bot.unban_chat_member(update.effective_chat.id, target.id)
        await update.message.reply_text(
            footer(f"👢 <b>{esc(target.full_name)}</b> has been removed from the group."),
            parse_mode=ParseMode.HTML,
        )
    except (BadRequest, Forbidden):
        await update.message.reply_text(
            footer("❌ I could not remove that member."),
            parse_mode=ParseMode.HTML,
        )


async def pin_command(update, context):
    if not await require_control(update, context):
        return
    if not update.message.reply_to_message:
        await update.message.reply_text(
            footer("📌 Reply to a message and use <code>/pin</code>."),
            parse_mode=ParseMode.HTML,
        )
        return
    try:
        await context.bot.pin_chat_message(
            update.effective_chat.id,
            update.message.reply_to_message.message_id,
            disable_notification=True,
        )
        await update.message.reply_text(footer("📌 Message pinned."), parse_mode=ParseMode.HTML)
    except (BadRequest, Forbidden):
        await update.message.reply_text(
            footer("❌ I could not pin that message."),
            parse_mode=ParseMode.HTML,
        )


async def unpin_command(update, context):
    if not await require_control(update, context):
        return
    try:
        await context.bot.unpin_chat_message(update.effective_chat.id)
        await update.message.reply_text(footer("📌 Pinned message removed."), parse_mode=ParseMode.HTML)
    except (BadRequest, Forbidden):
        await update.message.reply_text(
            footer("❌ There is no pinned message I can remove."),
            parse_mode=ParseMode.HTML,
        )


async def del_command(update, context):
    if not await require_control(update, context):
        return
    if not update.message.reply_to_message:
        await update.message.reply_text(
            footer("🗑 Reply to a message and use <code>/del</code>."),
            parse_mode=ParseMode.HTML,
        )
        return
    try:
        await update.message.reply_to_message.delete()
        await update.message.delete()
    except (BadRequest, Forbidden):
        pass


# ============================================================
# GROUP SETTINGS
# ============================================================
async def toggle_setting(update, context, key):
    if not await require_control(update, context):
        return
    s = group_settings(update.effective_chat.id)
    s[key] = not bool(s[key])
    save_data()
    await update.effective_message.reply_text(
        footer(f"⚙️ <b>{key.upper()}</b> is now <b>{'ON' if s[key] else 'OFF'}</b>."),
        parse_mode=ParseMode.HTML,
    )


async def antilink_command(update, context):
    if not await require_control(update, context):
        return
    if not context.args or context.args[0].lower() not in ("on", "off"):
        await update.message.reply_text(
            footer("Usage: <code>/antilink on</code> or <code>/antilink off</code>."),
            parse_mode=ParseMode.HTML,
        )
        return
    s = group_settings(update.effective_chat.id)
    s["antilink"] = context.args[0].lower() == "on"
    save_data()
    await update.message.reply_text(
        footer(f"🔗 Anti-Link: <b>{'ON' if s['antilink'] else 'OFF'}</b>"),
        parse_mode=ParseMode.HTML,
    )


async def antisticker_command(update, context):
    if not await require_control(update, context):
        return
    if not context.args or context.args[0].lower() not in ("on", "off"):
        await update.message.reply_text(
            footer("Usage: <code>/antisticker on</code> or <code>/antisticker off</code>."),
            parse_mode=ParseMode.HTML,
        )
        return
    s = group_settings(update.effective_chat.id)
    s["antisticker"] = context.args[0].lower() == "on"
    save_data()
    await update.message.reply_text(
        footer(f"🧩 Anti-Sticker: <b>{'ON' if s['antisticker'] else 'OFF'}</b>"),
        parse_mode=ParseMode.HTML,
    )


async def antispam_command(update, context):
    if not await require_control(update, context):
        return
    if not context.args or context.args[0].lower() not in ("on", "off"):
        await update.message.reply_text(
            footer("Usage: <code>/antispam on</code> or <code>/antispam off</code>."),
            parse_mode=ParseMode.HTML,
        )
        return
    s = group_settings(update.effective_chat.id)
    s["antispam"] = context.args[0].lower() == "on"
    save_data()
    await update.message.reply_text(
        footer(f"🛡 Anti-Spam: <b>{'ON' if s['antispam'] else 'OFF'}</b>"),
        parse_mode=ParseMode.HTML,
    )


async def antiflood_command(update, context):
    if not await require_control(update, context):
        return
    if not context.args or context.args[0].lower() not in ("on", "off"):
        await update.message.reply_text(
            footer("Usage: <code>/antiflood on</code> or <code>/antiflood off</code>."),
            parse_mode=ParseMode.HTML,
        )
        return
    s = group_settings(update.effective_chat.id)
    s["antiflood"] = context.args[0].lower() == "on"
    save_data()
    await update.message.reply_text(
        footer(f"🌊 Anti-Flood: <b>{'ON' if s['antiflood'] else 'OFF'}</b>"),
        parse_mode=ParseMode.HTML,
    )


async def setwelcome_command(update, context):
    if not await require_control(update, context):
        return
    if not context.args:
        await update.message.reply_text(
            footer("Usage: <code>/setwelcome Welcome {name} to {group}!</code>"),
            parse_mode=ParseMode.HTML,
        )
        return
    s = group_settings(update.effective_chat.id)
    s["welcome_text"] = " ".join(context.args)
    s["welcome"] = True
    save_data()
    await update.message.reply_text(
        footer("👋 Welcome message saved."),
        parse_mode=ParseMode.HTML,
    )


async def welcome_command(update, context):
    if not await require_control(update, context):
        return
    s = group_settings(update.effective_chat.id)
    if not s["welcome_text"]:
        await update.message.reply_text(
            footer("👋 No custom welcome message is set."),
            parse_mode=ParseMode.HTML,
        )
        return
    await update.message.reply_text(
        footer(f"👋 <b>Current welcome</b>\n\n{esc(s['welcome_text'])}"),
        parse_mode=ParseMode.HTML,
    )


async def setrules_command(update, context):
    if not await require_control(update, context):
        return
    if not context.args:
        await update.message.reply_text(
            footer("Usage: <code>/setrules Be respectful. No spam.</code>"),
            parse_mode=ParseMode.HTML,
        )
        return
    s = group_settings(update.effective_chat.id)
    s["rules"] = " ".join(context.args)
    save_data()
    await update.message.reply_text(footer("📜 Group rules saved."), parse_mode=ParseMode.HTML)


async def rules_command(update, context):
    s = group_settings(update.effective_chat.id)
    if not s["rules"]:
        await update.message.reply_text(
            footer("📜 No group rules have been set."),
            parse_mode=ParseMode.HTML,
        )
        return
    await update.message.reply_text(
        footer(f"📜 <b>GROUP RULES</b>\n\n{esc(s['rules'])}"),
        parse_mode=ParseMode.HTML,
    )


async def admins_command(update, context):
    if update.effective_chat.type not in ("group", "supergroup"):
        return
    try:
        admins = await context.bot.get_chat_administrators(update.effective_chat.id)
        lines = []
        for admin in admins:
            name = esc(admin.user.full_name)
            username = f" @{esc(admin.user.username)}" if admin.user.username else ""
            lines.append(f"• <b>{name}</b>{username}")
        await update.message.reply_text(
            footer("👮 <b>GROUP ADMINS</b>\n\n" + "\n".join(lines)),
            parse_mode=ParseMode.HTML,
        )
    except (BadRequest, Forbidden):
        await update.message.reply_text(
            footer("❌ I could not fetch the administrator list."),
            parse_mode=ParseMode.HTML,
        )


async def ginfo_command(update, context):
    chat = update.effective_chat
    if chat.type not in ("group", "supergroup"):
        return
    try:
        count = await context.bot.get_chat_member_count(chat.id)
        s = group_settings(chat.id)
        text = (
            "📊 <b>GROUP INFORMATION</b>\n\n"
            f"Name: <b>{esc(chat.title or 'Unknown')}</b>\n"
            f"ID: <code>{chat.id}</code>\n"
            f"Members: <b>{count}</b>\n\n"
            "🛡 <b>Protection</b>\n"
            f"Anti-Link: <b>{'ON' if s['antilink'] else 'OFF'}</b>\n"
            f"Anti-Spam: <b>{'ON' if s['antispam'] else 'OFF'}</b>\n"
            f"Anti-Flood: <b>{'ON' if s['antiflood'] else 'OFF'}</b>\n"
            f"Welcome: <b>{'ON' if s['welcome'] else 'OFF'}</b>"
        )
        await update.message.reply_text(footer(text), parse_mode=ParseMode.HTML)
    except (BadRequest, Forbidden):
        await update.message.reply_text(
            footer("❌ I could not read this group's information."),
            parse_mode=ParseMode.HTML,
        )


# ============================================================
# FUN
# ============================================================
JOKES = [
    "I told my computer I needed a break. Now it keeps showing me vacation ads.",
    "My phone battery and I have something in common: we both lose energy when people ask too many questions.",
    "I tried to organize my life, but the folder was already full of screenshots.",
    "I wanted to be productive today. Then my chair said, 'Maybe tomorrow.'",
    "My Wi-Fi has two moods: working perfectly and making me question my life choices.",
    "I opened the fridge three times. Still no new food. Technology has failed me.",
    "I love deadlines. They make a beautiful whooshing sound as they fly past.",
    "I asked my keyboard for advice. It said, 'Just keep typing.'",
    "My alarm clock and I have a toxic relationship. Every morning it starts the argument.",
    "I don't need a motivational quote. I need 8 more hours of sleep.",
    "I started a book about anti-gravity. It's impossible to put down.",
    "Why did the developer go broke? Because they used up all their cache.",
    "I told my code to behave. It responded with another error.",
    "My laptop is like a family member: it overheats when too many people are around.",
    "I wanted to make a joke about UDP, but I'm not sure you'd get it.",
]


async def joke_command(update, context):
    await update.message.reply_text(
        footer(f"😂 <b>RANDOM JOKE</b>\n\n{esc(random.choice(JOKES))}"),
        parse_mode=ParseMode.HTML,
    )


async def dice_command(update, context):
    msg = await update.message.reply_dice(emoji="🎲")
    await update.message.reply_text(
        footer(f"🎲 <b>DICE</b>\n\nResult: <b>{msg.dice.value}</b>"),
        parse_mode=ParseMode.HTML,
    )


async def dart_command(update, context):
    msg = await update.message.reply_dice(emoji="🎯")
    await update.message.reply_text(
        footer(f"🎯 <b>DART</b>\n\nScore: <b>{msg.dice.value}/6</b>"),
        parse_mode=ParseMode.HTML,
    )


async def football_command(update, context):
    msg = await update.message.reply_dice(emoji="⚽")
    result = msg.dice.value
    text = "GOAL! 🔥" if result in (3, 4, 5) else "Saved by the keeper! 🧤"
    await update.message.reply_text(
        footer(f"⚽ <b>FOOTBALL</b>\n\n{text}\nScore: <b>{result}/5</b>"),
        parse_mode=ParseMode.HTML,
    )


async def love_command(update, context):
    target = await target_user(update)
    if not target:
        await update.message.reply_text(
            footer("❤️ Reply to someone's message and use <code>/love</code>."),
            parse_mode=ParseMode.HTML,
        )
        return
    score = random.randint(1, 100)
    if score <= 25:
        comment = "Not bad. Keep the friendship strong. 🙂"
    elif score <= 50:
        comment = "There is a connection. Give it time. 💛"
    elif score <= 75:
        comment = "Strong chemistry detected. ❤️"
    else:
        comment = "That score is dangerously wholesome. 💖"

    text = (
        "❤️ <b>LOVE MATCH</b>\n\n"
        f"{esc(update.effective_user.first_name)} + {esc(target.first_name)}\n\n"
        f"Compatibility: <b>{score}%</b>\n"
        f"{esc(comment)}"
    )
    await update.message.reply_text(footer(text), parse_mode=ParseMode.HTML)


# ============================================================
# INLINE MODE
# ============================================================
async def inline_query_handler(update, context):
    query = update.inline_query.query.strip().lower()
    results = []

    if not query or "owner" in query:
        wa = OWNER_WHATSAPP.replace("+", "")
        markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("💬 Contact Owner", url=f"https://wa.me/{wa}")]
        ])
        results.append(
            InlineQueryResultArticle(
                id="owner",
                title="👑 Owner Contact",
                description="Show LUQMAN X MD owner contact.",
                input_message_content=InputTextMessageContent(
                    f"👑 <b>LUQMAN X MD — OWNER</b>\n\n"
                    f"Name: <b>{esc(OWNER_NAME)}</b>\n"
                    f"Telegram ID: <code>{OWNER_ID}</code>\n"
                    f"WhatsApp: <code>{esc(OWNER_WHATSAPP)}</code>",
                    parse_mode=ParseMode.HTML,
                ),
                reply_markup=markup,
            )
        )

    if not query or "joke" in query:
        joke = random.choice(JOKES)
        results.append(
            InlineQueryResultArticle(
                id=f"joke{random.randint(1, 999999)}",
                title="😂 Random Joke",
                description="Send a clean English joke.",
                input_message_content=InputTextMessageContent(
                    f"😂 <b>RANDOM JOKE</b>\n\n{esc(joke)}\n\n<i>— LUQMAN X MD</i>",
                    parse_mode=ParseMode.HTML,
                ),
            )
        )

    if not query or "info" in query:
        results.append(
            InlineQueryResultArticle(
                id="botinfo",
                title="🤖 Bot Info",
                description="Show LUQMAN X MD status.",
                input_message_content=InputTextMessageContent(
                    f"🤖 <b>{esc(BOT_NAME)}</b>\n\n"
                    f"Status: <b>Online</b>\n"
                    f"Version: <b>{VERSION}</b>\n"
                    f"Mode: <b>{MODE.upper()}</b>\n"
                    f"Owner: <b>{esc(OWNER_NAME)}</b>",
                    parse_mode=ParseMode.HTML,
                ),
            )
        )

    if not query or "help" in query:
        results.append(
            InlineQueryResultArticle(
                id="help",
                title="📚 Help",
                description="Show inline help.",
                input_message_content=InputTextMessageContent(
                    "📚 <b>LUQMAN X MD</b>\n\n"
                    "Try inline keywords such as <code>owner</code>, "
                    "<code>joke</code>, <code>info</code> or <code>help</code>.",
                    parse_mode=ParseMode.HTML,
                ),
            )
        )

    if not results:
        results.append(
            InlineQueryResultArticle(
                id="empty",
                title="🔎 No result",
                description="Try: owner, joke, info, help",
                input_message_content=InputTextMessageContent(
                    "🔎 No matching result. Try <code>owner</code>, <code>joke</code>, "
                    "<code>info</code> or <code>help</code>.",
                    parse_mode=ParseMode.HTML,
                ),
            )
        )

    await update.inline_query.answer(results[:10], cache_time=2, is_personal=True)


# ============================================================
# CALLBACK MENUS
# ============================================================
async def callback_handler(update, context):
    query = update.callback_query
    await query.answer()
    data = query.data
    chat_id = query.message.chat.id

    if data == "menu:main":
        await query.edit_message_text(
            footer("🤖 <b>LUQMAN X MD</b>\n\nChoose a section below."),
            parse_mode=ParseMode.HTML,
            reply_markup=main_menu_keyboard(),
        )
        return

    if data == "menu:group":
        await query.edit_message_text(
            footer("🛡 <b>GROUP MANAGEMENT</b>\n\nChoose an action."),
            parse_mode=ParseMode.HTML,
            reply_markup=group_menu_keyboard(),
        )
        return

    if data == "menu:tools":
        await query.edit_message_text(
            footer("🧰 <b>TOOLS</b>\n\nChoose a utility."),
            parse_mode=ParseMode.HTML,
            reply_markup=tools_menu_keyboard(),
        )
        return

    if data == "menu:user":
        await query.edit_message_text(
            footer("👤 <b>USER TOOLS</b>\n\nChoose an option."),
            parse_mode=ParseMode.HTML,
            reply_markup=user_menu_keyboard(),
        )
        return

    if data == "menu:fun":
        await query.edit_message_text(
            footer("🎮 <b>FUN</b>\n\nChoose a game or joke."),
            parse_mode=ParseMode.HTML,
            reply_markup=fun_menu_keyboard(),
        )
        return

    if data == "menu:settings":
        await query.edit_message_text(
            footer("⚙️ <b>GROUP SETTINGS</b>\n\nTap a setting to toggle it."),
            parse_mode=ParseMode.HTML,
            reply_markup=settings_keyboard(chat_id),
        )
        return

    if data == "menu:rules":
        s = group_settings(chat_id)
        rules = s["rules"] or "No rules have been configured yet."
        await query.edit_message_text(
            footer(f"📜 <b>GROUP RULES</b>\n\n{esc(rules)}"),
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([[back_button()]]),
        )
        return

    if data == "menu:notes":
        notes = DATA.get("notes", {}).get(str(chat_id), {})
        names = "\n".join(f"• <code>{esc(k)}</code>" for k in sorted(notes)) or "No notes saved."
        await query.edit_message_text(
            footer(f"📝 <b>NOTES</b>\n\n{names}\n\nUse <code>/save name text</code>."),
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([[back_button()]]),
        )
        return

    if data == "menu:owner":
        await query.edit_message_text(
            footer(
                f"👑 <b>OWNER</b>\n\n"
                f"Name: <b>{esc(OWNER_NAME)}</b>\n"
                f"Telegram ID: <code>{OWNER_ID}</code>"
            ),
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([[back_button()]]),
        )
        return

    if data.startswith("toggle:"):
        key = data.split(":", 1)[1]
        if key not in ("antilink", "antisticker", "antispam", "antiflood", "welcome"):
            return
        if not is_owner_or_sudo(query.from_user.id):
            await query.answer("Owner/Sudo only.", show_alert=True)
            return
        if chat_id > 0:
            await query.answer("Use this in a group.", show_alert=True)
            return
        s = group_settings(chat_id)
        s[key] = not bool(s[key])
        save_data()
        await query.edit_message_reply_markup(reply_markup=settings_keyboard(chat_id))
        await query.answer(f"{key}: {'ON' if s[key] else 'OFF'}")
        return

    if data.startswith("setting:"):
        key = data.split(":", 1)[1]
        if key in ("antilink", "antisticker", "antispam", "antiflood", "welcome"):
            await query.edit_message_reply_markup(reply_markup=settings_keyboard(chat_id))
            return

    if data.startswith("fun:"):
        fun = data.split(":", 1)[1]
        await query.message.reply_dice(emoji={"dice": "🎲", "dart": "🎯", "football": "⚽"}[fun])
        return

    if data.startswith("help:"):
        name = data.split(":", 1)[1]
        desc = COMMAND_HELP.get(name, "Use /help to see the available commands.")
        await query.edit_message_text(
            footer(f"📘 <b>/{name}</b>\n\n{esc(desc)}"),
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([[back_button()]]),
        )


# ============================================================
# WELCOME + PROTECTION
# ============================================================
LINK_RE = re.compile(r"(https?://\S+|www\.\S+|t\.me/\S+)", re.IGNORECASE)


async def handle_messages(update, context):
    message = update.effective_message
    if not message:
        return

    chat = update.effective_chat
    user = update.effective_user

    DATA["stats"]["messages"] = DATA.get("stats", {}).get("messages", 0) + 1
    DATA["stats"]["users"] = max(DATA.get("stats", {}).get("users", 0), 1)

    if chat.type not in ("group", "supergroup"):
        return

    s = group_settings(chat.id)

    # Welcome new members
    if message.new_chat_members and s.get("welcome", True):
        for member in message.new_chat_members:
            template = s.get("welcome_text") or "Welcome {name} to {group}! 🎉"
            text = (
                template.replace("{name}", member.first_name)
                .replace("{username}", f"@{member.username}" if member.username else member.first_name)
                .replace("{group}", chat.title or "the group")
            )
            await message.reply_text(
                footer(f"👋 <b>WELCOME</b>\n\n{esc(text)}"),
                parse_mode=ParseMode.HTML,
            )
        save_data()
        return

    # Ignore administrators for automatic moderation
    try:
        sender_is_admin = await is_admin(update, context, user.id)
    except Exception:
        sender_is_admin = False

    if sender_is_admin or is_owner_or_sudo(user.id):
        save_data()
        return

    # Anti-sticker
    if s.get("antisticker") and message.sticker:
        try:
            await message.delete()
        except (BadRequest, Forbidden):
            pass
        return

    # Anti-link
    text = message.text or message.caption or ""
    if s.get("antilink") and LINK_RE.search(text):
        try:
            await message.delete()
            await context.bot.send_message(
                chat.id,
                footer("🔗 <b>Link removed.</b>\nLinks are not allowed in this group."),
                parse_mode=ParseMode.HTML,
            )
        except (BadRequest, Forbidden):
            pass
        return

    # Anti-spam: repeated identical text
    if s.get("antispam") and text:
        key = (chat.id, user.id)
        recent = FLOOD_TRACKER[chat.id][user.id]
        now = time.time()
        recent.append((now, text.strip().lower()))
        same = [t for ts, t in recent if now - ts <= 12 and t == text.strip().lower()]
        if len(same) >= 4:
            try:
                await message.delete()
            except (BadRequest, Forbidden):
                pass
            return

    # Anti-flood: too many messages quickly
    if s.get("antiflood"):
        recent = FLOOD_TRACKER[chat.id][user.id]
        now = time.time()
        recent.append((now, "__message__"))
        recent_times = [ts for ts, _ in recent if now - ts <= 8]
        if len(recent_times) >= 7:
            try:
                await message.delete()
            except (BadRequest, Forbidden):
                pass
            return

    save_data()


# ============================================================
# ERROR HANDLER
# ============================================================
async def error_handler(update, context):
    logger.error("Update error: %s", context.error)


# ============================================================
# STARTUP
# ============================================================
def register_handlers(app):
    handlers = [
        ("start", start_command),
        ("menu", menu_command),
        ("help", help_command),
        ("alive", alive_command),
        ("ping", ping_command),
        ("owner", owner_command),
        ("ownerpanel", ownerpanel_command),
        ("id", id_command),
        ("info", info_command),
        ("font", font_command),
        ("math", math_command),
        ("qr", qr_command),
        ("save", save_note_command),
        ("get", get_note_command),
        ("notes", notes_command),
        ("remind", remind_command),
        ("ban", ban_command),
        ("unban", unban_command),
        ("kick", kick_command),
        ("mute", mute_command),
        ("unmute", unmute_command),
        ("warn", warn_command),
        ("unwarn", unwarn_command),
        ("pin", pin_command),
        ("unpin", unpin_command),
        ("del", del_command),
        ("antilink", antilink_command),
        ("antisticker", antisticker_command),
        ("antispam", antispam_command),
        ("antiflood", antiflood_command),
        ("setwelcome", setwelcome_command),
        ("welcome", welcome_command),
        ("setrules", setrules_command),
        ("rules", rules_command),
        ("admins", admins_command),
        ("ginfo", ginfo_command),
        ("joke", joke_command),
        ("dice", dice_command),
        ("dart", dart_command),
        ("football", football_command),
        ("love", love_command),
    ]
    for command, callback in handlers:
        app.add_handler(CommandHandler(command, callback))

    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(InlineQueryHandler(inline_query_handler))
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, handle_messages))
    app.add_error_handler(error_handler)


def main():
    if not OWNER_ID:
        raise RuntimeError("Set OWNER_ID in the configuration before starting the bot.")

    app = (
        Application.builder()
        .token(TOKEN)
        .build()
    )

    register_handlers(app)

    logger.info("%s v%s is starting...", BOT_NAME, VERSION)
    app.run_polling(
        poll_interval=1,
        timeout=60,
        bootstrap_retries=-1,
        drop_pending_updates=True,
        allowed_updates=Update.ALL_TYPES,
    )


if __name__ == "__main__":
    main()
