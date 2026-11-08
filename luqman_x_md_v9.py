
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
import asyncio
import copy
import urllib.request
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
    ChatJoinRequestHandler,
    InlineQueryHandler,
    ContextTypes,
    filters,
)

BOT_NAME = "LUQMAN X MD"
OWNER_NAME = "LUQMAN SJ"
OWNER_ID = 7847425637
OWNER_WHATSAPP = "+255678716839"

# KEEP YOUR CURRENT TOKEN HERE.
TOKEN = "PASTE_YOUR_CURRENT_TOKEN_HERE"

DATA_FILE = Path("luqman_data.json")
MODE = "public"
VERSION = "9.0.0"
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
    "title": "",
    "sp": {},
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
    sp_post_init(application)

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
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("⚙️ Group settings", callback_data="spx:open"),
        InlineKeyboardButton("📋 Commands menu", callback_data="menu:main"),
    ]])
    await update.effective_message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)

def main_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🛠 SETTINGS PANEL", callback_data="spx:open")],
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

async def addsudo(update, context):
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
    text = await do_warn(context, update.effective_chat.id, target.id, target.full_name, "")
    await update.effective_message.reply_text(text, parse_mode=ParseMode.HTML)

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

LINK_RE = re.compile(r"(https?://\S+|www\.\S+|t\.me/\S+)", re.I)
MENTION_RE = re.compile(r"(?<!\w)@\w{3,}", re.U)

async def warn_automatic(context, chat_id, user_id, reason):
    text = await do_warn(context, chat_id, user_id, None, reason)
    await notify(context, chat_id, text, temp=30)

async def handle_messages(update, context):
    msg = update.effective_message
    chat = update.effective_chat
    user = update.effective_user
    if not msg or not chat or not user:
        return
    if await sp_pending_input(update, context):
        return
    if not is_group(chat):
        save_data()
        return
    s = group_settings(chat.id)

    if msg.new_chat_members or msg.left_chat_member:
        return

    if is_service_message(msg):
        await handle_service_message(update, context)
        return

    if await is_admin(context, chat.id, user.id) or is_owner_or_sudo(user.id):
        save_data()
        return

    edited = update.edited_message is not None
    if edited and not sp(chat.id)["delmsg"]["edit_checks"]:
        return

    if await sp_enforce(update, context, edited=edited):
        save_data()
        return
    await sp_after_checks(update, context)

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
                await query.edit_message_text(
                    text=f"👥 <b>GROUP CENTER</b>\n\nModeration, protection, welcome na rules.\n\n🛠 Full panel: /settings",
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

# =====================================================================
#  v9 — SETTINGS PANEL & ADVANCED GROUP PROTECTION
# =====================================================================

APP_REF = {}
PENDING = {}              # (panel_chat_id, user_id) -> pending input
RC_DRAFT = {}             # (group_id, user_id) -> recurring draft text
USER_MSGS = defaultdict(lambda: deque(maxlen=60))
FLOOD2 = defaultdict(deque)
JOIN_TRACKER = defaultdict(deque)
JOINED_AT = {}
PRIVATE_WELCOMED = {}
MEDIA_GROUP_SEEN = {}
NOTICE_COOLDOWN = {}
REPORT_COOLDOWN = {}
CHECK_CACHE = {}
PENDING_TTL = 300

PUN_CODES = ("off", "warn", "kick", "mute", "ban")
PUN_NAMES = {"off": "Off", "warn": "Warn", "kick": "Kick", "mute": "Mute", "ban": "Ban"}

MEDIA_TYPES = [
    ("photo", "📸", "Photo"),
    ("video", "🎞", "Video"),
    ("album", "🖼", "Album"),
    ("gif", "🎥", "GIF"),
    ("sticker", "🃏", "Sticker"),
    ("animsticker", "🎭", "Animated stickers"),
    ("file", "💾", "File"),
    ("voice", "🎙", "Voice"),
    ("audio", "🎵", "Audio"),
    ("videonote", "⭕", "Video note"),
    ("poll", "📊", "Poll"),
]
MEDIA_CODE_LABEL = {
    "off": "✅ Off", "warn": "❕ Warn", "kick": "❗ Kick",
    "mute": "🔇 Mute", "ban": "🚷 Ban", "del": "🗑 Deletion",
}
MEDIA_CODE_ICON = {"off": "✅", "warn": "❕", "kick": "❗", "mute": "🔇", "ban": "🚷", "del": "🗑"}

ALPHABETS = [
    ("arabic", "☪️", "Arabic"),
    ("cyrillic", "🇷🇺", "Cyrillic"),
    ("chinese", "🇨🇳", "Chinese"),
    ("latin", "🔤", "Latin"),
    ("hindi", "🇮🇳", "Hindi"),
    ("bengali", "🇧🇩", "Bengali"),
]

CMDPERM_COMMANDS = ["staff", "rules", "me", "translate", "link"]
CMDPERM_LEVELS = ("nobody", "staff", "all", "private")

SERVICE_ATTRS = (
    "pinned_message", "new_chat_title", "new_chat_photo", "delete_chat_photo",
    "group_chat_created", "supergroup_chat_created", "message_auto_delete_timer_changed",
    "migrate_to_chat_id", "migrate_from_chat_id", "video_chat_scheduled",
    "video_chat_started", "video_chat_ended", "video_chat_participants_invited",
    "forum_topic_created", "forum_topic_closed", "forum_topic_reopened",
    "forum_topic_edited", "general_forum_topic_hidden", "general_forum_topic_unhidden",
)


def _pc():
    return {"pun": "off", "del": False}


SP_DEFAULT = {
    "flood": {"pun": "off", "del": False, "msgs": 5, "secs": 3},
    "tg_links": _pc(),
    "forward": _pc(),
    "quote": _pc(),
    "total_links": _pc(),
    "alpha": {k: _pc() for k, _, _ in ALPHABETS},
    "media": {k: "off" for k, _, _ in MEDIA_TYPES},
    "warn_pun": "ban",
    "mute_secs": 3600,
    "checks": {
        "surname": False, "username": False, "photo": False,
        "channel": False, "channel_name": "", "add": False, "add_count": 1,
        "n_arabic": False, "n_chinese": False, "n_russian": False, "n_spam": False,
        "at_join": False, "delete": False,
    },
    "blocks": {"join": False, "leave": False, "joinleave": False, "multijoin": False, "blacklist": []},
    "captcha": {"on": False, "pun": "kick", "timeout": 120, "clear": True, "pending": {}},
    "approval": {"auto": False, "welcome": "group"},
    "welcome": {"mode": "always", "delete_last": False, "last_id": 0, "seen": []},
    "goodbye": {"private": False, "delete_last": False, "last_id": 0},
    "night": {
        "on": False, "start": 23, "end": 9, "silence": True, "media": False,
        "advise": False, "tz": 3, "active": False, "saved": None,
    },
    "delmsg": {
        "commands": False, "silence": False, "edit_checks": True,
        "service_join": False, "service_leave": False, "service_pin": False, "service_other": False,
        "scheduled": 0, "block_cancel": False, "selfdestruct": 0,
    },
    "report": {"mode": "founder", "tag_founder": False, "tag_admins": False, "staff_chat": 0},
    "words": {"list": [], "pun": "off", "del": False},
    "length": {"max": 0, "pun": "off", "del": False},
    "recurring": [],
    "log_chat": 0,
    "invite_link": "",
    "added": {},
    "cmdperm": {"staff": "staff", "rules": "all", "me": "all", "translate": "all", "link": "all"},
    "rich": {
        "welcome": {"media": None, "buttons": [], "html": False},
        "goodbye": {"media": None, "buttons": [], "html": False},
        "rules": {"media": None, "buttons": [], "html": False},
    },
}


def _deep_fill(target, default):
    for k, v in default.items():
        if k not in target:
            target[k] = copy.deepcopy(v)
        elif isinstance(v, dict) and isinstance(target[k], dict):
            _deep_fill(target[k], v)


def sp(chat_id):
    s = group_settings(chat_id)
    if not isinstance(s.get("sp"), dict):
        s["sp"] = {}
    _deep_fill(s["sp"], SP_DEFAULT)
    return s["sp"]


def mention(uid, name=None):
    if not name:
        name = (DATA["users"].get(str(uid)) or {}).get("name") or "User"
    return f'<a href="tg://user?id={uid}">{esc(name)}</a>'


def cfg_active(cfg):
    return cfg.get("pun", "off") != "off" or bool(cfg.get("del"))


def pun_label(cfg):
    p = cfg.get("pun", "off")
    d = bool(cfg.get("del"))
    if p == "off":
        return "Deletion" if d else "Off"
    return PUN_NAMES.get(p, p) + (" + Deletion" if d else "")


def human_secs(sec):
    sec = int(sec)
    if sec <= 0:
        return "Off"
    if sec % 86400 == 0:
        return f"{sec // 86400}d"
    if sec % 3600 == 0:
        return f"{sec // 3600}h"
    if sec % 60 == 0:
        return f"{sec // 60}m"
    return f"{sec}s"


def onoff(v):
    return "✅" if v else "❌"


# ---------------------------------------------------------------------
#  Message helpers
# ---------------------------------------------------------------------
async def safe_delete(msg):
    try:
        await msg.delete()
        return True
    except TelegramError:
        return False


async def delete_msg_job(context):
    d = context.job.data
    try:
        await context.bot.delete_message(d["chat_id"], d["message_id"])
    except TelegramError:
        pass


def schedule_delete(context, chat_id, message_id, delay):
    try:
        context.job_queue.run_once(delete_msg_job, delay, data={"chat_id": chat_id, "message_id": message_id})
    except Exception:
        logger.debug("Could not schedule delete", exc_info=True)


async def notify(context, chat_id, text, markup=None, temp=0):
    try:
        m = await context.bot.send_message(chat_id, text, parse_mode=ParseMode.HTML, reply_markup=markup)
    except TelegramError as e:
        logger.warning("notify failed: %s", e)
        return None
    if temp and m:
        schedule_delete(context, chat_id, m.message_id, temp)
    return m


async def log_action(context, chat_id, text):
    try:
        target = sp(chat_id).get("log_chat")
        if not target:
            return
        title = group_settings(chat_id).get("title") or str(chat_id)
        await context.bot.send_message(target, f"📋 <b>{esc(title)}</b>\n{text}", parse_mode=ParseMode.HTML)
    except TelegramError as e:
        logger.warning("log_action failed: %s", e)


def msg_text(msg):
    return (msg.text or msg.caption or "") if msg else ""


# ---------------------------------------------------------------------
#  Punishments
# ---------------------------------------------------------------------
async def kick_user(context, chat_id, user_id):
    await context.bot.ban_chat_member(chat_id, user_id)
    await context.bot.unban_chat_member(chat_id, user_id, only_if_banned=True)


async def mute_user(context, chat_id, user_id, seconds):
    until = time.time() + seconds
    await context.bot.restrict_chat_member(
        chat_id, user_id,
        permissions=mute_permissions(),
        until_date=datetime.now(timezone.utc) + timedelta(seconds=seconds),
    )
    group_settings(chat_id)["mutes"][str(user_id)] = until
    old = MUTE_JOBS.pop((chat_id, user_id), None)
    if old:
        try:
            old.schedule_removal()
        except Exception:
            pass
    try:
        job = context.job_queue.run_once(
            unmute_job, when=seconds,
            data={"chat_id": chat_id, "user_id": user_id},
            name=f"unmute:{chat_id}:{user_id}",
        )
        MUTE_JOBS[(chat_id, user_id)] = job
    except Exception:
        logger.debug("Could not schedule unmute", exc_info=True)


async def purge_user_messages(context, chat_id, user_id):
    if not sp(chat_id)["delmsg"]["block_cancel"]:
        return
    ids = list(USER_MSGS.pop((chat_id, user_id), []))
    for mid in ids:
        try:
            await context.bot.delete_message(chat_id, mid)
        except TelegramError:
            pass


async def do_warn(context, chat_id, user_id, name=None, reason=""):
    s = group_settings(chat_id)
    p = sp(chat_id)
    uid = str(user_id)
    who = mention(user_id, name)
    current = int(s["warnings"].get(uid, 0)) + 1
    limit = max(1, int(s.get("warn_limit", 3)))
    track_moderation()
    why = f" — {esc(reason)}" if reason else ""
    if current < limit:
        s["warnings"][uid] = current
        save_data()
        return f"⚠️ {who} warning <b>{current}/{limit}</b>{why}."
    s["warnings"].pop(uid, None)
    pun = p.get("warn_pun", "ban")
    try:
        if pun == "kick":
            await kick_user(context, chat_id, user_id)
            text = f"❗ {who} was kicked after warnings {current}/{limit}{why}."
        elif pun == "mute":
            secs = int(p.get("mute_secs", 3600))
            await mute_user(context, chat_id, user_id, secs)
            text = f"🔇 {who} muted for {human_secs(secs)} after warnings {current}/{limit}{why}."
        elif pun == "ban":
            await context.bot.ban_chat_member(chat_id, user_id)
            text = f"🚫 {who} banned after warnings {current}/{limit}{why}."
        else:
            text = f"⚠️ {who} reached warnings {current}/{limit}{why}."
        if pun in ("kick", "ban"):
            await purge_user_messages(context, chat_id, user_id)
    except TelegramError as e:
        text = f"⚠️ Warning {current}/{limit}, but the punishment failed: {esc(e)}"
    save_data()
    await log_action(context, chat_id, f"🚨 {text}")
    return text


async def apply_punishment(context, chat_id, user_id, name, pun, reason):
    """Applies warn/kick/mute/ban and returns an HTML notice (or None)."""
    who = mention(user_id, name)
    p = sp(chat_id)
    if pun == "warn":
        return await do_warn(context, chat_id, user_id, name, reason)
    track_moderation()
    try:
        if pun == "kick":
            await kick_user(context, chat_id, user_id)
            txt = f"❗ {who} kicked — {esc(reason)}"
        elif pun == "mute":
            secs = int(p.get("mute_secs", 3600))
            await mute_user(context, chat_id, user_id, secs)
            txt = f"🔇 {who} muted for {human_secs(secs)} — {esc(reason)}"
        elif pun == "ban":
            await context.bot.ban_chat_member(chat_id, user_id)
            txt = f"🚷 {who} banned — {esc(reason)}"
        else:
            return None
    except TelegramError as e:
        logger.warning("Punishment failed: %s", e)
        return None
    if pun in ("kick", "ban"):
        await purge_user_messages(context, chat_id, user_id)
    await log_action(context, chat_id, f"🚨 {txt}")
    save_data()
    return txt


async def punish(update, context, cfg, reason):
    msg = update.effective_message
    chat = update.effective_chat
    user = update.effective_user
    if cfg.get("del"):
        await safe_delete(msg)
    pun = cfg.get("pun", "off")
    if pun != "off":
        text = await apply_punishment(context, chat.id, user.id, user.full_name, pun, reason)
        if text:
            await notify(context, chat.id, text, temp=30)
    return True


# ---------------------------------------------------------------------
#  Detection helpers
# ---------------------------------------------------------------------
SCRIPT_RANGES = {
    "arabic": [(0x0600, 0x06FF), (0x0750, 0x077F), (0x08A0, 0x08FF), (0xFB50, 0xFDFF), (0xFE70, 0xFEFF)],
    "cyrillic": [(0x0400, 0x052F), (0x1C80, 0x1C8F), (0x2DE0, 0x2DFF), (0xA640, 0xA69F)],
    "chinese": [(0x4E00, 0x9FFF), (0x3400, 0x4DBF), (0xF900, 0xFAFF), (0x20000, 0x2A6DF)],
    "hindi": [(0x0900, 0x097F)],
    "bengali": [(0x0980, 0x09FF)],
}

TG_LINK_RE = re.compile(r"(?<![\w.-])(?:(?:https?://)?(?:t(?:elegram)?\.me|telegram\.dog)/\S+|tg://\S+)", re.I)
SPAM_NAME_RE = re.compile(
    r"(https?://|www\.|t\.me|telegram\.me|@\w{3,}|\b[a-z0-9-]+\.(?:com|net|org|ru|xyz|io|me|co|info|site|top|online)\b)",
    re.I,
)
URL_RE = re.compile(r"(?<![\w.-])(?:https?://\S+|www\.\S+|t\.me/\S+)", re.I)
AT_ADMIN_RE = re.compile(r"(?<![\w@])@admins?\b", re.I)


def detect_scripts(text):
    """Returns the set of alphabets found in text.
    Non-Latin scripts: flagged when at least one letter exists.
    Latin: flagged when it is at least half of all letters."""
    found = set()
    letters = 0
    latin = 0
    for ch in text or "":
        if not ch.isalpha():
            continue
        letters += 1
        cp = ord(ch)
        if cp < 0x250 and cp not in (0xD7, 0xF7):
            latin += 1
            continue
        for key, ranges in SCRIPT_RANGES.items():
            if any(lo <= cp <= hi for lo, hi in ranges):
                found.add(key)
                break
    if letters and latin / letters >= 0.5:
        found.add("latin")
    return found


def media_kinds(msg):
    kinds = []
    if getattr(msg, "media_group_id", None):
        kinds.append("album")
    if msg.animation:
        kinds.append("gif")
    elif msg.sticker:
        st = msg.sticker
        kinds.append("animsticker" if (getattr(st, "is_animated", False) or getattr(st, "is_video", False)) else "sticker")
    elif msg.photo:
        kinds.append("photo")
    elif msg.video:
        kinds.append("video")
    elif msg.video_note:
        kinds.append("videonote")
    elif msg.voice:
        kinds.append("voice")
    elif msg.audio:
        kinds.append("audio")
    elif getattr(msg, "poll", None):
        kinds.append("poll")
    elif msg.document:
        kinds.append("file")
    return kinds


def msg_has_media(msg):
    return bool(media_kinds(msg))


def extract_urls(msg):
    text = msg_text(msg)
    urls = [m.group(0) for m in URL_RE.finditer(text)]
    for ent in list(msg.entities or []) + list(msg.caption_entities or []):
        if ent.type == "text_link" and getattr(ent, "url", None):
            urls.append(ent.url)
        elif ent.type == "url":
            try:
                chunk = text[ent.offset:ent.offset + ent.length]
                if chunk:
                    urls.append(chunk)
            except Exception:
                pass
    return urls


def is_forwarded(msg):
    return bool(getattr(msg, "forward_origin", None) or getattr(msg, "forward_date", None))


def is_service_message(msg):
    return any(getattr(msg, a, None) for a in SERVICE_ATTRS)


def local_now(tz_hours):
    return datetime.now(timezone.utc) + timedelta(hours=tz_hours)


def night_active_now(n):
    h = local_now(n.get("tz", 3)).hour
    a, b = int(n.get("start", 23)), int(n.get("end", 9))
    if a == b:
        return False
    if a < b:
        return a <= h < b
    return h >= a or h < b

# ---------------------------------------------------------------------
#  Checks (obligations + name blocks)
# ---------------------------------------------------------------------
def name_block_reasons(p, user):
    ck = p["checks"]
    full = user.full_name or ""
    reasons = []
    scripts = detect_scripts(full) if (ck["n_arabic"] or ck["n_chinese"] or ck["n_russian"]) else set()
    if ck["n_arabic"] and "arabic" in scripts:
        reasons.append("Arabic names are not allowed")
    if ck["n_chinese"] and "chinese" in scripts:
        reasons.append("Chinese names are not allowed")
    if ck["n_russian"] and "cyrillic" in scripts:
        reasons.append("Russian/Cyrillic names are not allowed")
    if ck["n_spam"] and SPAM_NAME_RE.search(full):
        reasons.append("Spam-looking names are not allowed")
    return reasons


async def has_profile_photo(context, user_id):
    key = ("ph", user_id)
    cached = CHECK_CACHE.get(key)
    if cached and time.time() - cached[0] < 600:
        return cached[1]
    try:
        photos = await context.bot.get_user_profile_photos(user_id, limit=1)
        val = photos.total_count > 0
    except TelegramError:
        val = True
    CHECK_CACHE[key] = (time.time(), val)
    return val


async def in_required_channel(context, channel, user_id):
    key = ("ch", channel, user_id)
    cached = CHECK_CACHE.get(key)
    if cached and time.time() - cached[0] < 60:
        return cached[1]
    try:
        member = await context.bot.get_chat_member(channel, user_id)
        status = str(getattr(member.status, "value", member.status))
        val = status not in ("left", "kicked", "banned") and not (
            status == "restricted" and not getattr(member, "is_member", True)
        )
    except TelegramError:
        val = True
    CHECK_CACHE[key] = (time.time(), val)
    return val


async def obligation_reasons(context, chat_id, user):
    p = sp(chat_id)
    ck = p["checks"]
    reasons = []
    if ck["surname"] and not user.last_name:
        reasons.append("set a surname (last name) in your profile")
    if ck["username"] and not user.username:
        reasons.append("set a Telegram username")
    if ck["photo"] and not await has_profile_photo(context, user.id):
        reasons.append("set a profile picture")
    if ck["channel"] and ck["channel_name"]:
        if not await in_required_channel(context, ck["channel_name"], user.id):
            reasons.append(f"join {esc(ck['channel_name'])}")
    if ck["add"]:
        have = int(p["added"].get(str(user.id), 0))
        need = int(ck["add_count"])
        if have < need:
            reasons.append(f"add {need - have} more member(s) to the group")
    return reasons


# ---------------------------------------------------------------------
#  Enforcement for ordinary (non-admin) messages
# ---------------------------------------------------------------------
async def sp_enforce(update, context, edited=False):
    """Returns True when the message was handled and processing should stop."""
    msg = update.effective_message
    chat = update.effective_chat
    user = update.effective_user
    p = sp(chat.id)
    text = msg_text(msg)
    dm = p["delmsg"]

    # 1. Blacklist
    if user.id in p["blocks"]["blacklist"]:
        await safe_delete(msg)
        try:
            await context.bot.ban_chat_member(chat.id, user.id)
            await log_action(context, chat.id, f"⛔ Blacklisted user {mention(user.id, user.full_name)} was banned.")
        except TelegramError:
            pass
        return True

    # 2. Global silence
    if dm["silence"]:
        await safe_delete(msg)
        return True

    # 3. Night mode: delete medias
    n = p["night"]
    if n["on"] and n["media"] and msg_has_media(msg) and night_active_now(n):
        await safe_delete(msg)
        return True

    # 4. Obligations + name blocks
    ck = p["checks"]
    needs_check = any(ck[k] for k in ("surname", "username", "photo", "channel", "add",
                                      "n_arabic", "n_chinese", "n_russian", "n_spam"))
    if needs_check:
        reasons = name_block_reasons(p, user)
        if not reasons:
            reasons = await obligation_reasons(context, chat.id, user)
        if reasons:
            if ck["delete"]:
                await safe_delete(msg)
            key = (chat.id, user.id)
            if time.time() - NOTICE_COOLDOWN.get(key, 0) > 30:
                NOTICE_COOLDOWN[key] = time.time()
                lines = "\n".join(f"• {r}" for r in reasons)
                await notify(context, chat.id,
                             f"🔦 {mention(user.id, user.full_name)}, to write in this group you must:\n{lines}",
                             temp=20)
            return bool(ck["delete"])

    # 5. Media block
    for kind in media_kinds(msg):
        code = p["media"].get(kind, "off")
        if code == "off":
            continue
        label = next((l for k, _, l in MEDIA_TYPES if k == kind), kind)
        if kind == "album":
            gkey = (chat.id, msg.media_group_id)
            now = time.time()
            for old in [k for k, t in MEDIA_GROUP_SEEN.items() if now - t > 120]:
                MEDIA_GROUP_SEEN.pop(old, None)
            if gkey in MEDIA_GROUP_SEEN:
                await safe_delete(msg)
                return True
            MEDIA_GROUP_SEEN[gkey] = now
        cfg = {"pun": "off" if code == "del" else code, "del": True}
        return await punish(update, context, cfg, f"{label} is not allowed")

    # 6. Alphabets
    if text:
        scripts = detect_scripts(text)
        for key, _, label in ALPHABETS:
            cfg = p["alpha"][key]
            if key in scripts and cfg_active(cfg):
                return await punish(update, context, cfg, f"{label} alphabet is not allowed")

    # 7. Anti-spam: forwards / quotes / links
    if cfg_active(p["forward"]) and is_forwarded(msg):
        return await punish(update, context, p["forward"], "forwarded messages are not allowed")
    if cfg_active(p["quote"]) and (getattr(msg, "quote", None) or getattr(msg, "external_reply", None)):
        return await punish(update, context, p["quote"], "quotes are not allowed")
    if cfg_active(p["tg_links"]) or cfg_active(p["total_links"]):
        urls = extract_urls(msg)
        blob = text + " " + " ".join(urls)
        if cfg_active(p["tg_links"]) and TG_LINK_RE.search(blob):
            return await punish(update, context, p["tg_links"], "Telegram links are not allowed")
        if cfg_active(p["total_links"]) and urls:
            return await punish(update, context, p["total_links"], "links are not allowed")

    # 8. Flood
    fl = p["flood"]
    if not edited and cfg_active(fl):
        q = FLOOD2[(chat.id, user.id)]
        now = time.time()
        q.append(now)
        secs = max(1, int(fl["secs"]))
        while q and now - q[0] > secs:
            q.popleft()
        if len(q) >= max(2, int(fl["msgs"])):
            q.clear()
            return await punish(update, context, fl, "flood")

    # 9. Banned words
    wd = p["words"]
    if text and wd["list"] and cfg_active(wd):
        low = text.lower()
        for w in wd["list"]:
            if w and w in low:
                return await punish(update, context, wd, "banned word")

    # 10. Message length
    ln = p["length"]
    if text and int(ln["max"]) > 0 and len(text) > int(ln["max"]) and cfg_active(ln):
        return await punish(update, context, ln, f"message too long (max {ln['max']})")

    return False


async def sp_after_checks(update, context):
    """Runs for non-admin messages that passed every check."""
    msg = update.effective_message
    chat = update.effective_chat
    user = update.effective_user
    if update.edited_message is None:
        USER_MSGS[(chat.id, user.id)].append(msg.message_id)
    text = msg_text(msg)
    if text and AT_ADMIN_RE.search(text):
        await do_report(update, context)


async def sp_track(update, context):
    """Runs for every message (group -1): titles, command cleanup, scheduled deletion."""
    chat = update.effective_chat
    msg = update.message
    if not chat or not msg or not is_group(chat):
        return
    s = group_settings(chat.id)
    if chat.title and s.get("title") != chat.title:
        s["title"] = chat.title
    dm = sp(chat.id)["delmsg"]
    delay = None
    if dm["commands"] and msg.text and msg.text.startswith("/"):
        delay = 3
    if int(dm["scheduled"]) > 0:
        delay = min(delay, int(dm["scheduled"])) if delay else int(dm["scheduled"])
    if delay:
        schedule_delete(context, chat.id, msg.message_id, delay)


async def handle_service_message(update, context):
    msg = update.effective_message
    chat = update.effective_chat
    dm = sp(chat.id)["delmsg"]
    if getattr(msg, "pinned_message", None):
        if dm["service_pin"]:
            await safe_delete(msg)
    elif dm["service_other"]:
        await safe_delete(msg)


# ---------------------------------------------------------------------
#  Rich messages (text + media + buttons) for welcome / goodbye / rules
# ---------------------------------------------------------------------
RICH_TEXT_KEY = {"welcome": "welcome_text", "goodbye": "goodbye_text", "rules": "rules"}
RICH_DEFAULT = {
    "welcome": "{name}, karibu {group}! 👋",
    "goodbye": "{name} ameondoka {group}.",
    "rules": "",
}
RICH_TITLE = {"welcome": "Welcome message", "goodbye": "Goodbye message", "rules": "Regulation"}
RICH_BACK = {"welcome": "welcome", "goodbye": "goodbye", "rules": "rules"}


def rich_spec(chat_id, kind):
    s = group_settings(chat_id)
    r = sp(chat_id)["rich"][kind]
    return {
        "text": s.get(RICH_TEXT_KEY[kind]) or RICH_DEFAULT[kind],
        "media": r.get("media"),
        "buttons": r.get("buttons") or [],
        "html": bool(r.get("html")),
    }


def render_rich_text(template, user, chat, count, is_html):
    if not is_html:
        return esc(render_template(template, user, chat, count))
    values = {
        "name": user.full_name if user else "",
        "username": f"@{user.username}" if user and user.username else "",
        "group": (chat.title or "") if chat else "",
        "id": user.id if user else "",
        "count": count if count is not None else "",
    }
    text = template
    for key, value in values.items():
        text = text.replace("{" + key + "}", html.escape(str(value)))
    return text


def build_buttons(rows):
    kb = []
    for row in rows or []:
        line = []
        for item in row:
            try:
                label, url = item
                line.append(InlineKeyboardButton(label, url=url))
            except Exception:
                continue
        if line:
            kb.append(line)
    return InlineKeyboardMarkup(kb) if kb else None


def parse_buttons(raw):
    """Each line = one row; buttons in a row are separated by ' | '. Format: Label - url"""
    rows = []
    for line in (raw or "").splitlines():
        line = line.strip()
        if not line:
            continue
        row = []
        for part in line.split(" | "):
            if " - " not in part:
                return None
            label, url = part.rsplit(" - ", 1)
            label, url = label.strip(), url.strip()
            if url.startswith("t.me/") or url.startswith("telegram.me/"):
                url = "https://" + url
            if not label or not re.match(r"^(https?://|tg://)\S+$", url, re.I):
                return None
            row.append([label[:60], url])
        if row:
            rows.append(row)
    return rows or None


async def send_rich(context, to_chat_id, group_chat, kind, user, count=None, spec=None):
    spec = spec or rich_spec(group_chat.id, kind)
    text = render_rich_text(spec["text"], user, group_chat, count, spec["html"]) if spec["text"] else ""
    markup = build_buttons(spec["buttons"])
    media = spec["media"]
    try:
        if media and media.get("id"):
            senders = {
                "photo": context.bot.send_photo, "video": context.bot.send_video,
                "animation": context.bot.send_animation, "document": context.bot.send_document,
            }
            sender = senders.get(media.get("type"))
            if sender:
                if text and len(text) <= 1000:
                    return await sender(to_chat_id, media["id"], caption=text,
                                        parse_mode=ParseMode.HTML, reply_markup=markup)
                m = await sender(to_chat_id, media["id"], reply_markup=None if text else markup)
                if text:
                    return await context.bot.send_message(to_chat_id, text, parse_mode=ParseMode.HTML, reply_markup=markup)
                return m
        return await context.bot.send_message(to_chat_id, text or "\u200b", parse_mode=ParseMode.HTML, reply_markup=markup)
    except TelegramError as e:
        logger.warning("send_rich failed (%s); retrying as plain text", e)
        try:
            return await context.bot.send_message(to_chat_id, html.unescape(re.sub(r"<[^>]+>", "", text)) or "\u200b")
        except TelegramError:
            return None


# ---------------------------------------------------------------------
#  Welcome / goodbye
# ---------------------------------------------------------------------
async def send_welcome(context, chat, member, count=None):
    s = group_settings(chat.id)
    p = sp(chat.id)
    if not s.get("welcome"):
        return
    w = p["welcome"]
    if w["mode"] == "first":
        if member.id in w["seen"]:
            return
        w["seen"].append(member.id)
        del w["seen"][:-5000]
    if w["delete_last"] and w.get("last_id"):
        try:
            await context.bot.delete_message(chat.id, w["last_id"])
        except TelegramError:
            pass
        w["last_id"] = 0
    m = await send_rich(context, chat.id, chat, "welcome", member, count)
    if m:
        w["last_id"] = m.message_id
    save_data()


async def send_goodbye(context, chat, member):
    s = group_settings(chat.id)
    p = sp(chat.id)
    if not s.get("goodbye"):
        return
    g = p["goodbye"]
    if g["private"]:
        await send_rich(context, member.id, chat, "goodbye", member)
        return
    if g["delete_last"] and g.get("last_id"):
        try:
            await context.bot.delete_message(chat.id, g["last_id"])
        except TelegramError:
            pass
        g["last_id"] = 0
    m = await send_rich(context, chat.id, chat, "goodbye", member)
    if m:
        g["last_id"] = m.message_id
    save_data()


async def handle_new_members(update, context):
    chat = update.effective_chat
    msg = update.effective_message
    if not is_group(chat):
        return
    s = group_settings(chat.id)
    p = sp(chat.id)
    inviter = msg.from_user
    try:
        count = await context.bot.get_chat_member_count(chat.id)
    except TelegramError:
        count = None
    now = time.time()
    for member in msg.new_chat_members or []:
        remember_user(member)
        if member.id == context.bot.id:
            continue
        JOINED_AT[(chat.id, member.id)] = now
        if inviter and inviter.id != member.id and not member.is_bot:
            added = p["added"]
            added[str(inviter.id)] = int(added.get(str(inviter.id), 0)) + 1

        if member.is_bot:
            if s.get("antibot"):
                try:
                    await context.bot.ban_chat_member(chat.id, member.id)
                except TelegramError:
                    pass
            continue

        invited_by_admin = bool(inviter and inviter.id != member.id and
                                (is_owner_or_sudo(inviter.id) or await is_admin(context, chat.id, inviter.id)))

        # blacklist
        if member.id in p["blocks"]["blacklist"]:
            try:
                await context.bot.ban_chat_member(chat.id, member.id)
                await log_action(context, chat.id, f"⛔ Blacklisted user {mention(member.id, member.full_name)} tried to join and was banned.")
            except TelegramError:
                pass
            continue

        # join block
        if p["blocks"]["join"] and not invited_by_admin:
            try:
                await kick_user(context, chat.id, member.id)
                await log_action(context, chat.id, f"🚪 Join block: {mention(member.id, member.full_name)} removed.")
            except TelegramError:
                pass
            continue

        # multiple joins (raid) block
        if p["blocks"]["multijoin"] and not invited_by_admin:
            dq = JOIN_TRACKER[chat.id]
            dq.append((now, member.id))
            while dq and now - dq[0][0] > 30:
                dq.popleft()
            if len(dq) >= 5:
                victims = list({uid for _, uid in dq})
                dq.clear()
                for uid in victims:
                    try:
                        await kick_user(context, chat.id, uid)
                    except TelegramError:
                        pass
                await notify(context, chat.id, "🛡 <b>Raid protection:</b> many users joined at once and were removed.", temp=30)
                await log_action(context, chat.id, f"🛡 Multiple joins block removed {len(victims)} users.")
                continue

        # checks at the join
        ck = p["checks"]
        if ck["at_join"]:
            bad = name_block_reasons(p, member)
            if bad:
                try:
                    await kick_user(context, chat.id, member.id)
                    await log_action(context, chat.id, f"🔦 {mention(member.id, member.full_name)} removed at join: {esc(bad[0])}.")
                except TelegramError:
                    pass
                continue
            obl = await obligation_reasons(context, chat.id, member)
            if obl:
                lines = "\n".join(f"• {r}" for r in obl)
                await notify(context, chat.id,
                             f"🔦 {mention(member.id, member.full_name)}, to write in this group you must:\n{lines}",
                             temp=30)

        # captcha
        cap = p["captcha"]
        if cap["on"] and not invited_by_admin:
            ok = await start_captcha(context, chat, member, msg.message_id)
            if ok:
                continue

        # welcome
        pw = PRIVATE_WELCOMED.get((chat.id, member.id))
        if pw and now - pw < 300 and p["approval"]["welcome"] == "private":
            continue
        await send_welcome(context, chat, member, count)

    if p["delmsg"]["service_join"]:
        await safe_delete(msg)
    save_data()


async def handle_left_member(update, context):
    chat = update.effective_chat
    msg = update.effective_message
    if not is_group(chat):
        return
    member = msg.left_chat_member
    if not member or member.id == context.bot.id:
        return
    p = sp(chat.id)
    voluntary = bool(msg.from_user and msg.from_user.id == member.id)
    cancel_captcha(context, chat.id, member.id, drop=True)

    if voluntary and not member.is_bot:
        joined = JOINED_AT.pop((chat.id, member.id), None)
        try:
            if p["blocks"]["leave"]:
                await context.bot.ban_chat_member(chat.id, member.id)
                await log_action(context, chat.id, f"🚪 Leave block: {mention(member.id, member.full_name)} banned for leaving.")
            elif p["blocks"]["joinleave"] and joined and time.time() - joined < 120:
                await context.bot.ban_chat_member(chat.id, member.id)
                await log_action(context, chat.id, f"🏃 Join-Leave block: {mention(member.id, member.full_name)} banned.")
        except TelegramError:
            pass

    await send_goodbye(context, chat, member)
    if p["delmsg"]["service_leave"]:
        await safe_delete(msg)


# ---------------------------------------------------------------------
#  Captcha
# ---------------------------------------------------------------------
def cancel_captcha(context, chat_id, user_id, drop=False):
    try:
        for job in context.job_queue.get_jobs_by_name(f"cap:{chat_id}:{user_id}"):
            job.schedule_removal()
    except Exception:
        pass
    if drop:
        sp(chat_id)["captcha"]["pending"].pop(str(user_id), None)


async def start_captcha(context, chat, member, join_msg_id):
    p = sp(chat.id)
    cap = p["captcha"]
    timeout = int(cap["timeout"])
    try:
        await context.bot.restrict_chat_member(chat.id, member.id, permissions=mute_permissions())
    except TelegramError as e:
        logger.warning("Captcha restrict failed: %s", e)
        return False
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("✅ I'm not a robot", callback_data=f"cap|{chat.id}|{member.id}")]])
    m = await notify(
        context, chat.id,
        f"🧠 {mention(member.id, member.full_name)}, press the button below within "
        f"<b>{human_secs(timeout)}</b> to prove you are not a robot.\nYou can't write until you do.",
        markup=kb,
    )
    cap["pending"][str(member.id)] = {
        "msg": m.message_id if m else 0, "join": join_msg_id, "until": time.time() + timeout,
    }
    try:
        context.job_queue.run_once(captcha_timeout, timeout,
                                   data={"chat_id": chat.id, "user_id": member.id},
                                   name=f"cap:{chat.id}:{member.id}")
    except Exception:
        logger.debug("Could not schedule captcha timeout", exc_info=True)
    save_data()
    return True


async def captcha_timeout(context):
    d = context.job.data
    cid, uid = d["chat_id"], d["user_id"]
    p = sp(cid)
    pend = p["captcha"]["pending"].pop(str(uid), None)
    if not pend:
        return
    cap = p["captcha"]
    try:
        if cap["pun"] == "ban":
            await context.bot.ban_chat_member(cid, uid)
        elif cap["pun"] == "mute":
            await mute_user(context, cid, uid, int(p["mute_secs"]))
        else:
            await kick_user(context, cid, uid)
    except TelegramError as e:
        logger.warning("Captcha punishment failed: %s", e)
    for mid in (pend.get("msg"), pend.get("join") if cap["clear"] else None):
        if mid:
            try:
                await context.bot.delete_message(cid, mid)
            except TelegramError:
                pass
    await log_action(context, cid, f"🧠 Captcha failed: {mention(uid)} ({cap['pun']}).")
    save_data()


async def captcha_callback(update, context):
    q = update.callback_query
    try:
        _, cid, uid = q.data.split("|")
        cid, uid = int(cid), int(uid)
    except ValueError:
        await q.answer()
        return
    if q.from_user.id != uid:
        await q.answer("This button is not for you.", show_alert=True)
        return
    p = sp(cid)
    pend = p["captcha"]["pending"].pop(str(uid), None)
    cancel_captcha(context, cid, uid)
    if not pend:
        await q.answer("Expired.", show_alert=True)
        return
    try:
        await context.bot.restrict_chat_member(cid, uid, permissions=open_permissions())
    except TelegramError:
        await q.answer("Could not unmute you — ask an admin.", show_alert=True)
        save_data()
        return
    await q.answer("✅ Verified, welcome!")
    try:
        await q.message.delete()
    except TelegramError:
        pass
    save_data()
    try:
        chat = await context.bot.get_chat(cid)
        try:
            count = await context.bot.get_chat_member_count(cid)
        except TelegramError:
            count = None
        await send_welcome(context, chat, q.from_user, count)
    except TelegramError:
        pass


# ---------------------------------------------------------------------
#  Approval mode (join requests)
# ---------------------------------------------------------------------
async def handle_join_request(update, context):
    req = update.chat_join_request
    if not req:
        return
    chat, user = req.chat, req.from_user
    p = sp(chat.id)
    remember_user(user)
    if user.id in p["blocks"]["blacklist"]:
        try:
            await req.decline()
        except TelegramError:
            pass
        return
    if not p["approval"]["auto"]:
        return
    try:
        await req.approve()
    except TelegramError as e:
        logger.warning("Approve failed: %s", e)
        return
    await log_action(context, chat.id, f"📫 Auto-approved {mention(user.id, user.full_name)}.")
    if p["approval"]["welcome"] == "private" and group_settings(chat.id).get("welcome") and not p["captcha"]["on"]:
        PRIVATE_WELCOMED[(chat.id, user.id)] = time.time()
        target = getattr(req, "user_chat_id", None) or user.id
        await send_rich(context, target, chat, "welcome", user)


# ---------------------------------------------------------------------
#  Command permissions + new commands
# ---------------------------------------------------------------------
async def cmd_allowed(update, context, name):
    chat = update.effective_chat
    user = update.effective_user
    if not is_group(chat):
        return True
    if user.id == OWNER_ID:
        return True
    level = sp(chat.id)["cmdperm"].get(name, "all")
    if level == "nobody":
        return False
    if level == "private":
        return False
    if level == "staff":
        return is_owner_or_sudo(user.id) or await is_admin(context, chat.id, user.id)
    return True


async def rules(update, context):
    track_command(update)
    chat = update.effective_chat
    if not is_group(chat):
        await update.effective_message.reply_text("❌ Group only.")
        return
    if not await cmd_allowed(update, context, "rules"):
        return
    spec = rich_spec(chat.id, "rules")
    s = group_settings(chat.id)
    if not s.get("rules") and not spec["media"]:
        await update.effective_message.reply_text("📜 Hakuna rules zilizowekwa.")
        return
    spec = dict(spec)
    if not s.get("rules"):
        spec["text"] = ""
    elif not spec["html"]:
        spec["text"] = f"📜 <b>GROUP RULES</b>\n\n{esc(spec['text'])}"
        spec["html"] = True
    await send_rich(context, chat.id, chat, "rules", update.effective_user, spec=spec)


async def staff_cmd(update, context):
    track_command(update)
    chat = update.effective_chat
    if not is_group(chat):
        await update.effective_message.reply_text("❌ Group only.")
        return
    if not await cmd_allowed(update, context, "staff"):
        return
    try:
        admins_list = await context.bot.get_chat_administrators(chat.id)
    except TelegramError as e:
        await update.effective_message.reply_text(f"❌ {esc(e)}", parse_mode=ParseMode.HTML)
        return
    owner_line, lines = "", []
    for a in admins_list:
        if a.user.is_bot:
            continue
        line = mention(a.user.id, a.user.full_name)
        status = str(getattr(a.status, "value", a.status))
        if status == "creator" or status == "owner":
            owner_line = f"👑 <b>Founder:</b> {line}"
        else:
            lines.append(f"• {line}")
    text = "👮 <b>STAFF</b>\n\n" + (owner_line + "\n\n" if owner_line else "")
    text += ("🛡 <b>Admins:</b>\n" + "\n".join(lines)) if lines else "🛡 No other admins."
    await update.effective_message.reply_text(text, parse_mode=ParseMode.HTML)


async def me_cmd(update, context):
    track_command(update)
    chat = update.effective_chat
    user = update.effective_user
    if is_group(chat) and not await cmd_allowed(update, context, "me"):
        return
    text = (
        f"👤 <b>{esc(user.full_name)}</b>\n"
        f"🆔 <code>{user.id}</code>\n"
        f"🔗 Username: {('@' + esc(user.username)) if user.username else '—'}\n"
    )
    if is_group(chat):
        s = group_settings(chat.id)
        text += f"⚠️ Warnings: <b>{int(s['warnings'].get(str(user.id), 0))}/{int(s.get('warn_limit', 3))}</b>\n"
        added = int(sp(chat.id)["added"].get(str(user.id), 0))
        text += f"➕ Members added: <b>{added}</b>\n"
        try:
            m = await context.bot.get_chat_member(chat.id, user.id)
            text += f"🎖 Status: <b>{esc(getattr(m.status, 'value', m.status))}</b>"
        except TelegramError:
            pass
    await update.effective_message.reply_text(text, parse_mode=ParseMode.HTML)


def _translate_sync(text, target):
    url = ("https://translate.googleapis.com/translate_a/single?client=gtx&sl=auto&tl="
           + quote(target) + "&dt=t&q=" + quote(text))
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return "".join(part[0] for part in data[0] if part and part[0])


async def translate_cmd(update, context):
    track_command(update)
    chat = update.effective_chat
    if is_group(chat) and not await cmd_allowed(update, context, "translate"):
        return
    msg = update.effective_message
    args = list(context.args or [])
    target = "en"
    if args and re.fullmatch(r"[a-zA-Z]{2}(-[a-zA-Z]{2})?", args[0]):
        target = args.pop(0).lower()
    text = " ".join(args).strip()
    if not text and msg.reply_to_message:
        text = msg_text(msg.reply_to_message).strip()
    if not text:
        await msg.reply_text("🌍 Tumia: <code>/translate sw Hello</code> au reply ujumbe: <code>/translate en</code>", parse_mode=ParseMode.HTML)
        return
    try:
        out = await asyncio.get_running_loop().run_in_executor(None, _translate_sync, text[:1500], target)
    except Exception as e:
        logger.warning("Translate failed: %s", e)
        await msg.reply_text("❌ Translate imeshindikana (angalia internet ya server).")
        return
    await msg.reply_text(f"🌍 <b>{esc(target.upper())}</b>\n{esc(out)}", parse_mode=ParseMode.HTML)


async def link_cmd(update, context):
    track_command(update)
    chat = update.effective_chat
    if not is_group(chat):
        await update.effective_message.reply_text("❌ Group only.")
        return
    if not await cmd_allowed(update, context, "link"):
        return
    p = sp(chat.id)
    link = f"https://t.me/{chat.username}" if chat.username else p.get("invite_link", "")
    if not link:
        try:
            info = await context.bot.get_chat(chat.id)
            link = getattr(info, "invite_link", None) or ""
            if not link:
                created = await context.bot.create_chat_invite_link(chat.id, name=f"{BOT_NAME} link")
                link = created.invite_link
            p["invite_link"] = link
            save_data()
        except TelegramError:
            await update.effective_message.reply_text("❌ Nahitaji admin permission ya 'Invite users' ili kutengeneza link.")
            return
    await update.effective_message.reply_text(f"🔗 <b>{esc(chat.title)}</b>\n{esc(link)}", parse_mode=ParseMode.HTML)


# ---------------------------------------------------------------------
#  @admin / report
# ---------------------------------------------------------------------
def message_link(chat, message_id):
    if chat.username:
        return f"https://t.me/{chat.username}/{message_id}"
    cid = str(chat.id)
    if cid.startswith("-100"):
        return f"https://t.me/c/{cid[4:]}/{message_id}"
    return ""


async def do_report(update, context):
    chat = update.effective_chat
    user = update.effective_user
    msg = update.effective_message
    if not is_group(chat):
        return
    p = sp(chat.id)
    rp = p["report"]
    if rp["mode"] == "nobody" and not rp["tag_founder"] and not rp["tag_admins"]:
        return
    if is_owner_or_sudo(user.id) or await is_admin(context, chat.id, user.id):
        return
    key = (chat.id, user.id)
    if time.time() - REPORT_COOLDOWN.get(key, 0) < 60:
        return
    REPORT_COOLDOWN[key] = time.time()

    target_msg = msg.reply_to_message or msg
    link = message_link(chat, target_msg.message_id)
    reported = target_msg.from_user
    body = (
        f"🆘 <b>REPORT</b> — {esc(chat.title)}\n"
        f"👤 From: {mention(user.id, user.full_name)}\n"
        + (f"🎯 Reported: {mention(reported.id, reported.full_name)}\n" if reported and reported.id != user.id else "")
        + (f"🔗 <a href=\"{esc(link)}\">Go to message</a>\n" if link else "")
    )
    reason = msg_text(msg).strip()
    if reason:
        body += f"💬 {esc(reason[:300])}"

    try:
        admins_list = await context.bot.get_chat_administrators(chat.id)
    except TelegramError:
        admins_list = []
    founder = next((a.user for a in admins_list
                    if str(getattr(a.status, "value", a.status)) in ("creator", "owner")), None)

    delivered = False
    if rp["mode"] == "founder" and founder:
        try:
            await context.bot.send_message(founder.id, body, parse_mode=ParseMode.HTML)
            delivered = True
        except TelegramError:
            delivered = False
    elif rp["mode"] == "staff" and rp["staff_chat"]:
        try:
            await context.bot.send_message(int(rp["staff_chat"]), body, parse_mode=ParseMode.HTML)
            delivered = True
        except TelegramError:
            delivered = False

    tags = []
    if rp["tag_founder"] and founder:
        tags.append(mention(founder.id, founder.full_name))
    if rp["tag_admins"]:
        tags += [mention(a.user.id, a.user.full_name) for a in admins_list if not a.user.is_bot][:10]
    if tags:
        await notify(context, chat.id, "🔔 " + " ".join(dict.fromkeys(tags)) + "\n🆘 A user needs staff attention.", temp=120)
    elif delivered:
        await notify(context, chat.id, "✅ Your report was sent to the staff.", temp=15)
    elif rp["mode"] != "nobody":
        await notify(context, chat.id, "⚠️ Report could not be delivered (staff must start the bot in private).", temp=15)


async def report_cmd(update, context):
    track_command(update)
    await do_report(update, context)


# ---------------------------------------------------------------------
#  Blacklist commands
# ---------------------------------------------------------------------
async def blacklist_cmd(update, context):
    track_command(update)
    if not await require_right(update, context, "can_restrict_members"):
        return
    target = await target_from_update(update, context)
    if await protected_target(update, context, target):
        return
    bl = sp(update.effective_chat.id)["blocks"]["blacklist"]
    if target.id not in bl:
        bl.append(target.id)
    try:
        await context.bot.ban_chat_member(update.effective_chat.id, target.id)
    except TelegramError:
        pass
    save_data()
    await update.effective_message.reply_text(f"⛔ {mention(target.id, target.full_name)} added to blacklist and banned.", parse_mode=ParseMode.HTML)


async def unblacklist_cmd(update, context):
    track_command(update)
    if not await require_right(update, context, "can_restrict_members"):
        return
    target = await target_from_update(update, context)
    if not target:
        await update.effective_message.reply_text("❌ Reply ujumbe wa mtu au weka user ID.")
        return
    bl = sp(update.effective_chat.id)["blocks"]["blacklist"]
    if target.id in bl:
        bl.remove(target.id)
    try:
        await context.bot.unban_chat_member(update.effective_chat.id, target.id, only_if_banned=True)
    except TelegramError:
        pass
    save_data()
    await update.effective_message.reply_text(f"✅ {mention(target.id, target.full_name)} removed from blacklist.", parse_mode=ParseMode.HTML)


async def cancel_cmd(update, context):
    msg = update.effective_message
    key = (update.effective_chat.id, update.effective_user.id)
    pend = PENDING.pop(key, None)
    RC_DRAFT.pop((pend["cid"], update.effective_user.id), None) if pend else None
    await msg.reply_text("✅ Cancelled." if pend else "Hakuna kitu cha kufuta.")
    if pend and pend.get("prompt_msg"):
        try:
            await context.bot.delete_message(key[0], pend["prompt_msg"])
        except TelegramError:
            pass

# =====================================================================
#  SETTINGS PANEL (inline menus)
# =====================================================================
def cbd(cid, *parts):
    return "sp|" + str(cid) + "|" + "|".join(str(x) for x in parts)


def btn(cid, label, *parts):
    return InlineKeyboardButton(label, callback_data=cbd(cid, *parts))


def nav(cid, label, page):
    return btn(cid, label, "pg", page)


def back_row(cid, page="main"):
    return [nav(cid, "🔙 Back", page)]


def _root_for(cid, path):
    if path.startswith("g."):
        return group_settings(cid), path[2:]
    return sp(cid), path


def path_get(cid, path):
    root, pth = _root_for(cid, path)
    cur = root
    for part in pth.split("."):
        if not isinstance(cur, dict) or part not in cur:
            raise KeyError(path)
        cur = cur[part]
    return cur


def path_set(cid, path, value):
    root, pth = _root_for(cid, path)
    parts = pth.split(".")
    cur = root
    for part in parts[:-1]:
        if not isinstance(cur, dict) or part not in cur:
            raise KeyError(path)
        cur = cur[part]
    if not isinstance(cur, dict) or parts[-1] not in cur:
        raise KeyError(path)
    if isinstance(cur[parts[-1]], (dict, list)):
        raise KeyError(path)
    cur[parts[-1]] = value


ST_ALLOWED = {
    "welcome.mode": {"always", "first"},
    "warn_pun": {"off", "kick", "mute", "ban"},
    "mute_secs": {"900", "3600", "21600", "86400", "604800"},
    "g.warn_limit": {"2", "3", "4", "5", "6"},
    "captcha.pun": {"kick", "ban", "mute"},
    "captcha.timeout": {"60", "120", "300", "600"},
    "approval.welcome": {"group", "private"},
    "report.mode": {"nobody", "founder", "staff"},
    "delmsg.scheduled": {"0", "60", "300", "1800", "3600", "21600", "86400"},
    "delmsg.selfdestruct": {"0", "10", "30", "60", "300", "1800"},
    "length.max": {"0", "100", "300", "500", "1000", "2000"},
}
for _c in CMDPERM_COMMANDS:
    ST_ALLOWED[f"cmdperm.{_c}"] = set(CMDPERM_LEVELS)

ADJ_ALLOWED = {
    # path: (min, max, wrap)
    "flood.msgs": (2, 30, False),
    "flood.secs": (1, 60, False),
    "night.start": (0, 23, True),
    "night.end": (0, 23, True),
    "night.tz": (-12, 14, False),
    "checks.add_count": (1, 50, False),
}

PUN_PATHS = {"flood", "tg_links", "forward", "quote", "total_links", "words", "length"} | {f"alpha.{k}" for k, _, _ in ALPHABETS}


def pun_rows(cid, path, page):
    cfg = path_get(cid, path)
    cur = cfg.get("pun", "off")

    def pb(code, label):
        return btn(cid, ("✔ " if cur == code else "") + label, "pn", path, code, page)

    return [
        [pb("off", "✖ Off"), pb("warn", "❕ Warn"), pb("kick", "❗ Kick")],
        [pb("mute", "🔇 Mute"), pb("ban", "🚷 Ban")],
        [btn(cid, f"🗑 Delete Messages {'✔' if cfg.get('del') else '✖'}", "tg", path + ".del", page)],
    ]


def group_title(cid):
    return esc(group_settings(cid).get("title") or str(cid))


# ---------------------------------------------------------------------
#  Pages (each returns (text, markup))
# ---------------------------------------------------------------------
async def pg_main(context, cid, arg):
    text = (
        f"⚙️ <b>SETTINGS</b>\n<b>Group:</b> <code>{group_title(cid)}</code>\n\n"
        "<i>Select one of the settings that you want to change.</i>"
    )
    kb = [
        [nav(cid, "💬 Welcome", "welcome"), nav(cid, "👋 Goodbye", "goodbye")],
        [nav(cid, "🕉 Alphabets", "alpha"), nav(cid, "🗣 Anti-Flood", "flood")],
        [nav(cid, "📨 Anti-Spam", "spam"), nav(cid, "📜 Rules", "rules")],
        [nav(cid, "🧠 Captcha", "captcha"), nav(cid, "🔦 Checks", "checks")],
        [nav(cid, "🆘 @Admin", "admin"), nav(cid, "🔐 Blocks", "blocks")],
        [nav(cid, "📸 Media", "media"), nav(cid, "❗ Warns", "warns")],
        [nav(cid, "🌘 Night", "night"), nav(cid, "📫 Approval mode", "approval")],
        [nav(cid, "🗑 Deleting Messages", "delmsg")],
        [btn(cid, "✅ Close", "close"), nav(cid, "▶️ Other", "other")],
    ]
    return text, InlineKeyboardMarkup(kb)


async def pg_other(context, cid, arg):
    text = f"⚙️ <b>SETTINGS</b> — more\n<b>Group:</b> <code>{group_title(cid)}</code>\n\n<i>Select one of the settings that you want to change.</i>"
    kb = [
        [nav(cid, "🔤 Banned Words", "words")],
        [nav(cid, "🕒 Recurring messages", "recurring")],
        [nav(cid, "📏 Message length", "length")],
        [nav(cid, "🔑 Permissions", "perms"), nav(cid, "🔍 Log Channel", "log")],
        [nav(cid, "🤖 Bot commands menu", "botmenu")],
        [nav(cid, "🔙 Back", "main"), btn(cid, "✅ Close", "close")],
    ]
    return text, InlineKeyboardMarkup(kb)


async def pg_botmenu(context, cid, arg):
    text = f"╭━━━〔 🔥 <b>{esc(BOT_NAME)}</b> 〕━━━╮\n┃ 👑 Owner: <b>{esc(OWNER_NAME)}</b>\n┃ ⚡ Prefix: <code>/</code>\n╰━━━━━━━━━━━━━━━━━━━━╯\n\nChagua category hapa chini:"
    return text, main_menu()


async def pg_welcome(context, cid, arg):
    s = group_settings(cid)
    w = sp(cid)["welcome"]
    on = bool(s["welcome"])
    mode = ("Send the welcome message at every join of the users in the group"
            if w["mode"] == "always" else "Send the welcome message only at the first join of each user")
    text = (
        "💬 <b>Welcome Message</b>\n"
        "From this menu you can set a welcome message that will be sent when someone joins the group.\n\n"
        f"<b>Status:</b> {'Active ✅' if on else 'Off ❌'}\n<b>Mode:</b> {mode}\n"
        "<i>Placeholders: {name} {username} {group} {id} {count}</i>"
    )
    kb = [
        [btn(cid, "✖ Turn off", "sb", "g.welcome", 0, "welcome"), btn(cid, "✔ Turn on", "sb", "g.welcome", 1, "welcome")],
        [nav(cid, "✍️ Customize message", "rich:welcome")],
        [btn(cid, ("✔ " if w["mode"] == "always" else "") + "🔔 Always send", "st", "welcome.mode", "always", "welcome"),
         btn(cid, ("✔ " if w["mode"] == "first" else "") + "1️⃣ Send 1st join", "st", "welcome.mode", "first", "welcome")],
        [btn(cid, f"♻️ Delete last message {'✔' if w['delete_last'] else '✖'}", "tg", "welcome.delete_last", "welcome")],
        back_row(cid),
    ]
    return text, InlineKeyboardMarkup(kb)


async def pg_goodbye(context, cid, arg):
    s = group_settings(cid)
    g = sp(cid)["goodbye"]
    on = bool(s["goodbye"])
    text = (
        "👋 <b>Goodbye</b>\n"
        "From this menu you can set a goodbye message that will be sent when someone leaves the group.\n\n"
        f"<b>Status:</b> {'Active ✅' if on else 'Off ❌'}"
    )
    kb = [
        [btn(cid, "✖ Turn off", "sb", "g.goodbye", 0, "goodbye"), btn(cid, "✔ Turn on", "sb", "g.goodbye", 1, "goodbye")],
        [nav(cid, "✍️ Customize message", "rich:goodbye")],
        [btn(cid, f"💌 Send in private chat {'✔' if g['private'] else '✖'}", "tg", "goodbye.private", "goodbye")],
        [btn(cid, f"♻️ Delete last message {'✔' if g['delete_last'] else '✖'}", "tg", "goodbye.delete_last", "goodbye")],
        back_row(cid),
    ]
    return text, InlineKeyboardMarkup(kb)


async def pg_rich(context, cid, kind):
    if kind not in RICH_TEXT_KEY:
        kind = "rules"
    s = group_settings(cid)
    r = sp(cid)["rich"][kind]
    has_text = bool(s.get(RICH_TEXT_KEY[kind]))
    text = (
        f"📜 <b>{RICH_TITLE[kind]}</b>\n\n"
        f"📄 Text {onoff(has_text)}\n"
        f"📸 Media {onoff(bool(r.get('media')))}\n"
        f"🔤 Buttons {onoff(bool(r.get('buttons')))}\n\n"
        "👉 Use the buttons below to choose what you want to set."
    )
    kb = [
        [btn(cid, "📄 Text", "inp", "rich_text", kind, f"rich:{kind}"), btn(cid, "👀 See", "see", kind, "text")],
        [btn(cid, "📸 Media", "inp", "rich_media", kind, f"rich:{kind}"), btn(cid, "👀 See", "see", kind, "media"),
         btn(cid, "🗑", "rm", kind, "media", f"rich:{kind}")],
        [btn(cid, "🔤 Buttons", "inp", "rich_buttons", kind, f"rich:{kind}"), btn(cid, "👀 See", "see", kind, "buttons"),
         btn(cid, "🗑", "rm", kind, "buttons", f"rich:{kind}")],
        [btn(cid, "👀 Full preview", "see", kind, "full")],
        back_row(cid, RICH_BACK[kind]),
    ]
    return text, InlineKeyboardMarkup(kb)


async def pg_rules(context, cid, arg):
    text = (
        "📜 <b>Group's regulations</b>\n"
        "From this menu you can manage the group's regulations, that will be shown with the command /rules.\n\n"
        "<i>To edit who can use the /rules command, go to the \"Commands permissions\" section.</i>"
    )
    kb = [
        [nav(cid, "✍️ Customize message", "rich:rules")],
        [nav(cid, "🕹 Commands Permissions", "cmdperm")],
        back_row(cid),
    ]
    return text, InlineKeyboardMarkup(kb)


async def pg_cmdperm(context, cid, arg):
    perms = sp(cid)["cmdperm"]
    icon = {"nobody": "✖", "staff": "👮", "all": "👥", "private": "🤖"}
    word = {"nobody": "Nobody", "staff": "Staff", "all": "Everyone", "private": "Private"}
    lines = "\n".join(f"• <code>/{c}</code> » {icon[perms[c]]} {word[perms[c]]}" for c in CMDPERM_COMMANDS)
    text = (
        "🕹 <b>Commands Permissions</b>\n"
        "From this menu you can configure the usage permissions of the following commands.\n\n"
        "✖ = nobody  |  👥 = all\n🤖 = all, in private chat\n👮 = admins and moderators\n\n" + lines
    )
    kb = []
    for c in CMDPERM_COMMANDS:
        row = [btn(cid, f"/{c}", "noop")]
        for lvl in CMDPERM_LEVELS:
            label = icon[lvl] + (" ✅" if perms[c] == lvl else "")
            row.append(btn(cid, label, "st", f"cmdperm.{c}", lvl, "cmdperm"))
        kb.append(row)
    kb.append(back_row(cid, "rules"))
    return text, InlineKeyboardMarkup(kb)


async def pg_alpha(context, cid, arg):
    p = sp(cid)
    lines = []
    for key, icon, label in ALPHABETS:
        lines.append(f"{icon} <b>{label}</b>\n└ Status: {pun_label(p['alpha'][key])}")
    text = (
        "🕉 <b>Alphabets</b>\nSelect punishment for any user who sends messages written in certain alphabets.\n\n"
        + "\n\n".join(lines)
        + "\n\n<i>Non-Latin alphabets trigger on any letter of that alphabet; Latin triggers when at least half of the letters are Latin.</i>"
    )
    kb, row = [], []
    for key, icon, label in ALPHABETS:
        lab = f"{icon} {label.upper()}"
        if arg == key:
            lab = f"» {lab} «"
        row.append(nav(cid, lab, f"alpha:{key}"))
        if len(row) == 2:
            kb.append(row)
            row = []
    if row:
        kb.append(row)
    if arg in p["alpha"]:
        kb.append([btn(cid, "┈┈┈┈┈┈┈┈┈", "noop")])
        kb += pun_rows(cid, f"alpha.{arg}", f"alpha:{arg}")
    kb.append(back_row(cid))
    return text, InlineKeyboardMarkup(kb)


async def pg_flood(context, cid, arg):
    fl = sp(cid)["flood"]
    text = (
        "🗣 <b>Antiflood</b>\n"
        "From this menu you can set a punishment for those who send many messages in a short time.\n\n"
        f"Currently the antiflood is triggered when <b>{fl['msgs']}</b> messages are sent within <b>{fl['secs']}</b> seconds.\n\n"
        f"<b>Punishment:</b> {pun_label(fl)}"
    )
    kb = [
        [btn(cid, "➖", "adj", "flood.msgs", -1, "flood"), btn(cid, f"📄 Messages: {fl['msgs']}", "noop"),
         btn(cid, "➕", "adj", "flood.msgs", 1, "flood")],
        [btn(cid, "➖", "adj", "flood.secs", -1, "flood"), btn(cid, f"🕒 Time: {fl['secs']}s", "noop"),
         btn(cid, "➕", "adj", "flood.secs", 1, "flood")],
    ] + pun_rows(cid, "flood", "flood") + [back_row(cid)]
    return text, InlineKeyboardMarkup(kb)


PUN_INFO = {
    "tg_links": ("📘 Telegram links", "Punishment for users who send Telegram links (t.me, telegram.me, tg://)."),
    "forward": ("📩 Forwarding", "Punishment for users who forward messages from other chats."),
    "quote": ("💭 Quote", "Punishment for users who quote text from other messages or chats."),
    "total_links": ("🔗 Total links block", "Punishment for users who send ANY link."),
}


async def pg_spam(context, cid, arg):
    p = sp(cid)
    text = (
        "📨 <b>Anti-Spam</b>\n"
        "In this menu you can decide whether to protect your groups from unnecessary links, forwards, and quotes.\n\n"
        + "\n".join(f"{PUN_INFO[k][0]}: <b>{pun_label(p[k])}</b>" for k in ("tg_links", "forward", "quote", "total_links"))
    )
    kb = [
        [nav(cid, "📘 Telegram links", "pun:tg_links")],
        [nav(cid, "📩 Forwarding", "pun:forward"), nav(cid, "💭 Quote", "pun:quote")],
        [nav(cid, "🔗 Total links block", "pun:total_links")],
        back_row(cid),
    ]
    return text, InlineKeyboardMarkup(kb)


async def pg_pun(context, cid, arg):
    if arg not in PUN_INFO:
        return await pg_spam(context, cid, "")
    title, desc = PUN_INFO[arg]
    cfg = sp(cid)[arg]
    text = f"{title}\n{desc}\n\n<b>Punishment:</b> {pun_label(cfg)}"
    kb = pun_rows(cid, arg, f"pun:{arg}") + [back_row(cid, "spam")]
    return text, InlineKeyboardMarkup(kb)


async def pg_media(context, cid, arg):
    m = sp(cid)["media"]
    lines = "\n".join(f"{icon} {label} = {MEDIA_CODE_LABEL[m[k]]}" for k, icon, label in MEDIA_TYPES)
    text = (
        "📸 <b>Media Block</b>\n\n"
        "❕ = Warn | ❗ = Kick\n🔇 = Mute | 🚷 = Ban\n🗑 = Deletion\n✅ = Off\n"
        "<i>Warn/Kick/Mute/Ban also delete the message.</i>\n"
        "───────────────\n" + lines
    )
    kb = []
    for k, icon, label in MEDIA_TYPES:
        row = [btn(cid, icon, "mdi", k)]
        for code in ("off", "warn", "kick", "mute", "ban", "del"):
            ic = MEDIA_CODE_ICON[code]
            row.append(btn(cid, f"[{ic}]" if m[k] == code else ic, "md", k, code))
        kb.append(row)
    kb.append(back_row(cid))
    return text, InlineKeyboardMarkup(kb)


async def pg_warns(context, cid, arg):
    s = group_settings(cid)
    p = sp(cid)
    pun = p["warn_pun"]
    limit = int(s.get("warn_limit", 3))
    text = (
        "❗ <b>User warnings</b>\n"
        "The warning system allows you to give warnings to users for incorrect behavior in the group, before actually punishing them.\n\n"
        "From this menu you can set:\n"
        "• the punishment for users who exceed the maximum of warnings allowed\n"
        "• the maximum number of warns allowed\n\n"
        f"<b>Punishment:</b> {PUN_NAMES.get(pun, pun)}\n<b>Max Warns allowed:</b> {limit}\n"
        f"<b>Mute duration:</b> {human_secs(p['mute_secs'])}"
    )

    def pb(code, label):
        return btn(cid, ("✔ " if pun == code else "") + label, "st", "warn_pun", code, "warns")

    kb = [
        [nav(cid, "📃 Warned List", "warned")],
        [pb("off", "✖ Off"), pb("kick", "❗ Kick")],
        [pb("mute", "🔇 Mute"), pb("ban", "🚷 Ban")],
        [btn(cid, "🔇⏱ Set mute duration", "noop")],
        [btn(cid, ("✅ " if int(p["mute_secs"]) == v else "") + lab, "st", "mute_secs", v, "warns")
         for v, lab in ((900, "15m"), (3600, "1h"), (21600, "6h"), (86400, "1d"), (604800, "7d"))],
        [btn(cid, f"{n}✅" if limit == n else str(n), "st", "g.warn_limit", n, "warns") for n in (2, 3, 4, 5, 6)],
        back_row(cid),
    ]
    return text, InlineKeyboardMarkup(kb)


async def pg_warned(context, cid, arg):
    s = group_settings(cid)
    limit = int(s.get("warn_limit", 3))
    items = [(u, c) for u, c in s["warnings"].items() if int(c) > 0][:40]
    body = "\n".join(f"• {mention(u)} — {c}/{limit}" for u, c in items) if items else "No warned users."
    text = f"📃 <b>Warned List</b>\n\n{body}"
    kb = [[btn(cid, "🧹 Reset all warnings", "wl_reset")], back_row(cid, "warns")]
    return text, InlineKeyboardMarkup(kb)


async def pg_night(context, cid, arg):
    n = sp(cid)["night"]
    now = local_now(n["tz"])
    actions = []
    if n["silence"]:
        actions.append("🤫 Global Silence")
    if n["media"]:
        actions.append("📸 Delete medias")
    status = ("Off ❌" if not n["on"] else (" + ".join(actions) if actions else "No action selected"))
    text = (
        "🌘 <b>Night mode</b>\nSelect the actions you want to limit every night.\n\n"
        f"<b>Status:</b> {status}\n"
        f"├ Active from hour <b>{n['start']}</b> to <b>{n['end']}</b>\n"
        f"└ Start&amp;End advises: {onoff(n['advise'])}\n\n"
        f"<b>Current time:</b> {now.day} {now.strftime('%b %Y, %H:%M')} (UTC{n['tz']:+d})"
    )
    kb = [
        [btn(cid, "❌ Turn off" if n["on"] else "✅ Turn on", "tg", "night.on", "night")],
        [btn(cid, f"📸 Delete medias {'✔' if n['media'] else '✖'}", "tg", "night.media", "night"),
         btn(cid, f"🤫 Global Silence {'✔' if n['silence'] else '✖'}", "tg", "night.silence", "night")],
        [nav(cid, "⏱ Set time slot", "nightslot")],
        [btn(cid, f"📣 Start&End advises {'✔' if n['advise'] else '✖'}", "tg", "night.advise", "night")],
        [nav(cid, "🔙 Back", "main"), nav(cid, "🌍 Time Zone", "nighttz")],
    ]
    return text, InlineKeyboardMarkup(kb)


async def pg_nightslot(context, cid, arg):
    n = sp(cid)["night"]
    text = f"⏱ <b>Time slot</b>\n\nNight mode is active from hour <b>{n['start']}</b> to <b>{n['end']}</b> (24h clock, your group's time zone UTC{n['tz']:+d})."
    kb = [
        [btn(cid, "➖", "adj", "night.start", -1, "nightslot"), btn(cid, f"🌘 Start: {n['start']}:00", "noop"),
         btn(cid, "➕", "adj", "night.start", 1, "nightslot")],
        [btn(cid, "➖", "adj", "night.end", -1, "nightslot"), btn(cid, f"🌅 End: {n['end']}:00", "noop"),
         btn(cid, "➕", "adj", "night.end", 1, "nightslot")],
        back_row(cid, "night"),
    ]
    return text, InlineKeyboardMarkup(kb)


async def pg_nighttz(context, cid, arg):
    n = sp(cid)["night"]
    now = local_now(n["tz"])
    text = f"🌍 <b>Time Zone</b>\n\nCurrent offset: <b>UTC{n['tz']:+d}</b>\nLocal time now: <b>{now.strftime('%H:%M')}</b>\n\n<i>Tanzania/Kenya/Uganda = UTC+3</i>"
    kb = [
        [btn(cid, "➖", "adj", "night.tz", -1, "nighttz"), btn(cid, f"UTC{n['tz']:+d}", "noop"),
         btn(cid, "➕", "adj", "night.tz", 1, "nighttz")],
        back_row(cid, "night"),
    ]
    return text, InlineKeyboardMarkup(kb)


async def pg_checks(context, cid, arg):
    ck = sp(cid)["checks"]

    def st(v):
        return "On" if v else "Off"

    text = (
        "🔦 <b>Checks</b>\n\n<b>OBLIGATION OF...</b>\n"
        f" • Surname: {st(ck['surname'])}\n • Username: {st(ck['username'])}\n • Profile picture: {st(ck['photo'])}\n"
        f" • Channel obligation: {st(ck['channel'])}\n • Obligation to add: {st(ck['add'])}\n\n"
        "<b>BLOCK...</b>\n"
        f" • Arabic name: {st(ck['n_arabic'])}\n • Chinese name: {st(ck['n_chinese'])}\n"
        f" • Russian name: {st(ck['n_russian'])}\n • Spam name: {st(ck['n_spam'])}\n\n"
        "🚪 <b>Check at the join</b>\nIf active, the bot will check for obligations and blocks even when users join the group, as well as when sending a message.\n"
        f"<b>Status:</b> {'Active ✔' if ck['at_join'] else 'Off ✖'}\n\n"
        "🗑 <b>Delete Messages</b>\nIf active, the bot will delete messages sent by users who do not comply with the obligations/blocks.\n"
        f"<b>Status:</b> {'Active ✔' if ck['delete'] else 'Off ✖'}"
    )
    kb = [
        [nav(cid, "OBLIGATIONS", "chk_obl"), nav(cid, "NAME BLOCKS", "chk_names")],
        [btn(cid, f"🚪 Check at the join {'✔' if ck['at_join'] else '✖'}", "tg", "checks.at_join", "checks")],
        [btn(cid, f"🗑 Delete Messages {'✔' if ck['delete'] else '✖'}", "tg", "checks.delete", "checks")],
        back_row(cid),
    ]
    return text, InlineKeyboardMarkup(kb)


async def pg_chk_obl(context, cid, arg):
    ck = sp(cid)["checks"]
    text = (
        "🔦 <b>Obligations</b>\nUsers must satisfy the enabled obligations before they can write.\n\n"
        f"• Channel: <code>{esc(ck['channel_name'] or 'not set')}</code> (bot must be admin there)\n"
        f"• Members to add: <b>{ck['add_count']}</b> (counted from now on)"
    )
    kb = [
        [btn(cid, f"Surname {onoff(ck['surname'])}", "tg", "checks.surname", "chk_obl"),
         btn(cid, f"Username {onoff(ck['username'])}", "tg", "checks.username", "chk_obl")],
        [btn(cid, f"Profile picture {onoff(ck['photo'])}", "tg", "checks.photo", "chk_obl")],
        [btn(cid, f"📢 Channel obligation {onoff(ck['channel'])}", "tg", "checks.channel", "chk_obl")],
        [btn(cid, "✍️ Set channel (@name)", "inp", "chk_channel", "x", "chk_obl")],
        [btn(cid, f"➕ Obligation to add {onoff(ck['add'])}", "tg", "checks.add", "chk_obl")],
        [btn(cid, "➖", "adj", "checks.add_count", -1, "chk_obl"), btn(cid, f"{ck['add_count']} member(s)", "noop"),
         btn(cid, "➕", "adj", "checks.add_count", 1, "chk_obl")],
        back_row(cid, "checks"),
    ]
    return text, InlineKeyboardMarkup(kb)


async def pg_chk_names(context, cid, arg):
    ck = sp(cid)["checks"]
    text = "🔦 <b>Name blocks</b>\nBlock users whose display name contains the selected alphabets or looks like spam (links, @handles, domains)."
    kb = [
        [btn(cid, f"☪️ Arabic name block {onoff(ck['n_arabic'])}", "tg", "checks.n_arabic", "chk_names")],
        [btn(cid, f"🇨🇳 Chinese name block {onoff(ck['n_chinese'])}", "tg", "checks.n_chinese", "chk_names")],
        [btn(cid, f"🇷🇺 Russian name block {onoff(ck['n_russian'])}", "tg", "checks.n_russian", "chk_names")],
        [btn(cid, f"📩 Spam name block {onoff(ck['n_spam'])}", "tg", "checks.n_spam", "chk_names")],
        back_row(cid, "checks"),
    ]
    return text, InlineKeyboardMarkup(kb)


async def pg_blocks(context, cid, arg):
    b = sp(cid)["blocks"]
    s = group_settings(cid)
    text = (
        "🔐 <b>Blocks</b>\n\n"
        f"📛 Blacklist: <b>{len(b['blacklist'])}</b> user(s) — banned on sight\n"
        f"👦 Join block {onoff(b['join'])} — new members are removed (admins can still add people)\n"
        f"🚪 Leave block {onoff(b['leave'])} — users who leave by themselves are banned\n"
        f"🏃 Join-Leave block {onoff(b['joinleave'])} — users who leave within 2 minutes of joining are banned\n"
        f"👨‍👩‍👧 Multiple joins block {onoff(b['multijoin'])} — 5+ joins within 30s are removed (raid protection)\n"
        f"🤖 Block adding bots {onoff(s['antibot'])} — bots that get added are banned"
    )
    kb = [
        [nav(cid, "📛 Blacklist", "bl")],
        [btn(cid, f"👦 Join block {onoff(b['join'])}", "tg", "blocks.join", "blocks")],
        [btn(cid, f"🚪 Leave block {onoff(b['leave'])}", "tg", "blocks.leave", "blocks")],
        [btn(cid, f"🏃 Join-Leave block {onoff(b['joinleave'])}", "tg", "blocks.joinleave", "blocks")],
        [btn(cid, f"👨‍👩‍👧 Multiple joins block {onoff(b['multijoin'])}", "tg", "blocks.multijoin", "blocks")],
        [btn(cid, f"🤖 Block adding bots {onoff(s['antibot'])}", "tg", "g.antibot", "blocks")],
        back_row(cid),
    ]
    return text, InlineKeyboardMarkup(kb)


async def pg_bl(context, cid, arg):
    bl = sp(cid)["blocks"]["blacklist"]
    body = "\n".join(f"• {mention(u)} (<code>{u}</code>)" for u in bl[:30]) if bl else "Blacklist is empty."
    if len(bl) > 30:
        body += f"\n… and {len(bl) - 30} more"
    text = f"📛 <b>Blacklist</b>\nBlacklisted users are banned when they join or write.\n\n{body}\n\n<i>Also: /blacklist and /unblacklist (reply or user ID).</i>"
    kb = [
        [btn(cid, "➕ Add", "inp", "bl_add", "x", "bl"), btn(cid, "➖ Remove", "inp", "bl_del", "x", "bl")],
        [btn(cid, "🗑 Clear all", "bl_clear")],
        back_row(cid, "blocks"),
    ]
    return text, InlineKeyboardMarkup(kb)


async def pg_captcha(context, cid, arg):
    c = sp(cid)["captcha"]
    text = (
        "🧠 <b>Captcha</b>\n"
        "By activating the captcha, when a user enters the group <b>he will not be able to send messages</b> until he has confirmed that he is <b>not a robot</b>.\n\n"
        "🕒 You can also decide to set a <b>PUNISHMENT</b> for those who will not resolve the captcha within the desired time and whether or not to clear the service message in case of failure.\n\n"
        f"<b>Status:</b> {'Active ✅' if c['on'] else 'Off ❌'}"
    )
    if not c["on"]:
        kb = [[btn(cid, "✅ Activate", "sb", "captcha.on", 1, "captcha")], back_row(cid)]
        return text, InlineKeyboardMarkup(kb)
    text += f"\n<b>Punishment:</b> {PUN_NAMES.get(c['pun'], c['pun'])}\n<b>Time limit:</b> {human_secs(c['timeout'])}"

    def pb(code, label):
        return btn(cid, ("✔ " if c["pun"] == code else "") + label, "st", "captcha.pun", code, "captcha")

    kb = [
        [btn(cid, "❌ Deactivate", "sb", "captcha.on", 0, "captcha")],
        [pb("kick", "❗ Kick"), pb("mute", "🔇 Mute"), pb("ban", "🚷 Ban")],
        [btn(cid, ("✅ " if int(c["timeout"]) == v else "") + lab, "st", "captcha.timeout", v, "captcha")
         for v, lab in ((60, "1m"), (120, "2m"), (300, "5m"), (600, "10m"))],
        [btn(cid, f"🧹 Clear service message {'✔' if c['clear'] else '✖'}", "tg", "captcha.clear", "captcha")],
        back_row(cid),
    ]
    return text, InlineKeyboardMarkup(kb)


async def pg_approval(context, cid, arg):
    a = sp(cid)["approval"]
    text = (
        "📫 <b>Approval mode</b>\n"
        "Through this menu you can decide to delegate the management of group approvals to the bot, for users who ask to enter via link with approval.\n\n"
        "🧠 Since the Captcha is not active, if you enable Auto-approval, users will be <b>automatically accepted into the group</b> as soon as they make a request (unless another check is triggered).\n\n"
        "💬 You can choose whether to send the welcome message in the group or in the private chat to the user.\n\n"
        "👥 If a user joins with a link that doesn't require approval, the procedures will be carried out regularly in the group.\n\n"
        "💡 <b>Status:</b>\n"
        f" • Auto-approval: {'Active' if a['auto'] else 'Off'}\n • Welcome: {'Private chat' if a['welcome'] == 'private' else 'Group'}\n\n"
        "<i>The bot needs the 'Invite users' admin right.</i>"
    )
    kb = [
        [btn(cid, "🔒 Auto-approval ⤵️", "noop")],
        [btn(cid, "✖ Turn off", "sb", "approval.auto", 0, "approval"), btn(cid, "✔ Turn on", "sb", "approval.auto", 1, "approval")],
        [btn(cid, "💬 Welcome ⤵️", "noop")],
        [btn(cid, ("✔ " if a["welcome"] == "private" else "") + "👤 Private chat", "st", "approval.welcome", "private", "approval"),
         btn(cid, ("✔ " if a["welcome"] == "group" else "") + "👥 Group", "st", "approval.welcome", "group", "approval")],
        back_row(cid),
    ]
    return text, InlineKeyboardMarkup(kb)


async def pg_admin(context, cid, arg):
    r = sp(cid)["report"]
    active = r["mode"] != "nobody" or r["tag_founder"] or r["tag_admins"]
    send_to = {"nobody": "✖ Nobody", "founder": "👑 Founder", "staff": "👥 Staff Group"}[r["mode"]]
    text = (
        "🆘 <b>@admin command</b>\n"
        "@admin (or /report) is a command available to users to attract the attention of the group's staff, for example if some other user is not respecting the group's rules.\n\n"
        "From this menu you can set where you want the reports made by users to be sent and/or whether to tag some staff members directly.\n\n"
        "⚠️ The @admin command DOES NOT work when used by Admins or Mods.\n\n"
        f"<b>Status:</b> {'Active' if active else 'Off'}\n<b>Send to:</b> {send_to}\n"
        f"<b>Staff group ID:</b> <code>{r['staff_chat'] or 'not set'}</code>"
    )

    def pb(code, label):
        return btn(cid, ("✔ " if r["mode"] == code else "") + label, "st", "report.mode", code, "admin")

    kb = [
        [pb("nobody", "✖ Nobody"), pb("founder", "👑 Founder")],
        [pb("staff", "👥 Staff Group"), btn(cid, "✍️ Set staff group ID", "inp", "staff_chat", "x", "admin")],
        [btn(cid, f"🔔 Tag Founder {onoff(r['tag_founder'])}", "tg", "report.tag_founder", "admin")],
        [btn(cid, f"🔔 Tag Admins {onoff(r['tag_admins'])}", "tg", "report.tag_admins", "admin")],
        back_row(cid),
    ]
    return text, InlineKeyboardMarkup(kb)


async def pg_delmsg(context, cid, arg):
    d = sp(cid)["delmsg"]
    serv = d["service_join"] or d["service_leave"] or d["service_pin"] or d["service_other"]
    text = (
        "🗑 <b>Deleting Messages</b>\nWhat messages do you want the Bot to delete?\n\n"
        f"🤖 Commands {onoff(d['commands'])} — command messages are removed 3s after use\n"
        f"🤫 Global Silence {onoff(d['silence'])} — every message from non-admins is deleted\n"
        f"✍️ Edit Checks {onoff(d['edit_checks'])} — edited messages are checked again\n"
        f"💥 Service Messages {onoff(serv)} — join / leave / pin / other\n"
        f"🕒 Scheduled deletion: <b>{human_secs(d['scheduled'])}</b> — all messages auto-deleted\n"
        f"📓 Block cancellation {onoff(d['block_cancel'])} — when the bot bans/kicks someone, their recent messages are deleted\n"
        f"♻️ Messages self-destruction: <b>{human_secs(d['selfdestruct'])}</b> — the bot's own messages auto-delete"
    )
    kb = [
        [btn(cid, f"🤖 Commands {onoff(d['commands'])}", "tg", "delmsg.commands", "delmsg")],
        [btn(cid, f"🤫 Global Silence {onoff(d['silence'])}", "tg", "delmsg.silence", "delmsg")],
        [btn(cid, f"✍️ Edit Checks {onoff(d['edit_checks'])}", "tg", "delmsg.edit_checks", "delmsg")],
        [nav(cid, "💥 Service Messages", "dm_serv")],
        [nav(cid, f"🕒 Scheduled deletion ({human_secs(d['scheduled'])})", "dm_sched")],
        [btn(cid, f"📓 Block cancellation {onoff(d['block_cancel'])}", "tg", "delmsg.block_cancel", "delmsg")],
        [nav(cid, f"♻️ Messages self-destruction ({human_secs(d['selfdestruct'])})", "dm_sd")],
        back_row(cid),
    ]
    return text, InlineKeyboardMarkup(kb)


async def pg_dm_serv(context, cid, arg):
    d = sp(cid)["delmsg"]
    text = "💥 <b>Service Messages</b>\nChoose which service messages the bot should delete."
    kb = [
        [btn(cid, f"👦 Joined {onoff(d['service_join'])}", "tg", "delmsg.service_join", "dm_serv"),
         btn(cid, f"🚪 Left {onoff(d['service_leave'])}", "tg", "delmsg.service_leave", "dm_serv")],
        [btn(cid, f"📌 Pinned {onoff(d['service_pin'])}", "tg", "delmsg.service_pin", "dm_serv"),
         btn(cid, f"🧩 Other {onoff(d['service_other'])}", "tg", "delmsg.service_other", "dm_serv")],
        back_row(cid, "delmsg"),
    ]
    return text, InlineKeyboardMarkup(kb)


def _choice_page(cid, path, options, page, back, title, desc):
    cur = int(path_get(cid, path))
    text = f"{title}\n{desc}\n\n<b>Current:</b> {human_secs(cur)}"
    row, kb = [], []
    for v, lab in options:
        row.append(btn(cid, ("✅ " if cur == v else "") + lab, "st", path, v, page))
        if len(row) == 3:
            kb.append(row)
            row = []
    if row:
        kb.append(row)
    kb.append(back_row(cid, back))
    return text, InlineKeyboardMarkup(kb)


async def pg_dm_sched(context, cid, arg):
    return _choice_page(cid, "delmsg.scheduled",
                        [(0, "Off"), (60, "1m"), (300, "5m"), (1800, "30m"), (3600, "1h"), (21600, "6h"), (86400, "24h")],
                        "dm_sched", "delmsg", "🕒 <b>Scheduled deletion</b>",
                        "Every message in the group is deleted after the chosen time (bot needs 'Delete messages'). Pending deletions are lost if the bot restarts.")


async def pg_dm_sd(context, cid, arg):
    return _choice_page(cid, "delmsg.selfdestruct",
                        [(0, "Off"), (10, "10s"), (30, "30s"), (60, "1m"), (300, "5m"), (1800, "30m")],
                        "dm_sd", "delmsg", "♻️ <b>Messages self-destruction</b>",
                        "The bot's own messages (replies, notices) in this group delete themselves after the chosen time. Menus with buttons are kept.")


async def pg_words(context, cid, arg):
    w = sp(cid)["words"]
    shown = ", ".join(f"<code>{esc(x)}</code>" for x in w["list"][:40]) or "—"
    if len(w["list"]) > 40:
        shown += f" … (+{len(w['list']) - 40})"
    text = (
        "🔤 <b>Banned Words</b>\nMessages containing a banned word (any part of the text, not case sensitive) are punished.\n\n"
        f"<b>Punishment:</b> {pun_label(w)}\n<b>Words ({len(w['list'])}):</b> {shown}"
    )
    kb = pun_rows(cid, "words", "words") + [
        [btn(cid, "➕ Add", "inp", "words_add", "x", "words"), btn(cid, "➖ Remove", "inp", "words_del", "x", "words")],
        [btn(cid, "🗑 Clear all", "words_clear")],
        back_row(cid, "other"),
    ]
    return text, InlineKeyboardMarkup(kb)


async def pg_length(context, cid, arg):
    ln = sp(cid)["length"]
    text = (
        "📏 <b>Message length</b>\nPunish messages longer than the maximum.\n\n"
        f"<b>Maximum:</b> {ln['max'] if int(ln['max']) else 'Off'}\n<b>Punishment:</b> {pun_label(ln)}"
    )
    kb = [[btn(cid, ("✅ " if int(ln["max"]) == v else "") + (str(v) if v else "Off"), "st", "length.max", v, "length")
           for v in (0, 100, 300, 500, 1000, 2000)]]
    kb += pun_rows(cid, "length", "length") + [back_row(cid, "other")]
    return text, InlineKeyboardMarkup(kb)


async def pg_recurring(context, cid, arg):
    items = sp(cid)["recurring"]
    lines = []
    for i, it in enumerate(items, 1):
        preview = re.sub(r"<[^>]+>", "", it["text"])[:40]
        lines.append(f"{i}. every <b>{human_secs(it['every'])}</b> — {esc(preview)}")
    text = "🕒 <b>Recurring messages</b>\nThe bot posts these messages again and again.\n\n" + ("\n".join(lines) if lines else "No recurring messages yet.")
    kb = []
    for i, it in enumerate(items, 1):
        kb.append([btn(cid, f"🗑 Delete #{i}", "rc_del", it["id"])])
    if len(items) < 10:
        kb.append([btn(cid, "➕ Add recurring message", "inp", "rc_text", "x", "recurring")])
    kb.append(back_row(cid, "other"))
    return text, InlineKeyboardMarkup(kb)


async def pg_perms(context, cid, arg):
    rights = [
        ("can_delete_messages", "Delete messages"), ("can_restrict_members", "Restrict/ban users"),
        ("can_pin_messages", "Pin messages"), ("can_invite_users", "Invite users"),
        ("can_promote_members", "Add admins"), ("can_change_info", "Change group info"),
    ]
    try:
        m = await context.bot.get_chat_member(cid, context.bot.id)
        status = str(getattr(m.status, "value", m.status))
        is_adm = status in ("administrator", "creator", "owner")
        lines = [f"<b>Bot is admin:</b> {onoff(is_adm)}"]
        for attr, label in rights:
            ok = is_adm and (status in ("creator", "owner") or bool(getattr(m, attr, False)))
            lines.append(f"{onoff(ok)} {label}")
        body = "\n".join(lines)
    except TelegramError as e:
        body = f"Could not read permissions: {esc(e)}"
    text = f"🔑 <b>Permissions</b>\nWhat the bot is allowed to do in this group:\n\n{body}\n\n<i>Settings can only be changed by group admins.</i>"
    kb = [[nav(cid, "🔄 Refresh", "perms")], back_row(cid, "other")]
    return text, InlineKeyboardMarkup(kb)


async def pg_log(context, cid, arg):
    target = sp(cid)["log_chat"]
    text = (
        "🔍 <b>Log Channel</b>\nAutomatic punishments, blocks, captcha results and admin commands are logged to a channel/group you choose.\n\n"
        f"<b>Current:</b> <code>{target or 'not set'}</code>\n\n"
        "Add the bot to the channel as admin, then press Set and send the @username, the ID, or forward a message from it."
    )
    kb = [[btn(cid, "✍️ Set log channel", "inp", "log_chat", "x", "log")]]
    if target:
        kb.append([btn(cid, "🗑 Remove", "log_clear")])
    kb.append(back_row(cid, "other"))
    return text, InlineKeyboardMarkup(kb)


PAGE_RENDERERS = {
    "main": pg_main, "other": pg_other, "botmenu": pg_botmenu, "welcome": pg_welcome, "goodbye": pg_goodbye,
    "rich": pg_rich, "rules": pg_rules, "cmdperm": pg_cmdperm, "alpha": pg_alpha, "flood": pg_flood,
    "spam": pg_spam, "pun": pg_pun, "media": pg_media, "warns": pg_warns, "warned": pg_warned,
    "night": pg_night, "nightslot": pg_nightslot, "nighttz": pg_nighttz, "checks": pg_checks,
    "chk_obl": pg_chk_obl, "chk_names": pg_chk_names, "blocks": pg_blocks, "bl": pg_bl,
    "captcha": pg_captcha, "approval": pg_approval, "admin": pg_admin, "delmsg": pg_delmsg,
    "dm_serv": pg_dm_serv, "dm_sched": pg_dm_sched, "dm_sd": pg_dm_sd, "words": pg_words,
    "length": pg_length, "recurring": pg_recurring, "perms": pg_perms, "log": pg_log,
}


async def render_page(context, cid, page):
    name, _, arg = page.partition(":")
    fn = PAGE_RENDERERS.get(name, pg_main)
    return await fn(context, cid, arg)


async def edit_panel(context, q, cid, page):
    text, markup = await render_page(context, cid, page)
    try:
        await q.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=markup)
    except BadRequest as e:
        if "not modified" not in str(e).lower():
            logger.warning("edit_panel failed: %s", e)


# ---------------------------------------------------------------------
#  Entry points
# ---------------------------------------------------------------------
async def user_admin_groups(context, user_id):
    out = []
    for gid, gs in list(DATA["groups"].items())[:60]:
        try:
            cid = int(gid)
        except ValueError:
            continue
        if cid >= 0:
            continue
        if is_owner_or_sudo(user_id) or await is_admin(context, cid, user_id):
            out.append((cid, (gs or {}).get("title") or str(cid)))
    return out


async def settings_cmd(update, context):
    track_command(update)
    chat = update.effective_chat
    user = update.effective_user
    msg = update.effective_message
    if is_group(chat):
        if not (is_owner_or_sudo(user.id) or await is_admin(context, chat.id, user.id)):
            await msg.reply_text("❌ Ni admin wa group tu ndiye anayeweza kufungua settings.")
            return
        group_settings(chat.id)["title"] = chat.title or ""
        text, markup = await pg_main(context, chat.id, "")
        await msg.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=markup)
        return
    groups_ = await user_admin_groups(context, user.id)
    if not groups_:
        await msg.reply_text("❌ Sijakuta group lolote ambalo wewe ni admin na mimi nipo. Niongeze kwenye group, nipe admin, kisha tuma /settings humo.")
        return
    kb = [[InlineKeyboardButton(f"👥 {title[:40]}", callback_data=cbd(cid, "pg", "main"))] for cid, title in groups_]
    await msg.reply_text("⚙️ <b>SETTINGS</b>\n\nChagua group unalotaka kusimamia:", parse_mode=ParseMode.HTML,
                         reply_markup=InlineKeyboardMarkup(kb))


async def spx_callback(update, context):
    q = update.callback_query
    chat = q.message.chat
    user = q.from_user
    if is_group(chat):
        if not (is_owner_or_sudo(user.id) or await is_admin(context, chat.id, user.id)):
            await q.answer("Admin wa group tu.", show_alert=True)
            return
        group_settings(chat.id)["title"] = chat.title or ""
        await q.answer()
        await edit_panel(context, q, chat.id, "main")
        return
    groups_ = await user_admin_groups(context, user.id)
    await q.answer()
    if not groups_:
        await q.message.reply_text("❌ Sijakuta group lolote ambalo wewe ni admin.")
        return
    kb = [[InlineKeyboardButton(f"👥 {title[:40]}", callback_data=cbd(cid, "pg", "main"))] for cid, title in groups_]
    await q.edit_message_text("⚙️ <b>SETTINGS</b>\n\nChagua group unalotaka kusimamia:", parse_mode=ParseMode.HTML,
                              reply_markup=InlineKeyboardMarkup(kb))


# ---------------------------------------------------------------------
#  Main panel callback
# ---------------------------------------------------------------------
async def start_input(context, q, cid, kind, prompt, page, extra=None):
    panel_chat = q.message.chat.id
    uid = q.from_user.id
    try:
        m = await context.bot.send_message(panel_chat, prompt + "\n\n<i>/cancel to abort.</i>", parse_mode=ParseMode.HTML)
    except TelegramError:
        return
    PENDING[(panel_chat, uid)] = {
        "kind": kind, "cid": cid, "ts": time.time(), "page": page,
        "panel_msg": q.message.message_id, "prompt_msg": m.message_id, "extra": extra,
    }


INPUT_PROMPTS = {
    "rich_text": "✍️ Send me the new <b>text</b> now. Formatting (bold, links…) is kept. Placeholders: <code>{name} {username} {group} {id} {count}</code>",
    "rich_media": "📸 Send me the <b>photo, video, GIF or file</b> to attach.",
    "rich_buttons": "🔤 Send the <b>buttons</b>, one row per line:\n<code>Label - https://link</code>\nTwo buttons in one row: <code>One - https://a.com | Two - https://b.com</code>",
    "bl_add": "➕ Send the <b>user ID(s)</b> to blacklist (separated by space/comma), or forward a message from the user.",
    "bl_del": "➖ Send the <b>user ID(s)</b> to remove from the blacklist.",
    "words_add": "➕ Send the <b>words</b> to ban (one per line or separated by commas).",
    "words_del": "➖ Send the <b>words</b> to remove (one per line or separated by commas).",
    "rc_text": "🕒 Send the <b>text</b> of the recurring message (formatting is kept).",
    "chk_channel": "📢 Send the channel <b>@username</b> (the bot must be admin in that channel).",
    "staff_chat": "👥 Send the <b>ID</b> of the staff group (e.g. <code>-1001234567890</code>) or forward a message from it.",
    "log_chat": "🔍 Send the channel/group <b>@username or ID</b>, or forward a message from it.",
}


async def sp_callback(update, context):
    q = update.callback_query
    parts = (q.data or "").split("|")
    if len(parts) < 3:
        await q.answer()
        return
    try:
        cid = int(parts[1])
    except ValueError:
        await q.answer()
        return
    uid = q.from_user.id
    if not (is_owner_or_sudo(uid) or await is_admin(context, cid, uid)):
        await q.answer("Admin wa group tu.", show_alert=True)
        return
    action, args = parts[2], parts[3:]
    p = sp(cid)
    s = group_settings(cid)
    try:
        if action == "noop":
            await q.answer()
            return
        if action == "close":
            await q.answer()
            try:
                await q.message.delete()
            except TelegramError:
                pass
            return
        if action == "pg":
            await q.answer()
            await edit_panel(context, q, cid, args[0] if args else "main")
            return
        if action == "tg":
            path, page = args[0], args[1]
            cur = path_get(cid, path)
            if not isinstance(cur, bool):
                await q.answer("Invalid.", show_alert=True)
                return
            path_set(cid, path, not cur)
            save_data()
            await q.answer(f"{'ON' if not cur else 'OFF'}")
            await edit_panel(context, q, cid, page)
            return
        if action == "sb":
            path, val, page = args[0], args[1], args[2]
            if not isinstance(path_get(cid, path), bool):
                await q.answer("Invalid.", show_alert=True)
                return
            path_set(cid, path, val == "1")
            save_data()
            await q.answer("ON" if val == "1" else "OFF")
            await edit_panel(context, q, cid, page)
            return
        if action == "st":
            path, val, page = args[0], args[1], args[2]
            if val not in ST_ALLOWED.get(path, set()):
                await q.answer("Invalid.", show_alert=True)
                return
            cur = path_get(cid, path)
            path_set(cid, path, int(val) if isinstance(cur, int) and not isinstance(cur, bool) else val)
            save_data()
            await q.answer("✅")
            await edit_panel(context, q, cid, page)
            return
        if action == "pn":
            path, code, page = args[0], args[1], args[2]
            if path not in PUN_PATHS or code not in PUN_CODES:
                await q.answer("Invalid.", show_alert=True)
                return
            path_get(cid, path)["pun"] = code
            save_data()
            await q.answer(f"{PUN_NAMES[code]}")
            await edit_panel(context, q, cid, page)
            return
        if action == "adj":
            path, delta, page = args[0], int(args[1]), args[2]
            if path not in ADJ_ALLOWED:
                await q.answer("Invalid.", show_alert=True)
                return
            lo, hi, wrap = ADJ_ALLOWED[path]
            val = int(path_get(cid, path)) + delta
            if val > hi:
                val = lo if wrap else hi
            if val < lo:
                val = hi if wrap else lo
            path_set(cid, path, val)
            save_data()
            await q.answer(str(val))
            await edit_panel(context, q, cid, page)
            return
        if action == "md":
            kind, code = args[0], args[1]
            if kind not in p["media"] or code not in MEDIA_CODE_LABEL:
                await q.answer("Invalid.", show_alert=True)
                return
            p["media"][kind] = code
            save_data()
            await q.answer(MEDIA_CODE_LABEL[code])
            await edit_panel(context, q, cid, "media")
            return
        if action == "mdi":
            label = next((l for k, _, l in MEDIA_TYPES if k == args[0]), args[0])
            await q.answer(label)
            return
        if action == "wl_reset":
            s["warnings"].clear()
            save_data()
            await q.answer("🧹 Done")
            await edit_panel(context, q, cid, "warned")
            return
        if action == "bl_clear":
            p["blocks"]["blacklist"].clear()
            save_data()
            await q.answer("🗑 Cleared")
            await edit_panel(context, q, cid, "bl")
            return
        if action == "words_clear":
            p["words"]["list"].clear()
            save_data()
            await q.answer("🗑 Cleared")
            await edit_panel(context, q, cid, "words")
            return
        if action == "log_clear":
            p["log_chat"] = 0
            save_data()
            await q.answer("🗑 Removed")
            await edit_panel(context, q, cid, "log")
            return
        if action == "rc_del":
            p["recurring"] = [it for it in p["recurring"] if it["id"] != args[0]]
            save_data()
            await q.answer("🗑 Deleted")
            await edit_panel(context, q, cid, "recurring")
            return
        if action == "rc_add":
            text = RC_DRAFT.pop((cid, uid), None)
            if not text:
                await q.answer("Expired — start again.", show_alert=True)
                return
            every = int(args[0])
            if every not in (900, 1800, 3600, 10800, 21600, 43200, 86400) or len(p["recurring"]) >= 10:
                await q.answer("Invalid.", show_alert=True)
                return
            p["recurring"].append({"id": secrets.token_hex(3), "text": text, "every": every, "last": time.time()})
            save_data()
            await q.answer("✅ Created")
            kb = InlineKeyboardMarkup([[nav(cid, "🕒 Recurring messages", "recurring")]])
            await q.edit_message_text(f"✅ Recurring message created — every <b>{human_secs(every)}</b>.",
                                      parse_mode=ParseMode.HTML, reply_markup=kb)
            return
        if action == "inp":
            kind, extra, page = args[0], args[1], args[2]
            if kind not in INPUT_PROMPTS:
                await q.answer("Invalid.", show_alert=True)
                return
            await q.answer()
            await start_input(context, q, cid, kind, INPUT_PROMPTS[kind], page, extra)
            return
        if action == "rm":
            kind, what, page = args[0], args[1], args[2]
            if kind not in RICH_TEXT_KEY:
                await q.answer("Invalid.", show_alert=True)
                return
            if what == "media":
                p["rich"][kind]["media"] = None
            elif what == "buttons":
                p["rich"][kind]["buttons"] = []
            save_data()
            await q.answer("🗑 Removed")
            await edit_panel(context, q, cid, page)
            return
        if action == "see":
            kind, what = args[0], args[1]
            if kind not in RICH_TEXT_KEY:
                await q.answer("Invalid.", show_alert=True)
                return
            await q.answer()
            chat = q.message.chat
            try:
                gchat = await context.bot.get_chat(cid)
            except TelegramError:
                gchat = chat
            spec = rich_spec(cid, kind)
            if what == "text":
                if not s.get(RICH_TEXT_KEY[kind]):
                    await q.answer("No text set.", show_alert=True)
                    return
                spec = dict(spec, media=None, buttons=[])
            elif what == "media":
                if not spec["media"]:
                    await q.answer("No media set.", show_alert=True)
                    return
                spec = dict(spec, text="", buttons=[])
            elif what == "buttons":
                if not spec["buttons"]:
                    await q.answer("No buttons set.", show_alert=True)
                    return
                spec = dict(spec, text="👇 Buttons preview", html=True, media=None)
            m = await send_rich(context, chat.id, gchat, kind, q.from_user, spec=spec)
            if m:
                schedule_delete(context, chat.id, m.message_id, 60)
            return
        await q.answer()
    except KeyError:
        await q.answer("Invalid.", show_alert=True)
    except TelegramError as e:
        logger.warning("Panel callback error: %s", e)


# ---------------------------------------------------------------------
#  Pending text/media input from admins
# ---------------------------------------------------------------------
def _parse_ids(text):
    return [int(x) for x in re.findall(r"-?\d{5,}", text or "")]


def _forwarded_user_id(msg):
    origin = getattr(msg, "forward_origin", None)
    u = getattr(origin, "sender_user", None) if origin else None
    if u:
        return u.id
    fu = getattr(msg, "forward_from", None)
    return fu.id if fu else None


def _forwarded_chat_id(msg):
    origin = getattr(msg, "forward_origin", None)
    c = getattr(origin, "chat", None) if origin else None
    if c:
        return c.id
    fc = getattr(msg, "forward_from_chat", None)
    return fc.id if fc else None


def _split_words(text):
    out = []
    for part in re.split(r"[\n,]+", text or ""):
        part = part.strip().lower()
        if part and part not in out:
            out.append(part[:60])
    return out


async def sp_pending_input(update, context):
    """Returns True when the message was consumed as input for a pending panel action."""
    msg = update.effective_message
    chat = update.effective_chat
    user = update.effective_user
    key = (chat.id, user.id)
    pend = PENDING.get(key)
    if not pend:
        return False
    if time.time() - pend["ts"] > PENDING_TTL:
        PENDING.pop(key, None)
        return False
    if update.edited_message is not None:
        return False
    cid, kind = pend["cid"], pend["kind"]
    p = sp(cid)
    s = group_settings(cid)
    text = msg.text or msg.caption or ""
    ok, error = False, "❌ That is not valid. Try again or /cancel."

    if kind == "rich_text":
        if msg.text:
            s[RICH_TEXT_KEY[pend["extra"]]] = msg.text_html
            p["rich"][pend["extra"]]["html"] = True
            ok = True
        else:
            error = "❌ Send plain text."
    elif kind == "rich_media":
        media = None
        if msg.photo:
            media = {"type": "photo", "id": msg.photo[-1].file_id}
        elif msg.video:
            media = {"type": "video", "id": msg.video.file_id}
        elif msg.animation:
            media = {"type": "animation", "id": msg.animation.file_id}
        elif msg.document:
            media = {"type": "document", "id": msg.document.file_id}
        if media:
            p["rich"][pend["extra"]]["media"] = media
            ok = True
        else:
            error = "❌ Send a photo, video, GIF or file."
    elif kind == "rich_buttons":
        rows = parse_buttons(msg.text or "")
        if rows:
            p["rich"][pend["extra"]]["buttons"] = rows
            ok = True
        else:
            error = "❌ Wrong format. Use: <code>Label - https://link</code> (one row per line)."
    elif kind == "bl_add":
        ids = _parse_ids(text)
        fid = _forwarded_user_id(msg)
        if fid:
            ids.append(fid)
        ids = [i for i in ids if i != OWNER_ID and i != context.bot.id]
        if ids:
            for i in ids:
                if i not in p["blocks"]["blacklist"]:
                    p["blocks"]["blacklist"].append(i)
                try:
                    await context.bot.ban_chat_member(cid, i)
                except TelegramError:
                    pass
            ok = True
    elif kind == "bl_del":
        ids = _parse_ids(text)
        if ids:
            for i in ids:
                if i in p["blocks"]["blacklist"]:
                    p["blocks"]["blacklist"].remove(i)
                try:
                    await context.bot.unban_chat_member(cid, i, only_if_banned=True)
                except TelegramError:
                    pass
            ok = True
    elif kind == "words_add":
        words = _split_words(text)
        if words:
            for w in words:
                if w not in p["words"]["list"]:
                    p["words"]["list"].append(w)
            del p["words"]["list"][200:]
            ok = True
    elif kind == "words_del":
        words = _split_words(text)
        if words:
            p["words"]["list"] = [w for w in p["words"]["list"] if w not in words]
            ok = True
    elif kind == "rc_text":
        if msg.text:
            RC_DRAFT[(cid, user.id)] = msg.text_html
            kb = InlineKeyboardMarkup([
                [btn(cid, lab, "rc_add", v) for v, lab in ((900, "15m"), (1800, "30m"), (3600, "1h"))],
                [btn(cid, lab, "rc_add", v) for v, lab in ((10800, "3h"), (21600, "6h"), (43200, "12h"), (86400, "24h"))],
            ])
            PENDING.pop(key, None)
            try:
                await context.bot.delete_message(chat.id, pend["prompt_msg"])
            except TelegramError:
                pass
            await context.bot.send_message(chat.id, "⏱ How often should it be posted?", reply_markup=kb)
            return True
        error = "❌ Send plain text."
    elif kind == "chk_channel":
        name = text.strip()
        if re.fullmatch(r"@[A-Za-z][A-Za-z0-9_]{3,}", name):
            p["checks"]["channel_name"] = name
            ok = True
        else:
            error = "❌ Send a valid @username, e.g. <code>@mychannel</code>."
    elif kind == "staff_chat":
        ids = _parse_ids(text)
        fid = _forwarded_chat_id(msg)
        target = fid or (ids[0] if ids else None)
        if target:
            p["report"]["staff_chat"] = int(target)
            ok = True
    elif kind == "log_chat":
        fid = _forwarded_chat_id(msg)
        ids = _parse_ids(text)
        target = fid or (ids[0] if ids else None)
        if not target and re.fullmatch(r"@[A-Za-z][A-Za-z0-9_]{3,}", text.strip()):
            try:
                target = (await context.bot.get_chat(text.strip())).id
            except TelegramError:
                target = None
                error = "❌ I can't find that chat. Add me as admin first."
        if target:
            try:
                await context.bot.send_message(int(target), "✅ This chat is now the log channel.")
                p["log_chat"] = int(target)
                ok = True
            except TelegramError:
                error = "❌ I can't write there. Add me as admin of that chat first."

    if not ok:
        await msg.reply_text(error, parse_mode=ParseMode.HTML)
        return True

    PENDING.pop(key, None)
    save_data()
    await safe_delete(msg)
    try:
        await context.bot.delete_message(chat.id, pend["prompt_msg"])
    except TelegramError:
        pass
    try:
        ptext, pmarkup = await render_page(context, cid, pend["page"])
        await context.bot.edit_message_text(ptext, chat_id=chat.id, message_id=pend["panel_msg"],
                                            parse_mode=ParseMode.HTML, reply_markup=pmarkup)
    except TelegramError as e:
        logger.debug("Panel refresh failed: %s", e)
    await notify(context, chat.id, "✅ Saved.", temp=5)
    return True

# =====================================================================
#  Background jobs
# =====================================================================
def _saved_permissions(chat):
    perms = getattr(chat, "permissions", None)
    if not perms:
        return None
    try:
        return perms.to_dict()
    except Exception:
        return None


def _restore_permissions(bot, saved):
    if saved:
        try:
            return ChatPermissions.de_json(saved, bot)
        except Exception:
            pass
    return open_permissions()


async def night_job(context):
    for gid, gs in list(DATA["groups"].items()):
        if not isinstance(gs, dict) or not isinstance(gs.get("sp"), dict):
            continue
        try:
            chat_id = int(gid)
        except ValueError:
            continue
        n = sp(chat_id)["night"]
        if not n["on"] and not n["active"] and not n["saved"]:
            continue
        should = bool(n["on"]) and night_active_now(n)
        want_silence = should and bool(n["silence"])
        try:
            if want_silence and not n["saved"]:
                chat = await context.bot.get_chat(chat_id)
                n["saved"] = _saved_permissions(chat) or {"can_send_messages": True}
                await context.bot.set_chat_permissions(chat_id, mute_permissions())
            elif not want_silence and n["saved"]:
                await context.bot.set_chat_permissions(chat_id, _restore_permissions(context.bot, n["saved"]))
                n["saved"] = None
            if should and not n["active"]:
                n["active"] = True
                if n["advise"]:
                    await notify(context, chat_id, f"🌘 <b>Night mode started.</b> See you at {n['end']}:00 🌅")
            elif not should and n["active"]:
                n["active"] = False
                if n["advise"]:
                    await notify(context, chat_id, "🌅 <b>Night mode ended.</b> Good morning, everyone!")
            save_data()
        except TelegramError as e:
            logger.warning("Night job failed for %s: %s", chat_id, e)


async def recurring_job(context):
    now = time.time()
    for gid, gs in list(DATA["groups"].items()):
        if not isinstance(gs, dict) or not isinstance(gs.get("sp"), dict):
            continue
        items = gs["sp"].get("recurring") or []
        changed = False
        for it in items:
            every = float(it.get("every", 0))
            if every > 0 and now - float(it.get("last", 0)) >= every:
                it["last"] = now
                changed = True
                try:
                    await context.bot.send_message(int(gid), it["text"], parse_mode=ParseMode.HTML)
                except (TelegramError, ValueError) as e:
                    logger.warning("Recurring message failed in %s: %s", gid, e)
        if changed:
            save_data()


def sp_post_init(application):
    jq = application.job_queue
    if jq is None:
        logger.warning("JobQueue not available — install python-telegram-bot[job-queue] for night mode, "
                       "recurring messages, captcha timeouts and auto-unmute.")
        return
    jq.run_repeating(night_job, interval=60, first=15, name="night_tick")
    jq.run_repeating(recurring_job, interval=30, first=20, name="recurring_tick")
    now = time.time()
    for gid, gs in list(DATA["groups"].items()):
        if not isinstance(gs, dict) or not isinstance(gs.get("sp"), dict):
            continue
        try:
            chat_id = int(gid)
        except ValueError:
            continue
        pending = (gs["sp"].get("captcha") or {}).get("pending") or {}
        for uid, pend in list(pending.items()):
            remaining = max(1.0, float(pend.get("until", now)) - now)
            jq.run_once(captcha_timeout, remaining, data={"chat_id": chat_id, "user_id": int(uid)},
                        name=f"cap:{chat_id}:{uid}")


# =====================================================================
#  Patches / registry
# =====================================================================
def install_selfdestruct_patch():
    """Makes the bot's own group messages (without buttons) delete themselves when enabled."""
    from telegram import Bot
    if getattr(Bot, "_luqman_patched", False):
        return
    orig = Bot.send_message

    async def wrapper(self, *args, **kwargs):
        msg = await orig(self, *args, **kwargs)
        try:
            chat_id = args[0] if args else kwargs.get("chat_id")
            if isinstance(chat_id, int) and chat_id < 0 and kwargs.get("reply_markup") is None and msg:
                gs = DATA["groups"].get(str(chat_id))
                secs = int(((gs or {}).get("sp") or {}).get("delmsg", {}).get("selfdestruct", 0))
                app = APP_REF.get("app")
                if secs > 0 and app and app.job_queue:
                    app.job_queue.run_once(delete_msg_job, secs,
                                           data={"chat_id": chat_id, "message_id": msg.message_id})
        except Exception:
            logger.debug("self-destruct hook failed", exc_info=True)
        return msg

    Bot.send_message = wrapper
    Bot._luqman_patched = True


LOGGED_COMMANDS = {
    "ban", "unban", "softban", "kick", "mute", "unmute", "warn", "unwarn", "resetwarn",
    "promote", "demote", "purge", "lock", "unlock", "pin", "unpin", "blacklist", "unblacklist",
}


def logged(name, callback):
    async def inner(update, context):
        await callback(update, context)
        try:
            chat = update.effective_chat
            user = update.effective_user
            if is_group(chat) and user and sp(chat.id).get("log_chat"):
                extra = ""
                rt = update.effective_message.reply_to_message
                if rt and rt.from_user:
                    extra = f" → {mention(rt.from_user.id, rt.from_user.full_name)}"
                elif context.args:
                    extra = f" {esc(' '.join(context.args)[:80])}"
                await log_action(context, chat.id, f"👮 {mention(user.id, user.full_name)} used /{name}{extra}")
        except Exception:
            logger.debug("command logging failed", exc_info=True)
    return inner


NEW_COMMANDS = {
    "settings": settings_cmd, "staff": staff_cmd, "me": me_cmd, "translate": translate_cmd,
    "link": link_cmd, "report": report_cmd, "blacklist": blacklist_cmd,
    "unblacklist": unblacklist_cmd, "cancel": cancel_cmd,
}


KNOWN_COMMANDS = {
    "start","menu","help","alive","ping","owner","ownerpanel","addsudo","delsudo","listsudo","botstats","groups","broadcast",
    "id","info","status","ginfo","admins","antilink","antisticker","antimedia","antispam","antiflood","antibot","antimention",
    "welcome","goodbye","setwelcome","setgoodbye","setrules","rules","clearrules","warn","warnings","unwarn","resetwarn","ban",
    "unban","softban","mute","unmute","kick","promote","demote","pin","unpin","del","purge","lock","unlock","setwarnlimit",
    "setflood","setspam","math","calc","font","qr","save","get","notes","delnote","clearnotes","remind","reminders","delreminder",
    "base64","decode64","hash","uuid","password","random","choose","reverse","upper","lower","title","count","slug","encodeurl",
    "decodeurl","islink","remove_space","repeat","binary","unbinary","convert","dice","dart","football","coin","slot","8ball","joke",
    "love","settitle","setdescription","tagadmins","tagall","afk","filter","delfilter","filters",
    "settings","staff","me","translate","link","report","blacklist","unblacklist","cancel"
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
        try:
            await sp_track(update, context)
        except Exception:
            logger.debug("sp_track failed", exc_info=True)

async def error_handler(update, context):
    err = context.error
    if isinstance(err, (BadRequest, Forbidden)):
        logger.warning("Telegram error: %s", err)
    else:
        logger.exception("Unhandled error: %s", err)

def register_handlers(app):
    commands = {
        "start": start, "menu": menu, "help": menu, "alive": alive, "ping": ping, "owner": owner, "ownerpanel": ownerpanel,
        "addsudo": addsudo, "delsudo": delsudo, "listsudo": listsudo, "botstats": botstats, "groups": groups_cmd, "broadcast": broadcast,
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
    commands.update(NEW_COMMANDS)
    for name, callback in commands.items():
        if name in LOGGED_COMMANDS:
            callback = logged(name, callback)
        app.add_handler(CommandHandler(name, callback))
    app.add_handler(CallbackQueryHandler(sp_callback, pattern=r"^sp\|"))
    app.add_handler(CallbackQueryHandler(spx_callback, pattern=r"^spx:"))
    app.add_handler(CallbackQueryHandler(captcha_callback, pattern=r"^cap\|"))
    app.add_handler(CallbackQueryHandler(callback_handler, pattern=r"^(menu|toggle|cmd):"))
    app.add_handler(ChatJoinRequestHandler(handle_join_request))
    app.add_handler(InlineQueryHandler(inline_query))
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, handle_new_members))
    app.add_handler(MessageHandler(filters.StatusUpdate.LEFT_CHAT_MEMBER, handle_left_member))
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, handle_messages))
    app.add_handler(MessageHandler(filters.COMMAND, unknown_command), group=1)

def main():
    if TOKEN == "PASTE_YOUR_CURRENT_TOKEN_HERE":
        raise RuntimeError("Weka Telegram bot token yako kwenye variable TOKEN.")
    app = (
        Application.builder()
        .token(TOKEN)
        .post_init(post_init)
        .build()
    )
    APP_REF["app"] = app
    install_selfdestruct_patch()
    # Track all messages in an earlier handler group.
    app.add_handler(MessageHandler(filters.ALL, track_all_messages, block=False), group=-1)
    register_handlers(app)
    app.add_error_handler(error_handler)
    logger.info("%s v%s starting in %s mode", BOT_NAME, VERSION, MODE)
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)

if __name__ == "__main__":
    main()
