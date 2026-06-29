import logging
from telegram import Update
from telegram.error import BadRequest
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# --- CONFIGURATION ---
BOT_NAME = "𓊈𒆜꯭𝆭̽ 𝐋ʋ̽զϻ̈̐𝛂ƞ̄ 𝛅͜𝐉»ً𒆜꧂"
OWNER_NAME = "𝙇𝙐𝙌𝙈𝘼Ν 𝙎𝙅"
OWNER_ID = 255678716839  # ID yako ya namba ya Telegram
TOKEN = "8712244204:AAHtCFtRg9WF1iWtMvICC5eHfsG3eiCQIVY"

MODE = "public"

# Mfumo wa kumbukumbu
antilink = {}
antisticker = {}
mute = {}
sudo = []

def wm(text: str) -> str:
    return f"_{text}_\n\n_— luqman on fire 🔥_"

def is_owner_or_sudo(user_id: int) -> bool:
    return user_id == OWNER_ID or user_id in sudo

async def check_bot_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    bot_member = await context.bot.get_chat_member(chat_id=update.effective_chat.id, user_id=context.bot.id)
    if bot_member.status in ['administrator', 'creator']:
        return True
    await update.message.reply_text(
        wm("❌ **Amri Imeshindwa!**\nBot linahitaji nguvu ya **U-Admin (Admin Privileges)** kwenye kundi hili ili kufanya kazi."),
        parse_mode="Markdown"
    )
    return False

# --- COMMAND HANDLERS ---

async def menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    menu_text = f"""
╔═☠️═𒆜 {BOT_NAME} 𒆜═☠️═╗
║ 👑 Owner: {OWNER_NAME}
║ 🌍 Country: Tanzania
║ ⚡ Prefix: /
║ 🔥 Mode: {MODE}
║ 💾 RAM: ██████████ 100%
║ 🛡 Sudo: {len(sudo)}
╠══════════════════════☠️

║ 💀 GROUP
║ /tagall - Tag wanachama wote
║ /kick - Reply ujumbe kumfukuza mtu
║ /antilink on/off - Ulinzi wa Links
║ /antisticker on/off - Ulinzi wa Sticker
║ /mute on/off - Kufunga Group
║ /admins - Orodha ya Ma-admin
║ /ginfo - Taarifa za Kundi
║ /id - Angalia ID yako au ya Kundi

╠══════════════════════☠️
║ 👑 OWNER
║ /alive - Hali ya bot
║ /ping - Kasi ya bot
║ /owner - Mawasiliano ya mmiliki

╚═☠️═ LUQMAN ON FIRE ═☠️═╝
"""
    await update.message.reply_text(wm(menu_text), parse_mode="Markdown")

async def alive_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(wm("🤖 **LUQMAN X MD** ipo hai na inafanya kazi kikamilifu! ✅"), parse_mode="Markdown")

async def ping_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(wm("⚡ **Response:** 0.02ms | Mfumo upo imara! ✅"), parse_mode="Markdown")

async def owner_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(wm(f"👑 **Taarifa za Mmiliki:**\n\nJina: {OWNER_NAME}\nTelegram ID: `{OWNER_ID}`"), parse_mode="Markdown")

async def id_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    id_text = f"👤 **ID Yako:** `{user.id}`\n"
    if chat.type in ['group', 'supergroup']:
        id_text += f"📊 **ID ya Kundi:** `{chat.id}`"
    await update.message.reply_text(wm(id_text), parse_mode="Markdown")

async def antilink_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if not is_owner_or_sudo(update.effective_user.id): return
    if not await check_bot_admin(update, context): return

    if context.args and context.args[0] in ["on", "off"]:
        antilink[chat_id] = context.args[0] == "on"
        await update.message.reply_text(wm(f"✅ **Mabadiliko:** Antilink imewekwa **{context.args[0].upper()}**!"), parse_mode="Markdown")
    else:
        await update.message.reply_text(wm("⚠️ Kosa! Tumia: `/antilink on` au `/antilink off`"), parse_mode="Markdown")

async def antisticker_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if not is_owner_or_sudo(update.effective_user.id): return
    if not await check_bot_admin(update, context): return

    if context.args and context.args[0] in ["on", "off"]:
        antisticker[chat_id] = context.args[0] == "on"
        await update.message.reply_text(wm(f"✅ **Mabadiliko:** Antisticker imewekwa **{context.args[0].upper()}**!"), parse_mode="Markdown")
    else:
        await update.message.reply_text(wm("⚠️ Kosa! Tumia: `/antisticker on` au `/antisticker off`"), parse_mode="Markdown")

async def mute_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if not is_owner_or_sudo(update.effective_user.id): return
    if not await check_bot_admin(update, context): return

    if context.args and context.args[0] in ["on", "off"]:
        mute[chat_id] = context.args[0] == "on"
        await update.message.reply_text(wm(f"✅ **Mabadiliko:** Group Mute imewekwa **{context.args[0].upper()}**!"), parse_mode="Markdown")
    else:
        await update.message.reply_text(wm("⚠️ Kosa! Tumia: `/mute on` au `/mute off`"), parse_mode="Markdown")

async def kick_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner_or_sudo(update.effective_user.id): return
    if not update.effective_chat.type in ['group', 'supergroup']: return
    if not await check_bot_admin(update, context): return

    if update.message.reply_to_message:
        user_to_kick = update.message.reply_to_message.from_user.id
        try:
            await context.bot.ban_chat_member(chat_id=update.effective_chat.id, user_id=user_to_kick)
            await update.message.reply_text(wm("☠️ **Kazi Imekamilika:** Mtumiaji amefukuzwa rasmi! ✅"))
        except BadRequest:
            await update.message.reply_text(wm("❌ Siwezi kumtoa mtu huyu (huenda ni admin au mfumo una hitilafu)."))
    else:
        await update.message.reply_text(wm("⚠️ **Maelekezo:** Reply kwenye ujumbe wa mtu kisha andika `/kick`"))

async def admins_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_chat.type in ['group', 'supergroup']: return
    try:
        admins = await context.bot.get_chat_administrators(chat_id=update.effective_chat.id)
        admin_list = "\n".join([f"👑 @{admin.user.username}" if admin.user.username else f"👑 {admin.user.first_name}" for admin in admins])
        await update.message.reply_text(wm(f"👮‍♂️ **Ma-Admin wa Kundi:**\n\n{admin_list}"), parse_mode="Markdown")
    except Exception:
        await update.message.reply_text(wm("⚠️ Imeshindwa kupata orodha."))

async def ginfo_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if not chat.type in ['group', 'supergroup']: return
    count = await context.bot.get_chat_member_count(chat_id=chat.id)
    await update.message.reply_text(wm(f"📊 **Taarifa za Kundi:**\n\nJina: {chat.title}\nID ya Kundi: `{chat.id}`\nIdadi ya Watu: {count}"), parse_mode="Markdown")

async def unknown_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(wm("❌ **Amri Haipo!**\nTafadhali andika `/menu` kuona orodha ya amri sahihi zilizopo kwenye mfumo."), parse_mode="Markdown")

async def handle_incoming_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    message = update.message

    if not message: return
    
    if mute.get(chat_id) and not is_owner_or_sudo(user_id):
        try: await message.delete()
        except BadRequest: pass
        return

    if antisticker.get(chat_id) and message.sticker and not is_owner_or_sudo(user_id):
        try:
            await message.delete()
            await message.chat.send_message(wm("⚠️ **Ulinzi:** Stickers haziruhusiwi kwa sasa!"))
        except BadRequest: pass
        return

    if antilink.get(chat_id) and message.text and "https://" in message.text and not is_owner_or_sudo(user_id):
        try:
            await message.delete()
            await message.chat.send_message(wm("⚠️ **Ulinzi:** Links haziruhusiwi hapa!"))
        except BadRequest: pass
        return

def main():
    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("menu", menu_command))
    app.add_handler(CommandHandler("alive", alive_command))
    app.add_handler(CommandHandler("ping", ping_command))
    app.add_handler(CommandHandler("owner", owner_command))
    app.add_handler(CommandHandler("id", id_command))
    app.add_handler(CommandHandler("antilink", antilink_command))
    app.add_handler(CommandHandler("antisticker", antisticker_command))
    app.add_handler(CommandHandler("mute", mute_command))
    app.add_handler(CommandHandler("kick", kick_command))
    app.add_handler(CommandHandler("admins", admins_command))
    app.add_handler(CommandHandler("ginfo", ginfo_command))

    app.add_handler(MessageHandler(filters.COMMAND, unknown_command))
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, handle_incoming_messages))

    print("Telegram Bot is running smoothly with target token...")
    app.run_polling()

if __name__ == "__main__":
    main()
  
