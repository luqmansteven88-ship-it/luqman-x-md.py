import logging
import random
from telegram import Update, ChatPermissions
from telegram.error import BadRequest
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# --- CONFIGURATION ---
BOT_NAME = "𓊈𒆜꯭𝆭̽ 𝐋ʋ̽զϻ̈̐𝛂ƞ̄ 𝛅͜𝐉»ً𒆜꧂"
OWNER_NAME = "𝙇𝙐𝙌𝙈𝘼Ν 𝙎𝙅"
OWNER_ID = 255678716839  # ID yako ya namba ya Telegram
TOKEN = "8712244204:AAHeCNc8PfPFk_ifL78odGuyQEQzgkX8XWc"

MODE = "public"

# Mfumo wa kumbukumbu
antilink = {}
antisticker = {}
mute_group = {}  # Kufunga group zima
warns = {}       # Kumbukumbu ya maonyo ya watumiaji {'chat_id': {'user_id': count}}
sudo = []

# Data za Manjonjo
VICHEKESHO = [
    "Ushajua maisha ni magumu pale unapoona nzi anatua kwenye simu yako anasoma meseji za deni kisha anakuangalia kwa huruma na kuondoka. 😭",
    "Kuna watu wana sura ngumu hadi wakipiga selfie simu inawaambia: 'Are you sure you want to save this?' 💀",
    "Ukitaka kujua mnaendana na mpenzi wako, jaribuni kufungua duka la reja reja. Mkimaliza mwezi hamjafilisika, fungeni ndoa! 🤣",
    "Hivi wale mbu wanaong'ata huku wanapiga kelele masikioni huwa wanatupa taarifa au ni dharau tu? 🦟",
    "Kuna umri ukifika, ukisikia sauti ya 'Baby' kwenye simu yako unajua kabisa ni ujumbe wa mtandao unaokuambia bando limeisha. 🚶‍♂️"
]

LOVE_COMMENTS = [
    "💔 Daah! Hapa hakuna muunganiko kabisa, heri mkae mbali mbali mapema!",
    "📉 Uhusiano wa kusuasua, mnaishia kwenye 'Kaka na Dada' tu hapa.",
    "💛 Sio mbaya, mkiongeza juhudi na kuvumiliana mtafika mbali.",
    "❤️ Hatari sana! Hapa kuna mapenzi motomoto, duka la nguo linawahusu!",
    "💍 Hawa ni mume na mke halali kabisa! Harusi iandaliwe haraka sana! 🔥"
]

def wm(text: str) -> str:
    return f"{text}\n\n_— luqman on fire 🔥_"

def is_owner_or_sudo(user_id: int) -> bool:
    return user_id == OWNER_ID or user_id in sudo

async def check_bot_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    bot_member = await context.bot.get_chat_member(chat_id=update.effective_chat.id, user_id=context.bot.id)
    if bot_member.status in ['administrator', 'creator']:
        return True
    await update.message.reply_text(
        wm("❌ **Amri Imeshindwa!**\nBot linahitaji nguvu ya **U-Admin** kwenye kundi hili ili kufanya kazi."),
        parse_mode="Markdown"
    )
    return False

# --- COMMAND HANDLERS ---

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    start_text = """████████████████████████
 🩸 𓊈𒆜 𝐋𝐔𝐐𝐌𝐀𝐍 𝐗 𝐌𝐃 𒆜𓊉 🩸
████████████████████████

👋 Hello! Welcome to the hellfire automation gateway.

╔════════ STATUS ════════╗
 ⚡ Bot     : Active
 🔮 Version : v5.0.0
 👤 Owner   : LUQMAN SJ
 ⛓️ Prefix  : /
╚════════端══════════════╝

╔════════ ACTIONS ═══════╗
 ➽ ⚔️ /menu   ──> Control Room
 ➽ 🛡️ /admins ──> Staff Power
 ➽ 📦 /ginfo  ──> Group Insight
 ➽ ❓ /help   ──> Core Manual
╚════════════════════════╝

🪓 Type /menu to view systems.

⚡ LUQMAN ON FIRE 🔥"""
    await update.message.reply_text(start_text)

async def menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    menu_text = f"""
💀 {BOT_NAME} 💀
👑 Owner: {OWNER_NAME}
🌍 Country: Tanzania
⚡ Prefix: /
🔥 Mode: {MODE}

💀 GROUP CONTROL
/ban, /unban, /kick
/mute, /unmute, /warn
/mute_group on/off
/antilink on/off
/antisticker on/off
/admins
/ginfo
/id

🎮 MICHEZO & MANJONJO
/slots, /dice, /dart
/football, /love, /joke

👑 OWNER SYSTEM
/alive, /ping, /owner
"""
    await update.message.reply_text(menu_text)
    

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

# --- NEW FUN & GAME COMMANDS ---

async def slots_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_dice(emoji="🎰")
    val = msg.dice.value
    if val in [1, 22, 43, 64]:
        await update.message.reply_text(wm("🎉 **JACKPOT!!!** Umeshinda mchezo wa Casino! 🏆💰"))
    else:
        await update.message.reply_text(wm("🎰 **Casino Matokeo:** Jaribu tena bahati yako!"))

async def dice_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_dice(emoji="🎲")
    await update.message.reply_text(wm(f"🎲 **Kete Imeangukia:** Namba {msg.dice.value}"))

async def dart_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_dice(emoji="🎯")
    val = msg.dice.value
    if val == 6:
        await update.message.reply_text(wm("🎯 **Katikati ya Shabaha!** Wewe ni sniper hatari! 🔥"))
    else:
        await update.message.reply_text(wm(f"🎯 **Umelenga:** Pointi {val}/6. Ongeza umakini!"))

async def football_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_dice(emoji="⚽")
    val = msg.dice.value
    if val in [3, 4, 5]:
        await update.message.reply_text(wm("⚽ **GOOOOOOAL!!!** Shuti kali limejaa nyavuni! 🏃‍♂️💨"))
    else:
        await update.message.reply_text(wm("🧤 **Imeokolewa!** Golikipa amedaka au mpira umetoka nje! 😂"))

async def love_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user1 = update.effective_user.first_name
    if update.message.reply_to_message:
        user2 = update.message.reply_to_message.from_user.first_name
    else:
        await update.message.reply_text(wm("⚠️ **Maelekezo:** Reply kwenye ujumbe wa mtu unayetaka kupima nae upendo kisha andika `/love`"))
        return

    percentage = random.randint(1, 100)
    
    if percentage <= 20: comment = LOVE_COMMENTS[0]
    elif percentage <= 50: comment = LOVE_COMMENTS[1]
    elif percentage <= 75: comment = LOVE_COMMENTS[2]
    elif percentage <= 90: comment = LOVE_COMMENTS[3]
    else: comment = LOVE_COMMENTS[4]

    love_report = f"❤️ **MITA YA UPENDO (LOVE MATCH)** ❤️\n\n👩‍❤️‍👨 **{user1}** +  **{user2}**\n\n📊 **Asilimia:** {percentage}%\n💬 **Tathmini:** {comment}"
    await update.message.reply_text(wm(love_report))

async def joke_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    joke = random.choice(VICHEKESHO)
    await update.message.reply_text(wm(f"😂 **KICHEKESHO CHA LEO:**\n\n{joke}"))

# --- PROTECTION & MODERATION COMMANDS ---

async def ban_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner_or_sudo(update.effective_user.id): return
    if not update.effective_chat.type in ['group', 'supergroup']: return
    if not await check_bot_admin(update, context): return

    if update.message.reply_to_message:
        user_id = update.message.reply_to_message.from_user.id
        name = update.message.reply_to_message.from_user.first_name
        try:
            await context.bot.ban_chat_member(chat_id=update.effective_chat.id, user_id=user_id)
            await update.message.reply_text(wm(f"☠️ **BAN:** {name} amefukuzwa rasmi na hatawahi kurudi! 🚫"))
        except BadRequest:
            await update.message.reply_text(wm("❌ Siwezi kum-ban huyu (huenda ni admin au yuko juu yangu)."))
    else:
        await update.message.reply_text(wm("⚠️ **Maelekezo:** Reply kwenye ujumbe wa mtu kisha andika `/ban`"))

async def unban_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner_or_sudo(update.effective_user.id): return
    if not update.effective_chat.type in ['group', 'supergroup']: return
    if not await check_bot_admin(update, context): return

    user_id = None
    if update.message.reply_to_message:
        user_id = update.message.reply_to_message.from_user.id
    elif context.args:
        try: user_id = int(context.args[0])
        except ValueError: pass

    if user_id:
        try:
            await context.bot.unban_chat_member(chat_id=update.effective_chat.id, user_id=user_id)
            await update.message.reply_text(wm("✅ **UNBAN:** Mtumiaji amesamehewa! Sasa hivi anaweza kujiunga tena."))
        except BadRequest:
            await update.message.reply_text(wm("❌ Imeshindwa kum-unban. Hakikisha ID ni sahihi."))
    else:
        await update.message.reply_text(wm("⚠️ **Maelekezo:** Reply kwenye ujumbe wake au andika `/unban [ID_ya_Mtu]`"))

async def mute_user_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner_or_sudo(update.effective_user.id): return
    if not update.effective_chat.type in ['group', 'supergroup']: return
    if not await check_bot_admin(update, context): return

    if update.message.reply_to_message:
        user_id = update.message.reply_to_message.from_user.id
        name = update.message.reply_to_message.from_user.first_name
        try:
            await context.bot.restrict_chat_member(
                chat_id=update.effective_chat.id,
                user_id=user_id,
                permissions=ChatPermissions(can_send_messages=False)
            )
            await update.message.reply_text(wm(f"🤐 **MUTE:** {name} amefungwa mdomo! Hawezi kuchat humu kwanza."))
        except BadRequest:
            await update.message.reply_text(wm("❌ Siwezi kumnyamazisha mtu huyu."))
    else:
        await update.message.reply_text(wm("⚠️ **Maelekezo:** Reply kwenye ujumbe wa mtu kisha andika `/mute`"))

async def unmute_user_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner_or_sudo(update.effective_user.id): return
    if not update.effective_chat.type in ['group', 'supergroup']: return
    if not await check_bot_admin(update, context): return

    if update.message.reply_to_message:
        user_id = update.message.reply_to_message.from_user.id
        name = update.message.reply_to_message.from_user.first_name
        try:
            await context.bot.restrict_chat_member(
                chat_id=update.effective_chat.id,
                user_id=user_id,
                permissions=ChatPermissions(
                    can_send_messages=True, can_send_audios=True, can_send_documents=True,
                    can_send_photos=True, can_send_videos=True, can_send_video_notes=True,
                    can_send_voice_notes=True, can_send_polls=True, can_send_other_messages=True,
                    can_add_web_page_previews=True
                )
            )
            await update.message.reply_text(wm(f"🔊 **UNMUTE:** {name} amerudishiwa sauti! Sasa anaweza kuendelea kuchat."))
        except BadRequest:
            await update.message.reply_text(wm("❌ Imeshindwa kumfungulia mdomo."))
    else:
        await update.message.reply_text(wm("⚠️ **Maelekezo:** Reply kwenye ujumbe wa mtu kisha andika `/unmute`"))

async def warn_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner_or_sudo(update.effective_user.id): return
    if not update.effective_chat.type in ['group', 'supergroup']: return
    if not await check_bot_admin(update, context): return

    chat_id = update.effective_chat.id

    if update.message.reply_to_message:
        user_id = update.message.reply_to_message.from_user.id
        name = update.message.reply_to_message.from_user.first_name
        
        if chat_id not in warns: warns[chat_id] = {}
        warns[chat_id][user_id] = warns[chat_id].get(user_id, 0) + 1
        
        current_warns = warns[chat_id][user_id]
        
        if current_warns >= 3:
            try:
                await context.bot.ban_chat_member(chat_id=chat_id, user_id=user_id)
                warns[chat_id][user_id] = 0
                await update.message.reply_text(wm(f"🚨 **WARN 3/3:** {name} amefikisha onyo la tatu, amepigwa BAN kiotomatiki! ☠️"))
            except BadRequest:
                await update.message.reply_text(wm("❌ Amefikisha onyo la 3 lakini siwezi kumfukuza (ni admin)."))
        else:
            await update.message.reply_text(wm(f"⚠️ **ONYO:** {name} umepewa onyo! ({current_warns}/3). Ukifikisha matatu unasepa!"))
    else:
        await update.message.reply_text(wm("⚠️ **Maelekezo:** Reply kwenye ujumbe wa mtu kisha andika `/warn`"))

async def kick_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner_or_sudo(update.effective_user.id): return
    if not update.effective_chat.type in ['group', 'supergroup']: return
    if not await check_bot_admin(update, context): return

    if update.message.reply_to_message:
        user_to_kick = update.message.reply_to_message.from_user.id
        try:
            await context.bot.ban_chat_member(chat_id=update.effective_chat.id, user_id=user_to_kick)
            await context.bot.unban_chat_member(chat_id=update.effective_chat.id, user_id=user_to_kick)
            await update.message.reply_text(wm("🪓 **KICK:** Mtumiaji ametolewa kwenye kundi! (Anaweza kurudi akialikwa upya)."))
        except BadRequest:
            await update.message.reply_text(wm("❌ Siwezi kumtoa mtu huyu."))
    else:
        await update.message.reply_text(wm("⚠️ **Maelekezo:** Reply kwenye ujumbe wa mtu kisha andika `/kick`"))

# --- AUTOMATION & SYSTEM SYSTEM ---

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

async def mute_group_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if not is_owner_or_sudo(update.effective_user.id): return
    if not await check_bot_admin(update, context): return

    if context.args and context.args[0] in ["on", "off"]:
        mute_group[chat_id] = context.args[0] == "on"
        await update.message.reply_text(wm(f"✅ **Mabadiliko:** Group Mute imewekwa **{context.args[0].upper()}**!"), parse_mode="Markdown")
    else:
        await update.message.reply_text(wm("⚠️ Kosa! Tumia: `/mute_group on` au `/mute_group off`"), parse_mode="Markdown")

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
    
    if mute_group.get(chat_id) and not is_owner_or_sudo(user_id):
        try: await message.delete()
        except BadRequest: pass
        return

    if antisticker.get(chat_id) and message.sticker and not is_owner_or_sudo(user_id):
        try: await message.delete()
        except BadRequest: pass
        return

    if antilink.get(chat_id) and message.text and ("https://" in message.text or "http://" in message.text or "t.me" in message.text) and not is_owner_or_sudo(user_id):
        try:
            await message.delete()
            await message.chat.send_message(f"⚠️ @{message.from_user.username or message.from_user.first_name} **Links haziruhusiwi hapa!**")
        except BadRequest: pass
        return

def main():
    app = Application.builder().token(TOKEN).build()

    # Core commands
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("menu", menu_command))
    app.add_handler(CommandHandler("alive", alive_command))
    app.add_handler(CommandHandler("ping", ping_command))
    app.add_handler(CommandHandler("owner", owner_command))
    app.add_handler(CommandHandler("id", id_command))
    
    # Amri za Michezo na Manjonjo Mapya
    app.add_handler(CommandHandler("slots", slots_command))
    app.add_handler(CommandHandler("dice", dice_command))
    app.add_handler(CommandHandler("dart", dart_command))
    app.add_handler(CommandHandler("football", football_command))
    app.add_handler(CommandHandler("love", love_command))
    app.add_handler(CommandHandler("joke", joke_command))
    
    # Moderation
    app.add_handler(CommandHandler("ban", ban_command))
    app.add_handler(CommandHandler("unban", unban_command))
    app.add_handler(CommandHandler("mute", mute_user_command))
    app.add_handler(CommandHandler("unmute", unmute_user_command))
    app.add_handler(CommandHandler("warn", warn_command))
    app.add_handler(CommandHandler("kick", kick_command))
    
    # Group settings
    app.add_handler(CommandHandler("antilink", antilink_command))
    app.add_handler(CommandHandler("antisticker", antisticker_command))
    app.add_handler(CommandHandler("mute_group", mute_group_command))
    app.add_handler(CommandHandler("admins", admins_command))
    app.add_handler(CommandHandler("ginfo", ginfo_command))

    # Message Handlers na Text Filters
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, handle_incoming_messages))
    
    # Amri zisizojulikana (Unknown commands)
    app.add_handler(MessageHandler(filters.COMMAND, unknown_command))

    # Kuwasha Bot
    print("Bot imewashwa rasmi... Run polling...")
    app.run_polling()

if __name__ == '__main__':
    main()
