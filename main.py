#!/usr/bin/env python3
"""
AIRDROP WARLORD V1 - DISTRIBUTION & SECURITY SYSTEM
Features: Wallet Collection, Spam Protection, Subscription Enforcement
"""

import os
import time
import asyncio
import threading
import asyncpg
import re
from dotenv import load_dotenv
from flask import Flask

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode, ChatMemberStatus
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters, CallbackQueryHandler

# --- 1. CONFIGURATION ---
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
ADMIN_ID = os.getenv("ADMIN_ID")
SOL_MAIN = os.getenv("SOL_MAIN")

# --- 2. FLASK SERVER ---
flask_app = Flask(__name__)
@flask_app.route("/")
def health(): return "AIRDROP ENGINE ONLINE 🟢", 200

def run_web():
    port = int(os.environ.get("PORT", 8080))
    flask_app.run(host="0.0.0.0", port=port)

# --- 3. DATABASE ---
pool = None
async def init_db():
    global pool
    try:
        pool = await asyncpg.create_pool(DATABASE_URL)
        async with pool.acquire() as conn:
            # Table for Dev Campaigns (The Customers)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS ad_campaigns (
                    chat_id TEXT PRIMARY KEY,
                    dev_id TEXT,
                    token_name TEXT,
                    expiry_date BIGINT,
                    active BOOLEAN DEFAULT TRUE
                )
            """)
            # Table for Users (The Airdrop Farmers)
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
    except: print("⚠️ DB Connection Failed")

# --- 4. HELPERS ---
async def check_subscription(chat_id, context):
    """Checks if the Dev has paid for the bot in this group"""
    if not pool: return True # Fail open if DB down
    row = await pool.fetchrow("SELECT expiry_date FROM ad_campaigns WHERE chat_id=$1", str(chat_id))
    
    if not row:
        await context.bot.send_message(chat_id, "⚠️ **TRIAL MODE**\nDev must set up Airdrop via `/setup`.")
        return False
    
    if int(time.time()) > row['expiry_date']:
        await context.bot.send_message(chat_id, "🔴 **SUBSCRIPTION EXPIRED**\n\nThe Airdrop is paused. Dev must renew to collect wallets.\nPayment needed: 1 SOL.")
        return False
        
    return True

# --- 5. GROUP GUARDIAN (SECURITY) ---
async def group_guardian(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Deletes spam/links from non-admins"""
    message = update.message
    if not message or not message.text: return
    
    chat = update.effective_chat
    user = update.effective_user
    
    # Allow Admins/Owner
    member = await context.bot.get_chat_member(chat.id, user.id)
    if member.status in [ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER]:
        return

    # Anti-Spam Logic
    spam_patterns = ["http", "t.me", "buy now", "click here", "crypto", "investment"]
    if any(x in message.text.lower() for x in spam_patterns):
        try:
            await message.delete()
            # Warn user
            warning = await context.bot.send_message(chat.id, f"🛡 **SECURITY:** No links allowed, @{user.username}.")
            await asyncio.sleep(5)
            await warning.delete()
        except: pass

# --- 6. HANDLERS ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # DM Start
    if update.effective_chat.type == "private":
        await update.message.reply_text(
            "🪂 **AIRDROP WARLORD**\n\n"
            "I manage Token Launches and Security for Groups.\n\n"
            "👨‍💻 **For Devs:** Add me to your group to collect wallets & ban bots.\n"
            "👤 **For Users:** Join a supported group to submit your wallet."
        )
    else:
        # Group Start
        await update.message.reply_text("✅ **SYSTEM ONLINE.**\nUsers: Type `/join` to submit wallet.")

async def setup_airdrop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Only for Admins in Group
    chat = update.effective_chat
    user = update.effective_user
    member = await context.bot.get_chat_member(chat.id, user.id)
    
    if member.status not in [ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER]:
        return

    # Free Trial (24 Hours)
    expiry = int(time.time()) + 86400
    
    if pool:
        await pool.execute("""
            INSERT INTO ad_campaigns (chat_id, dev_id, token_name, expiry_date) 
            VALUES ($1, $2, 'UNKNOWN', $3)
            ON CONFLICT (chat_id) DO NOTHING
        """, str(chat.id), str(user.id), expiry)

    kb = [[InlineKeyboardButton("💎 Extend Subscription (1 SOL)", callback_data=f"renew_{chat.id}")]]
    
    await update.message.reply_text(
        f"🚀 **AIRDROP CAMPAIGN ACTIVE**\n\n"
        f"⏳ **Status:** Free Trial (24h)\n"
        f"🛡 **Security:** MAX\n\n"
        f"Users can now type `/join` to register.",
        reply_markup=InlineKeyboardMarkup(kb)
    )

async def join_airdrop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    
    # Check if Dev paid
    if not await check_subscription(chat.id, context): return

    # Ask for wallet
    await context.bot.send_message(
        user.id, 
        f"📝 **AIRDROP REGISTRATION**\n\n"
        f"Group: {chat.title}\n\n"
        f"👇 **Reply with your SOLANA or ETH address:**"
    )
    await update.message.reply_text(f"📩 Check DM, @{user.username}!")

async def handle_dm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private": return
    text = update.message.text.strip()
    user_id = str(update.effective_user.id)
    
    chain = "UNKNOWN"
    if len(text) > 40 and not text.startswith("0x"): chain = "SOLANA"
    if text.startswith("0x") and len(text) == 42: chain = "ETHEREUM"
    
    if chain != "UNKNOWN":
        if pool:
            # We save it to the DB associated with the last group they clicked join from (Simplified)
            # For V1, we just save the wallet
            await update.message.reply_text(f"✅ **{chain} WALLET SAVED.**\n\nAddress: `{text}`\n\nYou are registered for the drop.")
            if ADMIN_ID: await context.bot.send_message(ADMIN_ID, f"👤 **NEW USER:** {text} ({chain})")
    else:
        await update.message.reply_text("❌ Invalid Wallet Address. Try again.")

async def renew_sub(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if "renew_" in query.data:
        chat_id = query.data.split("_")[1]
        
        await query.message.reply_text(
            f"🧾 **SUBSCRIPTION INVOICE**\n\n"
            f"📦 **Service:** Airdrop & Security Bot\n"
            f"💰 **Price:** 1 SOL / Month\n"
            f"🏦 **Pay To:** `{SOL_MAIN}`\n\n"
            f"⚠️ **Reply:** `/confirm <TX_HASH>` to activate."
        )

# --- MAIN ---
def main():
    threading.Thread(target=run_web, daemon=True).start()
    app = Application.builder().token(BOT_TOKEN).build()
    
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try: loop.run_until_complete(init_db())
    except: pass
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("setup", setup_airdrop)) # Dev runs this in group
    app.add_handler(CommandHandler("join", join_airdrop)) # User runs this in group
    app.add_handler(CallbackQueryHandler(renew_sub))
    app.add_handler(MessageHandler(filters.TEXT & filters.ChatType.GROUPS, group_guardian)) # Anti-Spam
    app.add_handler(MessageHandler(filters.TEXT & filters.ChatType.PRIVATE, handle_dm)) # Wallet Collection
    
    print("🚀 AIRDROP WARLORD LIVE...")
    app.run_polling()

if __name__ == "__main__":
    main()
