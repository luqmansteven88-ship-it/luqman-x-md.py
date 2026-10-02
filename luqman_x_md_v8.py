
import json
import logging
import math
import os
import random
import re
import secrets
import string
import time
import uuid
import base64
import hashlib
import html
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote, unquote, urlparse

import qrcode
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
from telegram.error import BadRequest, Forbidden, TelegramError
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    InlineQueryHandler,
    ContextTypes,
    filters,
)

BOT_NAME = "LUQMAN X MD"
OWNER_NAME = "LUQMAN SJ"
OWNER_ID = 7847425637
OWNER_WHATSAPP = "+255678716839"

# KEEP YOUR CURRENT TOKEN HERE.
TOKEN = "8712244204:AAEvEdORCg1bx3U77CFup0nMeDJkwDjof_g"

DATA_FILE = Path("luqman_data.json")
MODE = "public"
VERSION = "8.0.0"
START_TIME = time.time()

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(BOT_NAME)

DEFAULT_GROUP = {
    "antilink": False,
    "antisticker": False,
    "antimedia": False,
    "antispam": False,
    "antiflood": False,
    "antibot": False,
    "antimention": False,
    "welcome": True,
    "goodbye": False,
    "welcome_text": "",
    "goodbye_text": "",
    "rules": "",
    "warn_limit": 3,
    "antispam_limit": 4,
    "antispam_window": 12,
    "antiflood_limit": 7,
    "antiflood_window": 8,
    "warnings": {},
    "filters": {},
    "mutes": {},
    "locked": False,
    "unlock_permissions": None,
}

DEFAULT_DATA = {
    "groups": {},
    "notes": {},
    "users": {},
    "sudo": [],
    "stats": {
        "messages": 0,
        "commands": 0,
        "moderation": 0,
        "started_at": int(time.time()),
    },
    "reminders": {},
}

def load_data():
    if not DATA_FILE.exists():
        return json.loads(json.dumps(DEFAULT_DATA))
    try:
        raw = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    except Exception:
        logger.exception("Could not read data file; using defaults.")
        return json.loads(json.dumps(DEFAULT_DATA))

    data = json.loads(json.dumps(DEFAULT_DATA))
    if isinstance(raw, dict):
        for key in ("groups", "notes", "users", "reminders"):
            if isinstance(raw.get(key), dict):
                data[key] = raw[key]
        if isinstance(raw.get("sudo"), list):
            data["sudo"] = raw["sudo"]
        if isinstance(raw.get("stats"), dict):
            data["stats"].update(raw["stats"])

    for gid, settings in list(data["groups"].items()):
        if not isinstance(settings, dict):
            data["groups"][gid] = json.loads(json.dumps(DEFAULT_GROUP))
            continue
        for key, value in DEFAULT_GROUP.items():
            if key not in settings:
                settings[key] = json.loads(json.dumps(value))
    return data

DATA = load_data()

def save_data():
    tmp = DATA_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(DATA, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(DATA_FILE)

SPAM_TRACKER = defaultdict(lambda: defaultdict(deque))
FLOOD_TRACKER = defaultdict(lambda: defaultdict(deque))
AFK_USERS = {}
MUTE_JOBS = {}

def esc(value):
    return html.escape(str(value or ""))

def uptime():
    seconds = int(time.time() - START_TIME)
    d, seconds = divmod(seconds, 86400)
    h, seconds = divmod(seconds, 3600)
    m, s = divmod(seconds, 60)
    parts = []
    if d: parts.append(f"{d}d")
    if h: parts.append(f"{h}h")
    if m: parts.append(f"{m}m")
    parts.append(f"{s}s")
    return " ".join(parts)

def footer():
    return f"\n\n<i>— {esc(BOT_NAME)} • {esc(VERSION)}</i>"

def is_group(chat):
    return bool(chat and chat.type in ("group", "supergroup"))

def group_settings(chat_id):
    gid = str(chat_id)
    if gid not in DATA["groups"] or not isinstance(DATA["groups"][gid], dict):
        DATA["groups"][gid] = json.loads(json.dumps(DEFAULT_GROUP))
    settings = DATA["groups"][gid]
    for k, v in DEFAULT_GROUP.items():
        settings.setdefault(k, json.loads(json.dumps(v)))
    return settings

def user_key(user_id):
    return str(user_id)

def remember_user(user):
    if not user:
        return
    uid = user_key(user.id)
    old = DATA["users"].get(uid, {})
    DATA["users"][uid] = {
        "name": user.full_name,
        "username": user.username or "",
        "first_seen": old.get("first_seen", int(time.time())),
        "last_seen": int(time.time()),
    }

def track_message(update):
    user = update.effective_user
    if user:
        remember_user(user)
    DATA["stats"]["messages"] = int(DATA["stats"].get("messages", 0)) + 1

def track_command(update):
    DATA["stats"]["commands"] = int(DATA["stats"].get("commands", 0)) + 1
    if update.effective_user:
        remember_user(update.effective_user)

def track_moderation():
    DATA["stats"]["moderation"] = int(DATA["stats"].get("moderation", 0)) + 1

def is_owner_or_sudo(user_id):
    return user_id == OWNER_ID or user_id in DATA.get("sudo", [])

async def get_member(context, chat_id, user_id):
    return await context.bot.get_chat_member(chat_id, user_id)

async def is_admin(context, chat_id, user_id):
    try:
        member = await get_member(context, chat_id, user_id)
        return member.status in (ChatMemberStatus.OWNER, ChatMemberStatus.ADMINISTRATOR)
    except TelegramError:
        return False

async def get_bot_member(update, context):
    return await get_member(context, update.effective_chat.id, context.bot.id)

async def bot_is_admin(update, context):
    if not is_group(update.effective_chat):
        return False
    try:
        member = await get_bot_member(update, context)
        return member.status in (ChatMemberStatus.OWNER, ChatMemberStatus.ADMINISTRATOR)
    except TelegramError:
        return False

async def caller_can_control(update, context):
    if not is_group(update.effective_chat):
        await update.effective_message.reply_text("❌ Hii command inafanya kazi ndani ya group tu.")
        return False
    if is_owner_or_sudo(update.effective_user.id):
        return True
    if not await is_admin(context, update.effective_chat.id, update.effective_user.id):
        await update.effective_message.reply_text("❌ Ni admin wa group tu ndiye anayeweza kutumia command hii.")
        return False
    if not await bot_is_admin(update, context):
        await update.effective_message.reply_text("❌ Nipe Admin kwanza ili niweze kusimamia group.")
        return False
    return True

async def require_right(update, context, right, message=None):
    if not await caller_can_control(update, context):
        return False
    if is_owner_or_sudo(update.effective_user.id):
        return True
    try:
        member = await get_bot_member(update, context)
        if member.status == ChatMemberStatus.OWNER:
            return True
        if member.status != ChatMemberStatus.ADMINISTRATOR or not getattr(member, right, False):
            await update.effective_message.reply_text(
                message or f"❌ Bot haina permission: <code>{esc(right)}</code>.",
                parse_mode=ParseMode.HTML,
            )
            return False
    except TelegramError:
        await update.effective_message.reply_text("❌ Sijaweza kuthibitisha permissions za bot.")
        return False
    return True

async def target_from_update(update, context, allow_arg=True):
    message = update.effective_message
    if message.reply_to_message and message.reply_to_message.from_user:
        return message.reply_to_message.from_user
    if allow_arg and context.args:
        raw = context.args[0].strip()
        if raw.lstrip("-").isdigit():
            try:
                return (await context.bot.get_chat_member(update.effective_chat.id, int(raw))).user
            except TelegramError:
                return None
    return None

async def protected_target(update, context, target):
    if not target:
        await update.effective_message.reply_text("❌ Reply ujumbe wa mtu au weka user ID.")
        return True
    if target.id == context.bot.id:
        await update.effective_message.reply_text("🤖 Huwezi kunisimamia mimi.")
        return True
    if target.id == OWNER_ID:
        await update.effective_message.reply_text("👑 Owner hawezi kulengwa.")
        return True
    if await is_admin(context, update.effective_chat.id, target.id):
        await update.effective_message.reply_text("🛡️ Siwezi kumfanyia moderation admin/owner wa group.")
        return True
    return False

def parse_duration(text):
    if not text:
        return None
    m = re.fullmatch(r"(\d+)\s*(s|sec|secs|m|min|mins|h|hr|hrs|d|day|days)", text.lower())
    if not m:
        return None
    n = int(m.group(1))
    unit = m.group(2)
    mult = {"s":1,"sec":1,"secs":1,"m":60,"min":60,"mins":60,"h":3600,"hr":3600,"hrs":3600,"d":86400,"day":86400,"days":86400}
    seconds = n * mult[unit]
    if seconds < 1 or seconds > 30 * 86400:
        return None
    return seconds

def mute_permissions():
    return ChatPermissions(
        can_send_messages=False,
        can_send_audios=False,
        can_send_documents=False,
        can_send_photos=False,
        can_send_videos=False,
        can_send_video_notes=False,
        can_send_voice_notes=False,
        can_send_polls=False,
        can_send_other_messages=False,
        can_add_web_page_previews=False,
        can_change_info=False,
        can_invite_users=False,
        can_pin_messages=False,
        can_manage_topics=False,
    )

def open_permissions():
    return ChatPermissions(
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
        can_change_info=False,
        can_invite_users=False,
        can_pin_messages=False,
        can_manage_topics=False,
    )

async def unmute_job(context):
    data = context.job.data
    chat_id, user_id = data["chat_id"], data["user_id"]
    try:
        await context.bot.restrict_chat_member(chat_id, user_id, permissions=open_permissions())
        settings = group_settings(chat_id)
        settings["mutes"].pop(str(user_id), None)
        MUTE_JOBS.pop((chat_id, user_id), None)
        save_data()
        await context.bot.send_message(chat_id, f"🔊 <a href=\"tg://user?id={user_id}\">Member</a> amefunguliwa.", parse_mode=ParseMode.HTML)
    except TelegramError:
        logger.exception("Auto-unmute failed")

async def restore_mutes(application):
    now = time.time()
    for gid, settings in DATA.get("groups", {}).items():
        try:
            chat_id = int(gid)
        except ValueError:
            continue
        for uid, until in list(settings.get("mutes", {}).items()):
            remaining = float(until) - now
            if remaining <= 0:
                try:
                    await application.bot.restrict_chat_member(chat_id, int(uid), permissions=open_permissions())
                except TelegramError:
                    pass
                settings["mutes"].pop(uid, None)
                continue
            job = application.job_queue.run_once(
                unmute_job,
                when=remaining,
                data={"chat_id": chat_id, "user_id": int(uid)},
                name=f"unmute:{chat_id}:{uid}",
            )
            MUTE_JOBS[(chat_id, int(uid))] = job
    save_data()

async def post_init(application):
    await restore_mutes(application)

async def start(update, context):
    track_command(update)
    user = update.effective_user
    remember_user(user)
    save_data()
    text = (
        f"╭━━━〔 🔥 <b>{esc(BOT_NAME)}</b> 〕━━━╮\n"
        f"┃ 👋 Karibu <b>{esc(user.first_name)}</b>\n"
        f"┃ ⚡ Version: <code>{esc(VERSION)}</code>\n"
        f"┃ 🌐 Mode: <code>{esc(MODE)}</code>\n"
        f"┃ 🛡️ Group protection + tools\n"
        f"╰━━━━━━━━━━━━━━━━━━━━╯\n\n"
        f"👉 Tumia /menu kuona commands zote."
        f"{footer()}"
    )
    await update.effective_message.reply_text(text, parse_mode=ParseMode.HTML)

def main_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("👥 GROUP", callback_data="menu:group"),
         InlineKeyboardButton("🛠 TOOLS", callback_data="menu:tools")],
        [InlineKeyboardButton("👤 USER", callback_data="menu:user"),
         InlineKeyboardButton("🎮 FUN", callback_data="menu:fun")],
        [InlineKeyboardButton("⚙️ SETTINGS", callback_data="menu:settings"),
         InlineKeyboardButton("👑 OWNER", callback_data="menu:owner")],
        [InlineKeyboardButton("📌 INLINE", callback_data="menu:inline")],
    ])

def group_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔨 MODERATION", callback_data="menu:mod")],
        [InlineKeyboardButton("🛡 PROTECTION", callback_data="menu:protection")],
        [InlineKeyboardButton("👋 WELCOME", callback_data="menu:welcome"),
         InlineKeyboardButton("📜 RULES", callback_data="menu:rules")],
        [InlineKeyboardButton("🔙 BACK", callback_data="menu:main")],
    ])

def tools_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔤 FONT", callback_data="menu:font"),
         InlineKeyboardButton("🧮 MATH", callback_data="menu:math")],
        [InlineKeyboardButton("📱 QR", callback_data="menu:qr"),
         InlineKeyboardButton("📝 NOTES", callback_data="menu:notes")],
        [InlineKeyboardButton("⏰ REMINDERS", callback_data="menu:reminders"),
         InlineKeyboardButton("🔐 ENCODE", callback_data="menu:encode")],
        [InlineKeyboardButton("🔙 BACK", callback_data="menu:main")],
    ])

def user_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🆔 MY ID", callback_data="cmd:id"),
         InlineKeyboardButton("👤 MY INFO", callback_data="cmd:info")],
        [InlineKeyboardButton("🟢 STATUS", callback_data="cmd:status"),
         InlineKeyboardButton("🆔 GROUP INFO", callback_data="cmd:ginfo")],
        [InlineKeyboardButton("🔙 BACK", callback_data="menu:main")],
    ])

def fun_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎲 DICE", callback_data="cmd:dice"),
         InlineKeyboardButton("⚽ FOOTBALL", callback_data="cmd:football")],
        [InlineKeyboardButton("🎯 DART", callback_data="cmd:dart"),
         InlineKeyboardButton("🪙 COIN", callback_data="cmd:coin")],
        [InlineKeyboardButton("🎰 SLOT", callback_data="cmd:slot"),
         InlineKeyboardButton("🎱 8BALL", callback_data="cmd:8ball")],
        [InlineKeyboardButton("🔙 BACK", callback_data="menu:main")],
    ])

async def menu(update, context):
    track_command(update)
    await update.effective_message.reply_text(
        f"╭━━━〔 🔥 <b>{esc(BOT_NAME)}</b> 〕━━━╮\n"
        f"┃ 👑 Owner: <b>{esc(OWNER_NAME)}</b>\n"
        f"┃ ⚡ Prefix: <code>/</code>\n"
        f"┃ 🌐 Mode: <code>{esc(MODE)}</code>\n"
        f"╰━━━━━━━━━━━━━━━━━━━━╯\n\n"
        f"Chagua category hapa chini:{footer()}",
        parse_mode=ParseMode.HTML,
        reply_markup=main_menu(),
    )

async def alive(update, context):
    track_command(update)
    await update.effective_message.reply_text(
        f"🟢 <b>{esc(BOT_NAME)}</b> ONLINE\n\n"
        f"⚡ Version: <code>{esc(VERSION)}</code>\n"
        f"🌐 Mode: <code>{esc(MODE)}</code>\n"
        f"⏱ Uptime: <code>{esc(uptime())}</code>\n"
        f"👥 Users: <code>{len(DATA['users'])}</code>\n"
        f"💬 Messages: <code>{DATA['stats'].get('messages', 0)}</code>"
        f"{footer()}",
        parse_mode=ParseMode.HTML,
    )

async def ping(update, context):
    track_command(update)
    start = time.perf_counter()
    msg = await update.effective_message.reply_text("🏓 Pinging...")
    ms = (time.perf_counter() - start) * 1000
    await msg.edit_text(
        f"🏓 <b>PONG!</b>\n⚡ Telegram: <code>{ms:.0f} ms</code>\n⏱ Uptime: <code>{esc(uptime())}</code>{footer()}",
        parse_mode=ParseMode.HTML,
    )

async def owner(update, context):
    track_command(update)
    await update.effective_message.reply_text(
        f"╭━━〔 👑 OWNER 〕━━╮\n"
        f"┃ Name: <b>{esc(OWNER_NAME)}</b>\n"
        f"┃ WhatsApp: <code>{esc(OWNER_WHATSAPP)}</code>\n"
        f"┃ ID: <code>{OWNER_ID}</code>\n"
        f"╰━━━━━━━━━━━━━━╯{footer()}",
        parse_mode=ParseMode.HTML,
    )

async def ownerpanel(update, context):
    track_command(update)
    if not is_owner_or_sudo(update.effective_user.id):
        await update.effective_message.reply_text("❌ Owner/Sudo only.")
        return
    await update.effective_message.reply_text(
        f"👑 <b>{esc(BOT_NAME)} OWNER PANEL</b>\n\n"
        f"👥 Users: <code>{len(DATA['users'])}</code>\n"
        f"👥 Groups: <code>{len(DATA['groups'])}</code>\n"
        f"💬 Messages: <code>{DATA['stats'].get('messages', 0)}</code>\n"
        f"⌨️ Commands: <code>{DATA['stats'].get('commands', 0)}</code>\n"
        f"🛡 Moderation: <code>{DATA['stats'].get('moderation', 0)}</code>\n"
        f"⏱ Uptime: <code>{esc(uptime())}</code>\n\n"
        f"Commands: /addsudo /delsudo /listsudo /botstats /groups /broadcast",
        parse_mode=ParseMode.HTML,
    )

async def idsudo(update, context):
    track_command(update)
    if not is_owner_or_sudo(update.effective_user.id):
        await update.effective_message.reply_text("❌ Owner/Sudo only.")
        return
    target = await target_from_update(update, context)
    if not target:
        await update.effective_message.reply_text("❌ Reply user au weka user ID.")
        return
    uid = target.id
    if uid not in DATA["sudo"]:
        DATA["sudo"].append(uid)
        save_data()
    await update.effective_message.reply_text(f"✅ <code>{uid}</code> ameongezwa Sudo.", parse_mode=ParseMode.HTML)

async def delsudo(update, context):
    track_command(update)
    if not is_owner_or_sudo(update.effective_user.id):
        await update.effective_message.reply_text("❌ Owner/Sudo only.")
        return
    target = await target_from_update(update, context)
    if not target:
        await update.effective_message.reply_text("❌ Reply user au weka user ID.")
        return
    if target.id in DATA["sudo"]:
        DATA["sudo"].remove(target.id)
        save_data()
    await update.effective_message.reply_text("✅ Sudo imeondolewa.")

async def listsudo(update, context):
    track_command(update)
    if not is_owner_or_sudo(update.effective_user.id):
        await update.effective_message.reply_text("❌ Owner/Sudo only.")
        return
    if not DATA["sudo"]:
        await update.effective_message.reply_text("📋 Hakuna Sudo.")
        return
    await update.effective_message.reply_text(
        "📋 <b>SUDO USERS</b>\n\n" + "\n".join(f"• <code>{x}</code>" for x in DATA["sudo"]),
        parse_mode=ParseMode.HTML,
    )

async def botstats(update, context):
    track_command(update)
    if not is_owner_or_sudo(update.effective_user.id):
        await update.effective_message.reply_text("❌ Owner/Sudo only.")
        return
    s = DATA["stats"]
    await update.effective_message.reply_text(
        f"📊 <b>BOT STATS</b>\n\n"
        f"👥 Users: <code>{len(DATA['users'])}</code>\n"
        f"👥 Groups: <code>{len(DATA['groups'])}</code>\n"
        f"💬 Messages: <code>{s.get('messages', 0)}</code>\n"
        f"⌨️ Commands: <code>{s.get('commands', 0)}</code>\n"
        f"🛡 Moderation: <code>{s.get('moderation', 0)}</code>\n"
        f"⏱ Uptime: <code>{esc(uptime())}</code>",
        parse_mode=ParseMode.HTML,
    )

async def groups_cmd(update, context):
    track_command(update)
    if not is_owner_or_sudo(update.effective_user.id):
        await update.effective_message.reply_text("❌ Owner/Sudo only.")
        return
    if not DATA["groups"]:
        await update.effective_message.reply_text("📋 Bado hakuna group lililorekodiwa.")
        return
    lines = []
    for gid, settings in DATA["groups"].items():
        lines.append(f"• <code>{esc(gid)}</code> | welcome={settings.get('welcome')} | antilink={settings.get('antilink')}")
    await update.effective_message.reply_text("👥 <b>TRACKED GROUPS</b>\n\n" + "\n".join(lines[:100]), parse_mode=ParseMode.HTML)

async def broadcast(update, context):
    track_command(update)
    if not is_owner_or_sudo(update.effective_user.id):
        await update.effective_message.reply_text("❌ Owner/Sudo only.")
        return
    text = update.effective_message.text.partition(" ")[2].strip()
    if not text:
        if update.effective_message.reply_to_message and update.effective_message.reply_to_message.text:
            text = update.effective_message.reply_to_message.text
        else:
            await update.effective_message.reply_text("❌ Tumia /broadcast ujumbe")
            return
    sent = failed = 0
    for gid in list(DATA["groups"]):
        try:
            await context.bot.send_message(int(gid), f"📢 <b>ANNOUNCEMENT</b>\n\n{esc(text)}", parse_mode=ParseMode.HTML)
            sent += 1
        except TelegramError:
            failed += 1
    await update.effective_message.reply_text(f"📢 Sent: <code>{sent}</code> | Failed: <code>{failed}</code>", parse_mode=ParseMode.HTML)

async def id_cmd(update, context):
    track_command(update)
    u = update.effective_user
    username = f"@{esc(u.username)}" if u.username else "-"
    await update.effective_message.reply_text(
        f"🆔 <b>USER ID</b>\\n\\n"
        f"Name: {esc(u.full_name)}\\n"
        f"ID: <code>{u.id}</code>\\n"
        f"Username: <code>{username}</code>",
        parse_mode=ParseMode.HTML,
    )

async def info_cmd(update, context):
    track_command(update)
    target = await target_from_update(update, context, allow_arg=False) or update.effective_user
    username = f"@{esc(target.username)}" if target.username else "-"
    await update.effective_message.reply_text(
        f"👤 <b>USER INFO</b>\\n\\n"
        f"Name: {esc(target.full_name)}\\n"
        f"ID: <code>{target.id}</code>\\n"
        f"Username: <code>{username}</code>",
        parse_mode=ParseMode.HTML,
    )

async def status_cmd(update, context):
    track_command(update)
    u = update.effective_user
    if is_group(update.effective_chat):
        member = await get_member(context, update.effective_chat.id, u.id)
        status = member.status
    else:
        status = "private"
    await update.effective_message.reply_text(
        f"🟢 <b>STATUS</b>\n\n👤 User: <code>{esc(status)}</code>\n🌐 Mode: <code>{esc(MODE)}</code>",
        parse_mode=ParseMode.HTML,
    )

async def ginfo(update, context):
    track_command(update)
    if not is_group(update.effective_chat):
        await update.effective_message.reply_text("❌ Group only.")
        return
    chat = await context.bot.get_chat(update.effective_chat.id)
    count = await context.bot.get_chat_member_count(chat.id)
    s = group_settings(chat.id)
    await update.effective_message.reply_text(
        f"🏠 <b>GROUP INFO</b>\n\n"
        f"Name: <b>{esc(chat.title)}</b>\n"
        f"ID: <code>{chat.id}</code>\n"
        f"Members: <code>{count}</code>\n"
        f"🔗 Anti-link: <code>{s['antilink']}</code>\n"
        f"🚦 Anti-flood: <code>{s['antiflood']}</code>\n"
        f"🚫 Anti-spam: <code>{s['antispam']}</code>\n"
        f"🎞 Anti-media: <code>{s['antimedia']}</code>\n"
        f"👋 Welcome: <code>{s['welcome']}</code>",
        parse_mode=ParseMode.HTML,
    )

async def admins(update, context):
    track_command(update)
    if not is_group(update.effective_chat):
        await update.effective_message.reply_text("❌ Group only.")
        return
    admins_list = await context.bot.get_chat_administrators(update.effective_chat.id)
    lines = ["👑 <b>GROUP ADMINS</b>", ""]
    for a in admins_list:
        label = esc(a.user.full_name)
        if a.user.username:
            label += f" (@{esc(a.user.username)})"
        lines.append(f"• {label} — <code>{a.user.id}</code>")
    await update.effective_message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)

async def set_toggle(update, context, key, label):
    if not await caller_can_control(update, context):
        return
    if not context.args or context.args[0].lower() not in ("on", "off"):
        await update.effective_message.reply_text(f"⚙️ Tumia <code>/{key} on</code> au <code>/{key} off</code>.", parse_mode=ParseMode.HTML)
        return
    value = context.args[0].lower() == "on"
    group_settings(update.effective_chat.id)[key] = value
    save_data()
    await update.effective_message.reply_text(f"✅ {label}: <b>{'ON' if value else 'OFF'}</b>", parse_mode=ParseMode.HTML)

async def antilink(update, context): track_command(update); await set_toggle(update, context, "antilink", "Anti-link")
async def antisticker(update, context): track_command(update); await set_toggle(update, context, "antisticker", "Anti-sticker")
async def antimedia(update, context): track_command(update); await set_toggle(update, context, "antimedia", "Anti-media")
async def antispam(update, context): track_command(update); await set_toggle(update, context, "antispam", "Anti-spam")
async def antiflood(update, context): track_command(update); await set_toggle(update, context, "antiflood", "Anti-flood")
async def antibot(update, context): track_command(update); await set_toggle(update, context, "antibot", "Anti-bot")
async def antimention(update, context): track_command(update); await set_toggle(update, context, "antimention", "Anti-group mention")

async def welcome_cmd(update, context):
    track_command(update)
    if not await caller_can_control(update, context):
        return
    s = group_settings(update.effective_chat.id)
    if not context.args:
        await update.effective_message.reply_text(
            f"👋 Welcome: <b>{'ON' if s['welcome'] else 'OFF'}</b>\n"
            f"📝 Text: <code>{esc(s['welcome_text'] or '{name}, karibu {group}!')}</code>",
            parse_mode=ParseMode.HTML,
        )
        return
    await set_toggle(update, context, "welcome", "Welcome")

async def goodbye_cmd(update, context):
    track_command(update)
    if not await caller_can_control(update, context):
        return
    s = group_settings(update.effective_chat.id)
    if not context.args:
        await update.effective_message.reply_text(
            f"👋 Goodbye: <b>{'ON' if s['goodbye'] else 'OFF'}</b>\n"
            f"📝 Text: <code>{esc(s['goodbye_text'] or '{name} ameondoka {group}.')}</code>",
            parse_mode=ParseMode.HTML,
        )
        return
    await set_toggle(update, context, "goodbye", "Goodbye")

def render_template(template, user, chat, count=None):
    text = template or "{name}, karibu {group}! 👋"
    values = {
        "name": user.full_name,
        "username": f"@{user.username}" if user.username else "",
        "group": chat.title or "",
        "id": user.id,
        "count": count if count is not None else "",
    }
    for key, value in values.items():
        text = text.replace("{" + key + "}", str(value))
    return text

async def setwelcome(update, context):
    track_command(update)
    if not await caller_can_control(update, context):
        return
    text = update.effective_message.text.partition(" ")[2].strip()
    if not text:
        await update.effective_message.reply_text("❌ Mfano: /setwelcome Karibu {name} kwenye {group} 👋")
        return
    group_settings(update.effective_chat.id)["welcome_text"] = text
    save_data()
    await update.effective_message.reply_text("✅ Welcome message imehifadhiwa.")

async def setgoodbye(update, context):
    track_command(update)
    if not await caller_can_control(update, context):
        return
    text = update.effective_message.text.partition(" ")[2].strip()
    if not text:
        await update.effective_message.reply_text("❌ Mfano: /setgoodbye Tutaonana {name}.")
        return
    group_settings(update.effective_chat.id)["goodbye_text"] = text
    save_data()
    await update.effective_message.reply_text("✅ Goodbye message imehifadhiwa.")

async def setrules(update, context):
    track_command(update)
    if not await caller_can_control(update, context):
        return
    text = update.effective_message.text.partition(" ")[2].strip()
    if not text:
        await update.effective_message.reply_text("❌ Mfano: /setrules Heshimu kila mtu.")
        return
    group_settings(update.effective_chat.id)["rules"] = text
    save_data()
    await update.effective_message.reply_text("✅ Rules zimehifadhiwa.")

async def rules(update, context):
    track_command(update)
    if not is_group(update.effective_chat):
        await update.effective_message.reply_text("❌ Group only.")
        return
    text = group_settings(update.effective_chat.id).get("rules") or "📜 Hakuna rules zilizowekwa."
    await update.effective_message.reply_text(f"📜 <b>GROUP RULES</b>\n\n{esc(text)}", parse_mode=ParseMode.HTML)

async def clearrules(update, context):
    track_command(update)
    if not await caller_can_control(update, context):
        return
    group_settings(update.effective_chat.id)["rules"] = ""
    save_data()
    await update.effective_message.reply_text("🗑 Rules zimefutwa.")

async def warn(update, context):
    track_command(update)
    if not await require_right(update, context, "can_restrict_members"):
        return
    target = await target_from_update(update, context)
    if await protected_target(update, context, target):
        return
    s = group_settings(update.effective_chat.id)
    uid = str(target.id)
    current = int(s["warnings"].get(uid, 0)) + 1
    s["warnings"][uid] = current
    limit = int(s.get("warn_limit", 3))
    track_moderation()
    if current >= limit:
        try:
            await context.bot.ban_chat_member(update.effective_chat.id, target.id)
            s["warnings"].pop(uid, None)
            action = f"🚫 {esc(target.full_name)} ameban baada ya warnings {current}/{limit}."
        except TelegramError as e:
            action = f"⚠️ Warning {current}/{limit}, lakini ban imeshindikana: {esc(e)}"
    else:
        action = f"⚠️ {esc(target.full_name)} warning <b>{current}/{limit}</b>."
    save_data()
    await update.effective_message.reply_text(action, parse_mode=ParseMode.HTML)

async def warnings(update, context):
    track_command(update)
    if not is_group(update.effective_chat):
        return
    target = await target_from_update(update, context, allow_arg=False) or update.effective_user
    s = group_settings(update.effective_chat.id)
    count = int(s["warnings"].get(str(target.id), 0))
    await update.effective_message.reply_text(
        f"⚠️ <b>WARNINGS</b>\n{esc(target.full_name)}: <code>{count}/{s.get('warn_limit',3)}</code>",
        parse_mode=ParseMode.HTML,
    )

async def unwarn(update, context):
    track_command(update)
    if not await require_right(update, context, "can_restrict_members"):
        return
    target = await target_from_update(update, context)
    if await protected_target(update, context, target):
        return
    s = group_settings(update.effective_chat.id)
    uid = str(target.id)
    count = max(0, int(s["warnings"].get(uid, 0)) - 1)
    if count:
        s["warnings"][uid] = count
    else:
        s["warnings"].pop(uid, None)
    save_data()
    await update.effective_message.reply_text(f"✅ {esc(target.full_name)} warnings: <code>{count}</code>", parse_mode=ParseMode.HTML)

async def resetwarn(update, context):
    track_command(update)
    if not await require_right(update, context, "can_restrict_members"):
        return
    target = await target_from_update(update, context)
    if await protected_target(update, context, target):
        return
    group_settings(update.effective_chat.id)["warnings"].pop(str(target.id), None)
    save_data()
    await update.effective_message.reply_text("✅ Warnings reset.")

async def ban(update, context):
    track_command(update)
    if not await require_right(update, context, "can_restrict_members"):
        return
    target = await target_from_update(update, context)
    if await protected_target(update, context, target):
        return
    try:
        await context.bot.ban_chat_member(update.effective_chat.id, target.id)
        track_moderation()
        await update.effective_message.reply_text(f"🚫 <b>{esc(target.full_name)}</b> ameban.", parse_mode=ParseMode.HTML)
    except TelegramError as e:
        await update.effective_message.reply_text(f"❌ Ban imeshindikana: {esc(e)}", parse_mode=ParseMode.HTML)

async def unban(update, context):
    track_command(update)
    if not await require_right(update, context, "can_restrict_members"):
        return
    target = await target_from_update(update, context)
    if not target and context.args and context.args[0].lstrip("-").isdigit():
        target_id = int(context.args[0])
    elif target:
        target_id = target.id
    else:
        await update.effective_message.reply_text("❌ Reply user au weka ID.")
        return
    try:
        await context.bot.unban_chat_member(update.effective_chat.id, target_id, only_if_banned=True)
        track_moderation()
        await update.effective_message.reply_text("✅ User ame-unban.")
    except TelegramError as e:
        await update.effective_message.reply_text(f"❌ Unban imeshindikana: {esc(e)}", parse_mode=ParseMode.HTML)

async def softban(update, context):
    track_command(update)
    if not await require_right(update, context, "can_restrict_members"):
        return
    target = await target_from_update(update, context)
    if await protected_target(update, context, target):
        return
    try:
        await context.bot.ban_chat_member(update.effective_chat.id, target.id)
        await context.bot.unban_chat_member(update.effective_chat.id, target.id)
        track_moderation()
        await update.effective_message.reply_text(f"♻️ <b>{esc(target.full_name)}</b> ame-softban.", parse_mode=ParseMode.HTML)
    except TelegramError as e:
        await update.effective_message.reply_text(f"❌ Softban imeshindikana: {esc(e)}", parse_mode=ParseMode.HTML)

async def mute(update, context):
    track_command(update)
    if not await require_right(update, context, "can_restrict_members"):
        return
    target = await target_from_update(update, context)
    if await protected_target(update, context, target):
        return
    seconds = parse_duration(context.args[0]) if context.args else None
    try:
        if seconds:
            until = time.time() + seconds
            await context.bot.restrict_chat_member(
                update.effective_chat.id,
                target.id,
                permissions=mute_permissions(),
                until_date=datetime.now(timezone.utc) + timedelta(seconds=seconds),
            )
            s = group_settings(update.effective_chat.id)
            s["mutes"][str(target.id)] = until
            old = MUTE_JOBS.pop((update.effective_chat.id, target.id), None)
            if old:
                old.schedule_removal()
            job = context.job_queue.run_once(
                unmute_job,
                when=seconds,
                data={"chat_id": update.effective_chat.id, "user_id": target.id},
                name=f"unmute:{update.effective_chat.id}:{target.id}",
            )
            MUTE_JOBS[(update.effective_chat.id, target.id)] = job
            msg = f"🔇 <b>{esc(target.full_name)}</b> amemutwa kwa <code>{esc(context.args[0])}</code>."
        else:
            await context.bot.restrict_chat_member(
                update.effective_chat.id,
                target.id,
                permissions=mute_permissions(),
            )
            group_settings(update.effective_chat.id)["mutes"].pop(str(target.id), None)
            msg = f"🔇 <b>{esc(target.full_name)}</b> amemutwa."
        track_moderation()
        save_data()
        await update.effective_message.reply_text(msg, parse_mode=ParseMode.HTML)
    except TelegramError as e:
        await update.effective_message.reply_text(f"❌ Mute imeshindikana: {esc(e)}", parse_mode=ParseMode.HTML)

async def unmute(update, context):
    track_command(update)
    if not await require_right(update, context, "can_restrict_members"):
        return
    target = await target_from_update(update, context)
    if not target:
        await update.effective_message.reply_text("❌ Reply user.")
        return
    try:
        await context.bot.restrict_chat_member(update.effective_chat.id, target.id, permissions=open_permissions())
        group_settings(update.effective_chat.id)["mutes"].pop(str(target.id), None)
        job = MUTE_JOBS.pop((update.effective_chat.id, target.id), None)
        if job:
            job.schedule_removal()
        track_moderation()
        save_data()
        await update.effective_message.reply_text(f"🔊 <b>{esc(target.full_name)}</b> amefunguliwa.", parse_mode=ParseMode.HTML)
    except TelegramError as e:
        await update.effective_message.reply_text(f"❌ Unmute imeshindikana: {esc(e)}", parse_mode=ParseMode.HTML)

async def kick(update, context):
    track_command(update)
    if not await require_right(update, context, "can_restrict_members"):
        return
    target = await target_from_update(update, context)
    if await protected_target(update, context, target):
        return
    try:
        await context.bot.ban_chat_member(update.effective_chat.id, target.id)
        await context.bot.unban_chat_member(update.effective_chat.id, target.id)
        track_moderation()
        await update.effective_message.reply_text(f"👢 <b>{esc(target.full_name)}</b> amekickiwa.", parse_mode=ParseMode.HTML)
    except TelegramError as e:
        await update.effective_message.reply_text(f"❌ Kick imeshindikana: {esc(e)}", parse_mode=ParseMode.HTML)

async def promote(update, context):
    track_command(update)
    if not await require_right(update, context, "can_promote_members"):
        return
    target = await target_from_update(update, context)
    if not target:
        await update.effective_message.reply_text("❌ Reply user unayetaka kumpa admin.")
        return
    if target.id in (OWNER_ID, context.bot.id) or await is_admin(context, update.effective_chat.id, target.id):
        await update.effective_message.reply_text("⚠️ User tayari ni admin/owner au ni bot.")
        return
    try:
        await context.bot.promote_chat_member(
            update.effective_chat.id,
            target.id,
            can_change_info=False,
            can_delete_messages=True,
            can_invite_users=True,
            can_restrict_members=True,
            can_pin_messages=True,
            can_manage_topics=True,
            can_manage_video_chats=True,
            can_promote_members=False,
        )
        track_moderation()
        await update.effective_message.reply_text(f"👑 <b>{esc(target.full_name)}</b> sasa ni admin.", parse_mode=ParseMode.HTML)
    except TelegramError as e:
        await update.effective_message.reply_text(f"❌ Promote imeshindikana: {esc(e)}", parse_mode=ParseMode.HTML)

async def demote(update, context):
    track_command(update)
    if not await require_right(update, context, "can_promote_members"):
        return
    target = await target_from_update(update, context)
    if not target or target.id == OWNER_ID:
        await update.effective_message.reply_text("❌ Reply admin unayetaka kum-demote.")
        return
    try:
        await context.bot.promote_chat_member(
            update.effective_chat.id,
            target.id,
            is_anonymous=False,
            can_change_info=False,
            can_post_messages=False,
            can_edit_messages=False,
            can_delete_messages=False,
            can_invite_users=False,
            can_restrict_members=False,
            can_pin_messages=False,
            can_promote_members=False,
            can_manage_chat=False,
            can_manage_video_chats=False,
            can_manage_topics=False,
)
        track_moderation()
        await update.effective_message.reply_text(f"⬇️ <b>{esc(target.full_name)}</b> amedemote.", parse_mode=ParseMode.HTML)
    except TelegramError as e:
        await update.effective_message.reply_text(f"❌ Demote imeshindikana: {esc(e)}", parse_mode=ParseMode.HTML)

async def pin(update, context):
    track_command(update)
    if not await require_right(update, context, "can_pin_messages"):
        return
    if not update.effective_message.reply_to_message:
        await update.effective_message.reply_text("❌ Reply ujumbe unaotaka ku-pin.")
        return
    try:
        await update.effective_message.reply_to_message.pin(disable_notification=True)
        track_moderation()
        await update.effective_message.reply_text("📌 Pinned.")
    except TelegramError as e:
        await update.effective_message.reply_text(f"❌ Pin imeshindikana: {esc(e)}", parse_mode=ParseMode.HTML)

async def unpin(update, context):
    track_command(update)
    if not await require_right(update, context, "can_pin_messages"):
        return
    try:
        await context.bot.unpin_chat_message(update.effective_chat.id)
        track_moderation()
        await update.effective_message.reply_text("📌 Unpinned.")
    except TelegramError as e:
        await update.effective_message.reply_text(f"❌ Unpin imeshindikana: {esc(e)}", parse_mode=ParseMode.HTML)

async def delete_cmd(update, context):
    track_command(update)
    if not await require_right(update, context, "can_delete_messages"):
        return
    if not update.effective_message.reply_to_message:
        await update.effective_message.reply_text("❌ Reply ujumbe unaotaka kufuta.")
        return
    try:
        await update.effective_message.reply_to_message.delete()
        await update.effective_message.delete()
        track_moderation()
    except TelegramError:
        pass

async def purge(update, context):
    track_command(update)
    if not await require_right(update, context, "can_delete_messages"):
        return
    n = 10
    if context.args and context.args[0].isdigit():
        n = max(1, min(int(context.args[0]), 100))
    msg_id = update.effective_message.message_id
    deleted = 0
    for mid in range(msg_id, max(0, msg_id - n - 1), -1):
        try:
            await context.bot.delete_message(update.effective_chat.id, mid)
            deleted += 1
        except TelegramError:
            pass
    if deleted:
        await context.bot.send_message(update.effective_chat.id, f"🧹 Deleted <code>{deleted}</code> messages.", parse_mode=ParseMode.HTML)

async def lock(update, context):
    track_command(update)
    if not await require_right(update, context, "can_restrict_members"):
        return
    chat = await context.bot.get_chat(update.effective_chat.id)
    s = group_settings(chat.id)
    if not s["locked"]:
        p = chat.permissions
        if p:
            s["unlock_permissions"] = p.to_dict()
        s["locked"] = True
        await context.bot.set_chat_permissions(chat.id, ChatPermissions(can_send_messages=False))
        save_data()
    await update.effective_message.reply_text("🔒 Group imefungwa kwa members.")

async def unlock(update, context):
    track_command(update)
    if not await require_right(update, context, "can_restrict_members"):
        return
    chat = await context.bot.get_chat(update.effective_chat.id)
    s = group_settings(chat.id)
    stored = s.get("unlock_permissions")
    if stored:
        try:
            permissions = ChatPermissions.de_json(stored, context.bot)
        except Exception:
            permissions = open_permissions()
    else:
        permissions = open_permissions()
    await context.bot.set_chat_permissions(chat.id, permissions)
    s["locked"] = False
    save_data()
    await update.effective_message.reply_text("🔓 Group imefunguliwa.")

async def setwarnlimit(update, context):
    track_command(update)
    if not await caller_can_control(update, context):
        return
    if not context.args or not context.args[0].isdigit():
        await update.effective_message.reply_text("❌ Mfano: /setwarnlimit 3")
        return
    n = max(1, min(int(context.args[0]), 20))
    group_settings(update.effective_chat.id)["warn_limit"] = n
    save_data()
    await update.effective_message.reply_text(f"✅ Warn limit = <code>{n}</code>", parse_mode=ParseMode.HTML)

async def setflood(update, context):
    track_command(update)
    if not await caller_can_control(update, context):
        return
    if len(context.args) != 2 or not all(x.isdigit() for x in context.args):
        await update.effective_message.reply_text("❌ Mfano: /setflood 7 8  → messages/seconds")
        return
    n, sec = max(2, min(int(context.args[0]), 30)), max(2, min(int(context.args[1]), 60))
    s = group_settings(update.effective_chat.id)
    s["antiflood_limit"], s["antiflood_window"] = n, sec
    save_data()
    await update.effective_message.reply_text(f"✅ Anti-flood = <code>{n}</code> msgs / <code>{sec}</code>s", parse_mode=ParseMode.HTML)

async def setspam(update, context):
    track_command(update)
    if not await caller_can_control(update, context):
        return
    if len(context.args) != 2 or not all(x.isdigit() for x in context.args):
        await update.effective_message.reply_text("❌ Mfano: /setspam 4 12  → messages/seconds")
        return
    n, sec = max(2, min(int(context.args[0]), 30)), max(2, min(int(context.args[1]), 60))
    s = group_settings(update.effective_chat.id)
    s["antispam_limit"], s["antispam_window"] = n, sec
    save_data()
    await update.effective_message.reply_text(f"✅ Anti-spam = <code>{n}</code> msgs / <code>{sec}</code>s", parse_mode=ParseMode.HTML)

async def math_cmd(update, context):
    track_command(update)
    expr = update.effective_message.text.partition(" ")[2].strip()
    if not expr:
        await update.effective_message.reply_text("🧮 Mfano: /math 2^10 au /math sqrt(144) au /math 25% of 800")
        return
    expr = expr.replace("^", "**")
    m = re.fullmatch(r"\s*([0-9.]+)\s*%\s+of\s+([0-9.]+)\s*", expr, re.I)
    try:
        if m:
            result = float(m.group(1)) / 100 * float(m.group(2))
        else:
            expr = re.sub(r"\bsqrt\s*\(", "math.sqrt(", expr, flags=re.I)
            expr = re.sub(r"\bpi\b", "math.pi", expr, flags=re.I)
            if not re.fullmatch(r"[0-9+\-*/%().,\s*a-zA-Z_]+", expr):
                raise ValueError("bad chars")
            if re.search(r"__|import|exec|eval|open|globals|locals|lambda", expr, re.I):
                raise ValueError("blocked")
            result = eval(expr, {"__builtins__": {}, "math": math}, {"math": math})
        if isinstance(result, float) and result.is_integer():
            result = int(result)
        await update.effective_message.reply_text(f"🧮 <b>Result:</b> <code>{esc(result)}</code>", parse_mode=ParseMode.HTML)
    except Exception:
        await update.effective_message.reply_text("❌ Hesabu haijatambulika. Tumia mfano kama <code>25% of 800</code>, <code>2^10</code>, <code>sqrt(144)</code>.", parse_mode=ParseMode.HTML)

# Font maps: common Unicode styles
FONT_MAPS = {
    "bold": (str.maketrans("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz",
                           "𝐀𝐁𝐂𝐃𝐄𝐅𝐆𝐇𝐈𝐉𝐊𝐋𝐌𝐍𝐎𝐏𝐐𝐑𝐒𝐓𝐔𝐕𝐖𝐗𝐘𝐙𝐚𝐛𝐜𝐝𝐞𝐟𝐠𝐡𝐢𝐣𝐤𝐥𝐦𝐧𝐨𝐩𝐪𝐫𝐬𝐭𝐮𝐯𝐰𝐱𝐲𝐳")),
    "italic": (str.maketrans("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz",
                             "𝘈𝘉𝘊𝘋𝘌𝘍𝘎𝘏𝘐𝘑𝘒𝘓𝘔𝘕𝘖𝘗𝘘𝘙𝘚𝘛𝘜𝘝𝘞𝘟𝘠𝘡𝘢𝘣𝘤𝘥𝘦𝘧𝘨𝘩𝘪𝘫𝘬𝘭𝘮𝘯𝘰𝘱𝘲𝘳𝘴𝘵𝘶𝘷𝘸𝘹𝘺𝘻")),
    "mono": (str.maketrans("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789",
                           "𝙰𝙱𝙲𝙳𝙴𝙵𝙶𝙷𝙸𝙹𝙺𝙻𝙼𝙽𝙾𝙿𝚀𝚁𝚂𝚃𝚄𝚅𝚆𝚇𝚈𝚉𝚊𝚋𝚌𝚍𝚎𝚏𝚐𝚑𝚒𝚓𝚔𝚕𝚖𝚗𝚘𝚙𝚚𝚛𝚜𝚝𝚞𝚟𝚠𝚡𝚢𝚣𝟶𝟷𝟸𝟹𝟺𝟻𝟼𝟽𝟾𝟿")),
    "full": (str.maketrans("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789",
                           "ＡＢＣＤＥＦＧＨＩＪＫＬＭＮＯＰＱＲＳＴＵＶＷＸＹＺａｂｃｄｅｆｇｈｉｊｋｌｍｎｏｐｑｒｓｔｕｖｗｘｙｚ０１２３４５６７８９")),
}

async def font_cmd(update, context):
    track_command(update)
    parts = update.effective_message.text.split(maxsplit=2)
    if len(parts) < 3 or parts[1].lower() not in FONT_MAPS:
        await update.effective_message.reply_text("🔤 Tumia: /font bold Hello | /font italic Hello | /font mono Hello | /font full Hello")
        return
    style, text = parts[1].lower(), parts[2]
    await update.effective_message.reply_text(text.translate(FONT_MAPS[style]))

async def qr_cmd(update, context):
    track_command(update)
    text = update.effective_message.text.partition(" ")[2].strip()
    if not text:
        await update.effective_message.reply_text("📱 Tumia /qr https://example.com")
        return
    path = Path(f"qr_{update.effective_user.id}_{int(time.time()*1000)}.png")
    try:
        qrcode.make(text).save(path)
        with path.open("rb") as f:
            await update.effective_message.reply_photo(f, caption="📱 QR generated by LUQMAN X MD")
    finally:
        try: path.unlink()
        except OSError: pass

def note_bucket(chat_id):
    key = str(chat_id)
    DATA["notes"].setdefault(key, {})
    return DATA["notes"][key]

async def save_note(update, context):
    track_command(update)
    parts = update.effective_message.text.split(maxsplit=2)
    if len(parts) < 3:
        await update.effective_message.reply_text("📝 Tumia /save jina ujumbe")
        return
    note_bucket(update.effective_chat.id)[parts[1].lower()] = parts[2]
    save_data()
    await update.effective_message.reply_text(f"✅ Note <code>{esc(parts[1])}</code> imehifadhiwa.", parse_mode=ParseMode.HTML)

async def get_note(update, context):
    track_command(update)
    if not context.args:
        await update.effective_message.reply_text("📝 Tumia /get jina")
        return
    note = note_bucket(update.effective_chat.id).get(context.args[0].lower())
    if not note:
        await update.effective_message.reply_text("❌ Note haipo.")
        return
    await update.effective_message.reply_text(note)

async def notes(update, context):
    track_command(update)
    bucket = note_bucket(update.effective_chat.id)
    if not bucket:
        await update.effective_message.reply_text("📝 Hakuna notes.")
        return
    await update.effective_message.reply_text("📝 <b>NOTES</b>\n\n" + "\n".join(f"• <code>{esc(k)}</code>" for k in bucket), parse_mode=ParseMode.HTML)

async def delnote(update, context):
    track_command(update)
    if not context.args:
        await update.effective_message.reply_text("❌ /delnote jina")
        return
    bucket = note_bucket(update.effective_chat.id)
    bucket.pop(context.args[0].lower(), None)
    save_data()
    await update.effective_message.reply_text("🗑 Note imefutwa.")

async def clearnotes(update, context):
    track_command(update)
    note_bucket(update.effective_chat.id).clear()
    save_data()
    await update.effective_message.reply_text("🗑 Notes zote zimefutwa.")

async def reminder_job(context):
    d = context.job.data
    rid = d["id"]
    try:
        await context.bot.send_message(d["chat_id"], f"⏰ <b>REMINDER</b>\n\n{esc(d['text'])}", parse_mode=ParseMode.HTML)
    finally:
        DATA["reminders"].pop(rid, None)
        save_data()

async def remind(update, context):
    track_command(update)
    parts = update.effective_message.text.split(maxsplit=2)
    if len(parts) < 3:
        await update.effective_message.reply_text("⏰ Tumia /remind 10m Soma")
        return
    seconds = parse_duration(parts[1])
    if not seconds:
        await update.effective_message.reply_text("❌ Duration: 10s, 10m, 2h, 1d.")
        return
    rid = uuid.uuid4().hex[:8]
    DATA["reminders"][rid] = {
        "chat_id": update.effective_chat.id,
        "user_id": update.effective_user.id,
        "text": parts[2],
        "due": time.time() + seconds,
    }
    context.job_queue.run_once(reminder_job, when=seconds, data=DATA["reminders"][rid], name=f"reminder:{rid}")
    save_data()
    await update.effective_message.reply_text(f"⏰ Reminder <code>{rid}</code> imewekwa.", parse_mode=ParseMode.HTML)

async def reminders(update, context):
    track_command(update)
    rows = []
    for rid, d in DATA["reminders"].items():
        if d["chat_id"] == update.effective_chat.id and d["user_id"] == update.effective_user.id:
            remaining = max(0, int(d["due"] - time.time()))
            rows.append(f"• <code>{rid}</code> — {remaining}s — {esc(d['text'])}")
    await update.effective_message.reply_text("⏰ <b>REMINDERS</b>\n\n" + ("\n".join(rows) if rows else "Hakuna reminders."), parse_mode=ParseMode.HTML)

async def delreminder(update, context):
    track_command(update)
    if not context.args:
        await update.effective_message.reply_text("❌ /delreminder ID")
        return
    rid = context.args[0]
    d = DATA["reminders"].get(rid)
    if not d or d["chat_id"] != update.effective_chat.id or d["user_id"] != update.effective_user.id:
        await update.effective_message.reply_text("❌ Reminder haipo.")
        return
    DATA["reminders"].pop(rid, None)
    for job in context.job_queue.get_jobs_by_name(f"reminder:{rid}"):
        job.schedule_removal()
    save_data()
    await update.effective_message.reply_text("🗑 Reminder imefutwa.")

async def encode_cmd(update, context):
    track_command(update)
    parts = update.effective_message.text.split(maxsplit=1)
    if len(parts) < 2:
        await update.effective_message.reply_text("🔐 /base64 text | /decode64 text | /hash text")
        return
    cmd, text = parts[0].lower().lstrip("/"), parts[1]
    if cmd == "base64":
        out = base64.b64encode(text.encode()).decode()
    elif cmd == "decode64":
        try: out = base64.b64decode(text).decode()
        except Exception: out = "❌ Invalid Base64"
    elif cmd == "hash":
        out = hashlib.sha256(text.encode()).hexdigest()
    else:
        out = text
    await update.effective_message.reply_text(f"<code>{esc(out)}</code>", parse_mode=ParseMode.HTML)

async def uuid_cmd(update, context):
    track_command(update)
    await update.effective_message.reply_text(f"🆔 <code>{uuid.uuid4()}</code>", parse_mode=ParseMode.HTML)

async def password_cmd(update, context):
    track_command(update)
    n = 16
    if context.args and context.args[0].isdigit():
        n = max(8, min(int(context.args[0]), 64))
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*_-"
    pwd = "".join(secrets.choice(alphabet) for _ in range(n))
    await update.effective_message.reply_text(f"🔐 <code>{esc(pwd)}</code>", parse_mode=ParseMode.HTML)

async def random_cmd(update, context):
    track_command(update)
    if len(context.args) != 2 or not all(x.lstrip("-").isdigit() for x in context.args):
        await update.effective_message.reply_text("🎲 /random 1 100")
        return
    a, b = map(int, context.args)
    if a > b: a, b = b, a
    await update.effective_message.reply_text(f"🎲 <code>{random.randint(a,b)}</code>", parse_mode=ParseMode.HTML)

async def choose_cmd(update, context):
    track_command(update)
    text = update.effective_message.text.partition(" ")[2]
    options = [x.strip() for x in text.split("|") if x.strip()]
    if len(options) < 2:
        await update.effective_message.reply_text("🎯 /choose pizza | chips | rice")
        return
    await update.effective_message.reply_text("🎯 " + random.choice(options))

async def text_util(update, context):
    track_command(update)
    parts = update.effective_message.text.split(maxsplit=1)
    cmd = parts[0].lstrip("/").lower()
    text = parts[1] if len(parts) > 1 else ""
    if not text:
        await update.effective_message.reply_text(f"❌ /{cmd} text")
        return
    if cmd == "reverse": out = text[::-1]
    elif cmd == "upper": out = text.upper()
    elif cmd == "lower": out = text.lower()
    elif cmd == "title": out = text.title()
    elif cmd == "count": out = f"Characters: {len(text)}\nWords: {len(text.split())}"
    elif cmd == "slug": out = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    elif cmd == "encodeurl": out = quote(text)
    elif cmd == "decodeurl": out = unquote(text)
    elif cmd == "islink":
        p = urlparse(text if "://" in text else "https://" + text)
        out = "✅ Link" if p.scheme in ("http","https") and p.netloc else "❌ Not a valid link"
    elif cmd == "remove_space": out = re.sub(r"\s+", "", text)
    elif cmd == "repeat":
        parts2 = text.split(maxsplit=1)
        if len(parts2) != 2 or not parts2[0].isdigit():
            out = "❌ /repeat 3 Hello"
        else:
            out = "\n".join([parts2[1]] * min(int(parts2[0]), 20))
    elif cmd == "binary":
        out = " ".join(format(ord(c), "08b") for c in text)
    elif cmd == "unbinary":
        try: out = "".join(chr(int(x,2)) for x in text.split())
        except Exception: out = "❌ Invalid binary"
    else: out = text
    await update.effective_message.reply_text(esc(out), parse_mode=ParseMode.HTML)

async def convert_cmd(update, context):
    track_command(update)
    if len(context.args) != 4 or context.args[2].lower() != "to":
        await update.effective_message.reply_text("🔄 /convert 10 km to mi\n🔄 /convert 25 c to f\n🔄 /convert 1 kg to lb")
        return
    try:
        value = float(context.args[0])
    except ValueError:
        await update.effective_message.reply_text("❌ Value si sahihi.")
        return
    src, dst = context.args[1].lower(), context.args[3].lower()
    factors = {
        ("km","mi"): 0.621371, ("mi","km"): 1.609344,
        ("m","ft"): 3.28084, ("ft","m"): 0.3048,
        ("kg","lb"): 2.2046226218, ("lb","kg"): 0.45359237,
        ("g","oz"): 0.035273962, ("oz","g"): 28.349523125,
        ("l","gal"): 0.2641720524, ("gal","l"): 3.785411784,
        ("cm","in"): 0.3937007874, ("in","cm"): 2.54,
    }
    if (src,dst) in factors:
        result = value * factors[(src,dst)]
    elif src in ("c","f") and dst in ("c","f"):
        result = value if src == dst else (value * 9/5 + 32 if src == "c" else (value - 32)*5/9)
    elif src in ("c","k") and dst in ("c","k"):
        result = value if src == dst else value + 273.15
    elif src == "k" and dst == "c":
        result = value - 273.15
    else:
        await update.effective_message.reply_text("❌ Conversion haipo kwenye list yangu.")
        return
    await update.effective_message.reply_text(f"🔄 <code>{value:g} {src} = {result:g} {dst}</code>", parse_mode=ParseMode.HTML)

async def dice(update, context):
    track_command(update)
    await update.effective_message.reply_dice(emoji="🎲")

async def dart(update, context):
    track_command(update)
    await update.effective_message.reply_dice(emoji="🎯")

async def football(update, context):
    track_command(update)
    await update.effective_message.reply_dice(emoji="⚽")

async def coin(update, context):
    track_command(update)
    await update.effective_message.reply_text("🪙 " + random.choice(["HEADS", "TAILS"]))

async def slot(update, context):
    track_command(update)
    await update.effective_message.reply_dice(emoji="🎰")

async def eightball(update, context):
    track_command(update)
    answers = ["Ndiyo.", "Hapana.", "Inawezekana.", "Uliza tena baadaye.", "Inaonekana hivyo.", "Siwezi kujua kwa uhakika."]
    await update.effective_message.reply_text("🎱 " + random.choice(answers))

async def joke(update, context):
    track_command(update)
    jokes = [
        "😂 Programmer aliulizwa kwa nini ana tabs 20? Akasema: bado hajapata ile yenye code.",
        "🤣 Wi-Fi ikikataa, kila mtu anakuwa engineer wa router.",
        "😅 Bug moja ikiingia, bugs wengine wanafuata kama familia.",
    ]
    await update.effective_message.reply_text(random.choice(jokes))

async def love(update, context):
    track_command(update)
    await update.effective_message.reply_text("❤️ Love meter: " + str(random.randint(1, 100)) + "%")

async def settitle(update, context):
    track_command(update)
    if not await require_right(update, context, "can_change_info"):
        return
    text = update.effective_message.text.partition(" ")[2].strip()
    if not text:
        await update.effective_message.reply_text("❌ /settitle Jina jipya")
        return
    try:
        await context.bot.set_chat_title(update.effective_chat.id, text)
        await update.effective_message.reply_text("✅ Group title updated.")
    except TelegramError as e:
        await update.effective_message.reply_text(f"❌ {esc(e)}", parse_mode=ParseMode.HTML)

async def setdescription(update, context):
    track_command(update)
    if not await require_right(update, context, "can_change_info"):
        return
    text = update.effective_message.text.partition(" ")[2].strip()
    if not text:
        await update.effective_message.reply_text("❌ /setdescription Maelezo")
        return
    try:
        await context.bot.set_chat_description(update.effective_chat.id, text)
        await update.effective_message.reply_text("✅ Description updated.")
    except TelegramError as e:
        await update.effective_message.reply_text(f"❌ {esc(e)}", parse_mode=ParseMode.HTML)

async def tagadmins(update, context):
    track_command(update)
    if not await caller_can_control(update, context):
        return
    admins_list = await context.bot.get_chat_administrators(update.effective_chat.id)
    mentions = []
    for a in admins_list:
        name = esc(a.user.first_name or a.user.full_name)
        mentions.append(f'<a href="tg://user?id={a.user.id}">{name}</a>')
    await update.effective_message.reply_text("📣 " + " ".join(mentions), parse_mode=ParseMode.HTML)

async def tagall(update, context):
    track_command(update)
    if not await caller_can_control(update, context):
        return
    # Telegram Bot API doesn't expose a general get-all-members method.
    # We can safely tag users the bot has observed.
    users = list(DATA["users"].items())[:50]
    if not users:
        await update.effective_message.reply_text("❌ Bado hakuna users walioonekana na bot.")
        return
    mentions = []
    for uid, data in users:
        name = esc(data.get("name") or "Member")
        mentions.append(f'<a href="tg://user?id={uid}">{name}</a>')
    await update.effective_message.reply_text("📣 <b>TAG SEEN MEMBERS</b>\n\n" + " ".join(mentions), parse_mode=ParseMode.HTML)

async def handle_new_members(update, context):
    if not is_group(update.effective_chat):
        return
    s = group_settings(update.effective_chat.id)
    count = await context.bot.get_chat_member_count(update.effective_chat.id)
    for member in update.effective_message.new_chat_members or []:
        remember_user(member)
        if s.get("antibot") and member.is_bot and member.id != context.bot.id:
            try:
                await context.bot.ban_chat_member(update.effective_chat.id, member.id)
            except TelegramError:
                pass
            continue
        if s.get("welcome"):
            text = render_template(s.get("welcome_text"), member, update.effective_chat, count)
            await update.effective_message.reply_text(esc(text), parse_mode=ParseMode.HTML)
    save_data()

async def handle_left_member(update, context):
    if not is_group(update.effective_chat):
        return
    member = update.effective_message.left_chat_member
    if not member:
        return
    s = group_settings(update.effective_chat.id)
    if s.get("goodbye"):
        text = render_template(s.get("goodbye_text") or "{name} ameondoka {group}.", member, update.effective_chat)
        await update.effective_message.reply_text(esc(text), parse_mode=ParseMode.HTML)

LINK_RE = re.compile(r"(https?://\S+|www\.\S+|t\.me/\S+)", re.I)
MENTION_RE = re.compile(r"(?<!\w)@\w{3,}", re.U)

async def warn_automatic(context, chat_id, user_id, reason):
    s = group_settings(chat_id)
    uid = str(user_id)
    current = int(s["warnings"].get(uid, 0)) + 1
    s["warnings"][uid] = current
    limit = int(s.get("warn_limit", 3))
    try:
        if current >= limit:
            await context.bot.ban_chat_member(chat_id, user_id)
            s["warnings"].pop(uid, None)
            await context.bot.send_message(chat_id, f"🚫 User ameban baada ya {reason} warnings {current}/{limit}.")
        else:
            await context.bot.send_message(chat_id, f"⚠️ Warning {current}/{limit} — {reason}.")
    except TelegramError:
        pass
    save_data()

async def handle_messages(update, context):
    msg = update.effective_message
    chat = update.effective_chat
    user = update.effective_user
    if not msg or not chat or not user:
        return
    if not is_group(chat):
        save_data()
        return
    s = group_settings(chat.id)

    if msg.new_chat_members or msg.left_chat_member:
        return

    if await is_admin(context, chat.id, user.id) or is_owner_or_sudo(user.id):
        save_data()
        return

    now = time.time()
    uid = str(user.id)

    # AFK mention/reply
    if msg.text:
        mentioned = False
        for other_uid in list(AFK_USERS):
            if f"tg://user?id={other_uid}" in msg.text:
                mentioned = True
                await msg.reply_text(f"💤 User huyu yuko AFK: {esc(AFK_USERS[other_uid])}", parse_mode=ParseMode.HTML)
        if user.id in AFK_USERS:
            AFK_USERS.pop(user.id, None)
            await msg.reply_text("👋 Karibu tena — AFK imeondolewa.")

    if s.get("antisticker") and msg.sticker:
        try: await msg.delete()
        except TelegramError: pass
        await warn_automatic(context, chat.id, user.id, "anti-sticker")
        return

    media = bool(msg.photo or msg.video or msg.audio or msg.voice or msg.document or msg.animation or msg.video_note)
    if s.get("antimedia") and media:
        try: await msg.delete()
        except TelegramError: pass
        await warn_automatic(context, chat.id, user.id, "anti-media")
        return

    text = msg.text or msg.caption or ""
    if s.get("antilink") and LINK_RE.search(text):
        try: await msg.delete()
        except TelegramError: pass
        await warn_automatic(context, chat.id, user.id, "anti-link")
        return

    if s.get("antimention") and len(MENTION_RE.findall(text)) >= 5:
        try: await msg.delete()
        except TelegramError: pass
        await warn_automatic(context, chat.id, user.id, "anti-mention")
        return

    if s.get("antiflood"):
        q = FLOOD_TRACKER[chat.id][user.id]
        q.append(now)
        window = int(s.get("antiflood_window", 8))
        limit = int(s.get("antiflood_limit", 7))
        while q and now - q[0] > window:
            q.popleft()
        if len(q) >= limit:
            q.clear()
            try: await msg.delete()
            except TelegramError: pass
            await warn_automatic(context, chat.id, user.id, "anti-flood")
            return

    if s.get("antispam"):
        q = SPAM_TRACKER[chat.id][user.id]
        signature = (text.strip().lower()[:200], now)
        q.append(signature)
        window = int(s.get("antispam_window", 12))
        limit = int(s.get("antispam_limit", 4))
        while q and now - q[0][1] > window:
            q.popleft()
        if len(q) >= limit:
            recent_texts = [x[0] for x in q]
            if len(recent_texts) >= 2 and len(set(recent_texts)) <= 2:
                q.clear()
                try: await msg.delete()
                except TelegramError: pass
                await warn_automatic(context, chat.id, user.id, "anti-spam")
                return

    # Custom filters
    if text:
        low = text.lower()
        for keyword, response in s.get("filters", {}).items():
            if keyword.lower() in low:
                await msg.reply_text(response)
                break

    save_data()

async def afk(update, context):
    track_command(update)
    reason = update.effective_message.text.partition(" ")[2].strip() or "AFK"
    AFK_USERS[update.effective_user.id] = reason
    await update.effective_message.reply_text(f"💤 {esc(update.effective_user.first_name)} yuko AFK: {esc(reason)}", parse_mode=ParseMode.HTML)

async def setfilter(update, context):
    track_command(update)
    if not await caller_can_control(update, context):
        return
    parts = update.effective_message.text.split(maxsplit=2)
    if len(parts) < 3:
        await update.effective_message.reply_text("🧩 /filter keyword response")
        return
    keyword, response = parts[1].lower(), parts[2]
    group_settings(update.effective_chat.id)["filters"][keyword] = response
    save_data()
    await update.effective_message.reply_text("✅ Filter imehifadhiwa.")

async def delfilter(update, context):
    track_command(update)
    if not await caller_can_control(update, context):
        return
    if not context.args:
        await update.effective_message.reply_text("🧩 /delfilter keyword")
        return
    group_settings(update.effective_chat.id)["filters"].pop(context.args[0].lower(), None)
    save_data()
    await update.effective_message.reply_text("🗑 Filter imefutwa.")

async def filters_cmd(update, context):
    track_command(update)
    if not is_group(update.effective_chat):
        return
    f = group_settings(update.effective_chat.id).get("filters", {})
    await update.effective_message.reply_text("🧩 <b>FILTERS</b>\n\n" + ("\n".join(f"• {esc(k)} → {esc(v)}" for k,v in f.items()) if f else "Hakuna filters."), parse_mode=ParseMode.HTML)

async def callback_handler(update, context):
    query = update.callback_query
    data = query.data or ""
    try:
        if data.startswith("menu:"):
            section = data.split(":",1)[1]
            if section == "main":
                await query.edit_message_reply_markup(reply_markup=main_menu())
            elif section == "group":
                await query.edit_message_reply_markup(
                    text=f"👥 <b>GROUP CENTER</b>\n\nModeration, protection, welcome na rules.",
                    parse_mode=ParseMode.HTML,
                    reply_markup=group_menu(),
                )
            elif section == "mod":
                await query.edit_message_text(
                    "🔨 <b>MODERATION</b>\n\n"
                    "/ban /unban /kick /softban\n/mute 10m /unmute\n/warn /unwarn /warnings /resetwarn\n/promote /demote\n/pin /unpin /del /purge\n/lock /unlock",
                    parse_mode=ParseMode.HTML,
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 GROUP", callback_data="menu:group")]]),
                )
            elif section == "protection":
                await query.edit_message_text(
                    "🛡 <b>PROTECTION</b>\n\n"
                    "/antilink on/off\n/antisticker on/off\n/antimedia on/off\n/antispam on/off\n/antiflood on/off\n/antibot on/off\n/antimention on/off\n/setwarnlimit 3\n/setspam 4 12\n/setflood 7 8",
                    parse_mode=ParseMode.HTML,
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 GROUP", callback_data="menu:group")]]),
                )
            elif section == "welcome":
                await query.edit_message_text(
                    "👋 <b>WELCOME</b>\n\n/welcome on/off\n/setwelcome text\n/goodbye on/off\n/setgoodbye text\n\nPlaceholders: {name} {username} {group} {id} {count}",
                    parse_mode=ParseMode.HTML,
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 GROUP", callback_data="menu:group")]]),
                )
            elif section == "rules":
                await query.edit_message_text(
                    "📜 <b>RULES</b>\n\n/setrules text\n/rules\n/clearrules",
                    parse_mode=ParseMode.HTML,
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 GROUP", callback_data="menu:group")]]),
                )
            elif section == "tools":
                await query.edit_message_reply_markup(reply_markup=tools_menu())
            elif section == "font":
                await query.edit_message_text(
                    "🔤 /font bold Hello\n/font italic Hello\n/font mono Hello\n/font full Hello",
                    parse_mode=ParseMode.HTML,
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 TOOLS", callback_data="menu:tools")]]),
                )
            elif section == "math":
                await query.edit_message_text(
                    "🧮 /math 2^10\n/math sqrt(144)\n/math 25% of 800\n\nBasic arithmetic pia inafanya.",
                    parse_mode=ParseMode.HTML,
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 TOOLS", callback_data="menu:tools")]]),
                )
            elif section == "qr":
                await query.edit_message_text(
                    "📱 Tuma /qr pamoja na text/link.\nMfano: /qr https://example.com",
                    parse_mode=ParseMode.HTML,
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 TOOLS", callback_data="menu:tools")]]),
                )
            elif section == "notes":
                await query.edit_message_text(
                    "📝 /save name text\n/get name\n/notes\n/delnote name\n/clearnotes",
                    parse_mode=ParseMode.HTML,
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 TOOLS", callback_data="menu:tools")]]),
                )
            elif section == "reminders":
                await query.edit_message_text(
                    "⏰ /remind 10m Soma\n/reminders\n/delreminder ID",
                    parse_mode=ParseMode.HTML,
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 TOOLS", callback_data="menu:tools")]]),
                )
            elif section == "encode":
                await query.edit_message_text(
                    "🔐 /base64 text\n/decode64 text\n/hash text\n/uuid\n/password 16\n/random 1 100\n/convert 10 km to mi",
                    parse_mode=ParseMode.HTML,
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 TOOLS", callback_data="menu:tools")]]),
                )
            elif section == "user":
                await query.edit_message_reply_markup(reply_markup=user_menu())
            elif section == "fun":
                await query.edit_message_reply_markup(reply_markup=fun_menu())
            elif section == "settings":
                if is_group(query.message.chat) and (await is_admin(context, query.message.chat.id, query.from_user.id) or is_owner_or_sudo(query.from_user.id)):
                    s = group_settings(query.message.chat.id)
                    kb = InlineKeyboardMarkup([
                        [InlineKeyboardButton(f"🔗 Anti-link {'ON' if s['antilink'] else 'OFF'}", callback_data="toggle:antilink"),
                         InlineKeyboardButton(f"🚦 Flood {'ON' if s['antiflood'] else 'OFF'}", callback_data="toggle:antiflood")],
                        [InlineKeyboardButton(f"🚫 Spam {'ON' if s['antispam'] else 'OFF'}", callback_data="toggle:antispam"),
                         InlineKeyboardButton(f"🎞 Media {'ON' if s['antimedia'] else 'OFF'}", callback_data="toggle:antimedia")],
                        [InlineKeyboardButton(f"🧷 Sticker {'ON' if s['antisticker'] else 'OFF'}", callback_data="toggle:antisticker"),
                         InlineKeyboardButton(f"🤖 Bot {'ON' if s['antibot'] else 'OFF'}", callback_data="toggle:antibot")],
                        [InlineKeyboardButton("🔙 BACK", callback_data="menu:main")],
                    ])
                    await query.edit_message_text("⚙️ <b>GROUP SETTINGS</b>", parse_mode=ParseMode.HTML, reply_markup=kb)
                else:
                    await query.answer("Admin wa group tu.", show_alert=True)
            elif section == "owner":
                await query.edit_message_text(
                    "👑 <b>OWNER</b>\n\n/owner\n/ownerpanel\n/addsudo\n/delsudo\n/listsudo\n/botstats\n/groups\n/broadcast",
                    parse_mode=ParseMode.HTML,
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 BACK", callback_data="menu:main")]]),
                )
            elif section == "inline":
                await query.edit_message_text(
                    "📌 <b>INLINE MODE</b>\n\nEnable Inline Mode via BotFather, then try:\n<code>@YourBot joke</code>\n<code>@YourBot info</code>",
                    parse_mode=ParseMode.HTML,
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 BACK", callback_data="menu:main")]]),
                )
            return

        if data.startswith("toggle:"):
            key = data.split(":",1)[1]
            if not is_group(query.message.chat):
                await query.answer("Group only.", show_alert=True)
                return
            if not (await is_admin(context, query.message.chat.id, query.from_user.id) or is_owner_or_sudo(query.from_user.id)):
                await query.answer("Admin wa group tu.", show_alert=True)
                return
            s = group_settings(query.message.chat.id)
            if key not in ("antilink","antiflood","antispam","antimedia","antisticker","antibot"):
                await query.answer("Setting haijulikani.", show_alert=True)
                return
            s[key] = not bool(s[key])
            save_data()
            await query.answer(f"{key}: {'ON' if s[key] else 'OFF'}")
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton(f"🔗 Anti-link {'ON' if s['antilink'] else 'OFF'}", callback_data="toggle:antilink"),
                 InlineKeyboardButton(f"🚦 Flood {'ON' if s['antiflood'] else 'OFF'}", callback_data="toggle:antiflood")],
                [InlineKeyboardButton(f"🚫 Spam {'ON' if s['antispam'] else 'OFF'}", callback_data="toggle:antispam"),
                 InlineKeyboardButton(f"🎞 Media {'ON' if s['antimedia'] else 'OFF'}", callback_data="toggle:antimedia")],
                [InlineKeyboardButton(f"🧷 Sticker {'ON' if s['antisticker'] else 'OFF'}", callback_data="toggle:antisticker"),
                 InlineKeyboardButton(f"🤖 Bot {'ON' if s['antibot'] else 'OFF'}", callback_data="toggle:antibot")],
                [InlineKeyboardButton("🔙 BACK", callback_data="menu:main")],
            ])
            await query.edit_message_reply_markup(reply_markup=kb)
            return

        if data.startswith("cmd:"):
            cmd = data.split(":",1)[1]
            fake = None
            if cmd == "id":
                fake = id_cmd
            elif cmd == "info":
                fake = info_cmd
            elif cmd == "status":
                fake = status_cmd
            elif cmd == "ginfo":
                fake = ginfo
            elif cmd == "dice":
                fake = dice
            elif cmd == "dart":
                fake = dart
            elif cmd == "football":
                fake = football
            elif cmd == "coin":
                fake = coin
            elif cmd == "slot":
                fake = slot
            elif cmd == "8ball":
                fake = eightball
            if fake:
                await fake(update, context)
                return
        await query.answer()
    except TelegramError as e:
        logger.warning("Callback error: %s", e)

async def inline_query(update, context):
    q = (update.inline_query.query or "").strip().lower()
    results = [
        InlineQueryResultArticle(
            id="owner",
            title="👑 Owner",
            description="LUQMAN SJ",
            input_message_content=InputTextMessageContent(
                f"👑 <b>{esc(OWNER_NAME)}</b>\nWhatsApp: <code>{esc(OWNER_WHATSAPP)}</code>",
                parse_mode=ParseMode.HTML,
            ),
        ),
        InlineQueryResultArticle(
            id="joke",
            title="😂 Joke",
            description="Send a clean joke",
            input_message_content=InputTextMessageContent("😂 " + random.choice([
                "Programmer alifungua browser, bug ikasema: mimi nilikuwahi.",
                "Wi-Fi ikizima, kila mtu anageuka IT support.",
            ])),
        ),
        InlineQueryResultArticle(
            id="info",
            title="🤖 Bot Info",
            description=BOT_NAME,
            input_message_content=InputTextMessageContent(
                f"🤖 <b>{esc(BOT_NAME)}</b>\nVersion: <code>{esc(VERSION)}</code>\nMode: <code>{esc(MODE)}</code>",
                parse_mode=ParseMode.HTML,
            ),
        ),
    ]
    if q:
        results = [r for r in results if q in r.title.lower() or q in r.description.lower()]
    await update.inline_query.answer(results[:20], cache_time=1)

KNOWN_COMMANDS = {
    "start","menu","help","alive","ping","owner","ownerpanel","addsudo","delsudo","listsudo","botstats","groups","broadcast",
    "id","info","status","ginfo","admins","antilink","antisticker","antimedia","antispam","antiflood","antibot","antimention",
    "welcome","goodbye","setwelcome","setgoodbye","setrules","rules","clearrules","warn","warnings","unwarn","resetwarn","ban",
    "unban","softban","mute","unmute","kick","promote","demote","pin","unpin","del","purge","lock","unlock","setwarnlimit",
    "setflood","setspam","math","calc","font","qr","save","get","notes","delnote","clearnotes","remind","reminders","delreminder",
    "base64","decode64","hash","uuid","password","random","choose","reverse","upper","lower","title","count","slug","encodeurl",
    "decodeurl","islink","remove_space","repeat","binary","unbinary","convert","dice","dart","football","coin","slot","8ball","joke",
    "love","settitle","setdescription","tagadmins","tagall","afk","filter","delfilter","filters"
}

async def unknown_command(update, context):
    msg = update.effective_message
    if not msg or not msg.text or not msg.text.startswith("/"):
        return
    token = msg.text.split()[0][1:].split("@")[0].lower()
    if token and token not in KNOWN_COMMANDS:
        await msg.reply_text(f"❓ Command <code>/{esc(token)}</code> haipo.\nTumia /menu.", parse_mode=ParseMode.HTML)

async def track_all_messages(update, context):
    # Group -1 tracker so commands and ordinary messages both count.
    if update.effective_message and update.effective_user:
        remember_user(update.effective_user)
        DATA["stats"]["messages"] = int(DATA["stats"].get("messages", 0)) + 1

async def error_handler(update, context):
    err = context.error
    if isinstance(err, (BadRequest, Forbidden)):
        logger.warning("Telegram error: %s", err)
    else:
        logger.exception("Unhandled error: %s", err)

def register_handlers(app):
    commands = {
        "start": start, "menu": menu, "help": menu, "alive": alive, "ping": ping, "owner": owner, "ownerpanel": ownerpanel,
        "addsudo": idsudo, "delsudo": delsudo, "listsudo": listsudo, "botstats": botstats, "groups": groups_cmd, "broadcast": broadcast,
        "id": id_cmd, "info": info_cmd, "status": status_cmd, "ginfo": ginfo, "admins": admins,
        "antilink": antilink, "antisticker": antisticker, "antimedia": antimedia, "antispam": antispam, "antiflood": antiflood,
        "antibot": antibot, "antimention": antimention, "welcome": welcome_cmd, "goodbye": goodbye_cmd,
        "setwelcome": setwelcome, "setgoodbye": setgoodbye, "setrules": setrules, "rules": rules, "clearrules": clearrules,
        "warn": warn, "warnings": warnings, "unwarn": unwarn, "resetwarn": resetwarn, "ban": ban, "unban": unban, "softban": softban,
        "mute": mute, "unmute": unmute, "kick": kick, "promote": promote, "demote": demote, "pin": pin, "unpin": unpin, "del": delete_cmd,
        "purge": purge, "lock": lock, "unlock": unlock, "setwarnlimit": setwarnlimit, "setflood": setflood, "setspam": setspam,
        "math": math_cmd, "calc": math_cmd, "font": font_cmd, "qr": qr_cmd, "save": save_note, "get": get_note, "notes": notes,
        "delnote": delnote, "clearnotes": clearnotes, "remind": remind, "reminders": reminders, "delreminder": delreminder,
        "base64": encode_cmd, "decode64": encode_cmd, "hash": encode_cmd, "uuid": uuid_cmd, "password": password_cmd, "random": random_cmd,
        "choose": choose_cmd, "reverse": text_util, "upper": text_util, "lower": text_util, "title": text_util, "count": text_util,
        "slug": text_util, "encodeurl": text_util, "decodeurl": text_util, "islink": text_util, "remove_space": text_util, "repeat": text_util,
        "binary": text_util, "unbinary": text_util, "convert": convert_cmd, "dice": dice, "dart": dart, "football": football,
        "coin": coin, "slot": slot, "8ball": eightball, "joke": joke, "love": love, "settitle": settitle, "setdescription": setdescription,
        "tagadmins": tagadmins, "tagall": tagall, "afk": afk, "filter": setfilter, "delfilter": delfilter, "filters": filters_cmd,
    }
    for name, callback in commands.items():
        app.add_handler(CommandHandler(name, callback))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(InlineQueryHandler(inline_query))
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, handle_new_members))
    app.add_handler(MessageHandler(filters.StatusUpdate.LEFT_CHAT_MEMBER, handle_left_member))
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, handle_messages))
    app.add_handler(MessageHandler(filters.COMMAND, unknown_command), group=1)

def main():
    if TOKEN == "8712244204:AAEvEdORCg1bx3U77CFup0nMeDJkwDjof_g":
        raise RuntimeError("Weka Telegram bot token yako kwenye variable TOKEN.")
    app = (
        Application.builder()
        .token(TOKEN)
        .post_init(post_init)
        .build()
    )
    # Track all messages in an earlier handler group.
    app.add_handler(MessageHandler(filters.ALL, track_all_messages, block=False), group=-1)
    register_handlers(app)
    app.add_error_handler(error_handler)
    logger.info("%s v%s starting in %s mode", BOT_NAME, VERSION, MODE)
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)

if __name__ == "__main__":
    main()
