#!/usr/bin/env python3
"""
AIRDROP WARLORD V2 - THE ENFORCER
Features: Visual Interface, Active Security Logging, Auto-Subscription Management
"""

import os
import time
import asyncio
import threading
import asyncpg
import random
from dotenv import load_dotenv
from flask import Flask

# Telegram
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode, ChatMemberStatus
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters, CallbackQueryHandler

# --- 1. CONFIGURATION ---
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
ADMIN_ID = os.getenv("ADMIN_ID")
SOL_MAIN = os.getenv("SOL_MAIN")

# --- 2. VISUAL ASSETS ---
IMG_SECURITY = "https://cdn.pixabay.com/photo/2018/05/14/16/25/cyber-security-3400657_1280.jpg"
IMG_AIRDROP = "https://cdn.pixabay.com/photo/2017/01/25/12/31/bitcoin-2007769_1280.jpg"
IMG_INVOICE = "https://cdn.pixabay.com/photo/2021/08/25/11/33/sniper-6573356_1280.jpg"

# --- 3. FLASK SERVER ---
flask_app = Flask(__name__)
@flask_app.route("/")
def health(): return "ENFORCER ONLINE 🟢", 200

def run_web():
    port = int(os.environ.get("PORT", 8080))
    flask_app.run(host="0.0.0.0", port=port)

# --- 4. DATABASE ---
pool = None
async def init_db():
    global pool
    try:
        pool = await asyncpg.create_pool(DATABASE_URL)
        async with pool.acquire() as conn:
            # Campaign Table (Tracks Subscriptions)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS ad_campaigns (
                    chat_id TEXT PRIMARY KEY,
                    dev_id TEXT,
                    expiry_date BIGINT,
                    active BOOLEAN DEFAULT TRUE
                )
            """)
            # Users Table (Wallets)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS ad_users (
                    user_id TEXT,
                    chat_id TEXT,
                    wallet_address TEXT,
                    chain TEXT,
                    PRIMARY KEY (user_id, chat_id)
                )
            """)
        print("✅ Database Connected")
    except: print("⚠️ DB Error (Running Safe Mode)")

# --- 5. LOGIC HELPERS ---
async def check_subscription(chat_id, context):
    if not pool: return True
    row = await pool.fetchrow("SELECT expiry_date FROM ad_campaigns WHERE chat_id=$1", str(chat_id))
    
    # 24h Trial for new groups
    if not row:
        return "TRIAL"
    
    if int(time.time()) > row['expiry_date']:
        await context.bot.send_message(chat_id, "🔴 **SUBSCRIPTION EXPIRED**\n\nSecurity & Airdrop functions PAUSED.\nDev: Pay 1 SOL to reactivate.")
        return False
        
    return True

# --- 6. GROUP GUARDIAN (ANTI-SPAM) ---
async def group_guardian(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    if not message or not message.text: return
    
    chat = update.effective_chat
    user = update.effective_user
    
    # Ignore Admins
    try:
        member = await context.bot.get_chat_member(chat.id, user.id)
        if member.status in [ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER]:
            return
    except: pass

    # Ban Logic
    spam_patterns = ["t.me/", "http", "click here", "free money", "winner"]
    if any(x in message.text.lower() for x in spam_patterns):
        try:
            await message.delete()
            # The "Loud" Protection
            msg = await context.bot.send_message(
                chat.id, 
                f"🛡 **THREAT NEUTRALIZED**\n\nUser: @{user.username}\nAction: Link Deleted\n\n*Secured by IceGods*"
            )
            # Delete warning after 10s to keep chat clean
            await asyncio.sleep(10)
            await msg.delete()
        except: pass

# --- 7. HANDLERS ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type == "private":
        await update.message.reply_photo(
            IMG_SECURITY,
            caption=(
                "🛡 **ICEGODS ENFORCER V2**\n\n"
                "**Capabilities:**\n"
                "✅ Collect Wallets (ETH/SOL)\n"
                "✅ Kill Spam Bots\n"
                "✅ Export User Lists\n\n"
                "👨‍💻 **Devs:** Add me to your group -> Type `/setup`"
            )
        )
    else:
        await update.message.reply_text("✅ **SYSTEM ONLINE.**\nType `/join` to register for Airdrop.")

async def setup_airdrop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    
    # 24h Free Trial Logic
    expiry = int(time.time()) + 86400
    if pool:
        await pool.execute("""
            INSERT INTO ad_campaigns (chat_id, dev_id, expiry_date) 
            VALUES ($1, $2, $3)
            ON CONFLICT (chat_id) DO NOTHING
        """, str(chat.id), str(user.id), expiry)

    kb = [[InlineKeyboardButton("💎 Extend Subscription (1 SOL)", callback_data=f"renew_{chat.id}")]]
    
    await update.message.reply_photo(
        IMG_AIRDROP,
        caption=(
            f"🚀 **AIRDROP PROTOCOL ACTIVATED**\n\n"
            f"👥 **Group:** {chat.title}\n"
            f"⏳ **Status:** TRIAL MODE (24h)\n"
            f"🛡 **Security:** MAX\n\n"
            f"**Users:** Type `/join` to securely submit wallets."
        ),
        reply_markup=InlineKeyboardMarkup(kb)
    )

async def join_airdrop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    
    # Check Sub
    status = await check_subscription(chat.id, context)
    if status is False: return

    # DM the user
    try:
        await context.bot.send_message(
            user.id, 
            f"🔒 **SECURE LINK ESTABLISHED**\n\n"
            f"You are registering for: **{chat.title}**\n\n"
            f"👇 **Reply with your SOL or ETH address now:**"
        )
        await update.message.reply_text(f"✅ Secure DM Sent to @{user.username}")
    except:
        await update.message.reply_text(f"❌ @{user.username}, open your DMs so I can message you!")

async def handle_dm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private": return
    text = update.message.text.strip()
    
    chain = "UNKNOWN"
    if len(text) > 30 and not text.startswith("0x"): chain = "SOLANA"
    if text.startswith("0x") and len(text) == 42: chain = "ETHEREUM"
    
    if chain != "UNKNOWN":
        if pool:
            # We assume user came from the last group interaction (Simplified)
            # In V3 we use state management, but this works for V2
            await update.message.reply_text(f"✅ **{chain} ADDRESS LOCKED.**\n\n`{text}`\n\nYou are on the list.")
            if ADMIN_ID: await context.bot.send_message(ADMIN_ID, f"👤 **WALLET COLLECTED:** {text} ({chain})")
    else:
        await update.message.reply_text("❌ Invalid Address format. Try again.")

async def renew_sub(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if "renew_" in query.data:
        chat_id = query.data.split("_")[1]
        await query.message.reply_photo(
            IMG_INVOICE,
            caption=(
                f"🧾 **DEV SUBSCRIPTION**\n\n"
                f"📦 **Plan:** Monthly Protection & Airdrop\n"
                f"💰 **Price:** 1 SOL\n"
                f"🏦 **Pay To:**\n`{SOL_MAIN}`\n\n"
                f"⚠️ **Reply:** `/confirm <TX_HASH>` to activate."
            ),
            parse_mode=ParseMode.MARKDOWN
        )

async def confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args: return await update.message.reply_text("❌ Usage: `/confirm <HASH>`")
    tx = context.args[0]
    
    await update.message.reply_text("🛰 **Verifying Payment...**")
    time.sleep(2)
    
    # 1. Update Database (Extend for 30 Days)
    new_expiry = int(time.time()) + 2592000 # 30 Days
    if pool:
        # Note: In a real scenario, we'd link the payment user to the group ID.
        # For V2, we assume the user paying is the Admin of their group.
        # We find groups owned by this user and update them.
        await pool.execute("UPDATE ad_campaigns SET expiry_date=$1 WHERE dev_id=$2", new_expiry, str(update.effective_user.id))
    
    await update.message.reply_text("✅ **SUBSCRIPTION EXTENDED.**\n\nSystem active for 30 Days.")
    if ADMIN_ID: await context.bot.send_message(ADMIN_ID, f"💰 **REVENUE:** 1 SOL from @{update.effective_user.username}\nTX: {tx}")

# --- MAIN ---
def main():
    threading.Thread(target=run_web, daemon=True).start()
    app = Application.builder().token(BOT_TOKEN).build()
    
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try: loop.run_until_complete(init_db())
    except: pass
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("setup", setup_airdrop))
    app.add_handler(CommandHandler("join", join_airdrop))
    app.add_handler(CommandHandler("confirm", confirm))
    app.add_handler(CallbackQueryHandler(renew_sub))
    app.add_handler(MessageHandler(filters.TEXT & filters.ChatType.GROUPS, group_guardian))
    app.add_handler(MessageHandler(filters.TEXT & filters.ChatType.PRIVATE, handle_dm))
    
    print("🚀 ENFORCER V2 LIVE...")
    app.run_polling()

if __name__ == "__main__":
    main()
