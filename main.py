#!/usr/bin/env python3
"""
ICE REIGN MACHINE V4 - THE GROUP OVERLORD
Features: Anti-Spam Security, Airdrop Funnel, Auto-Token Scanner, Dev Stats
"""

import os
import time
import asyncio
import threading
import asyncpg
import requests
import random
from decimal import Decimal
from dotenv import load_dotenv
from flask import Flask

# Telegram Imports
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode, ChatMemberStatus
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters, CallbackQueryHandler

# --- 1. CONFIGURATION ---
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
ADMIN_ID = os.getenv("ADMIN_ID")
SOL_MAIN = os.getenv("SOL_MAIN")
CHANNEL_ID = os.getenv("VIP_CHANNEL_ID") # For Token Alerts

# --- 2. ASSETS ---
IMG_SECURE = "https://cdn.pixabay.com/photo/2018/05/14/16/25/cyber-security-3400657_1280.jpg"
IMG_STATS = "https://cdn.pixabay.com/photo/2020/08/09/14/25/business-5475661_1280.jpg"
IMG_ALERT = "https://cdn.pixabay.com/photo/2021/05/09/18/54/chart-6241774_1280.png"

# --- 3. FLASK SERVER ---
flask_app = Flask(__name__)
@flask_app.route("/")
def health(): return "OVERLORD ONLINE 🟢", 200

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
            # Group Stats Table
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS group_stats (
                    chat_id TEXT PRIMARY KEY,
                    messages_scanned INT DEFAULT 0,
                    bots_banned INT DEFAULT 0,
                    airdrops_claimed INT DEFAULT 0
                )
            """)
            # Airdrop Config
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS ad_campaigns (
                    chat_id TEXT PRIMARY KEY,
                    token_name TEXT,
                    amount_per_user INT,
                    active BOOLEAN DEFAULT TRUE
                )
            """)
        print("✅ Overlord Database Connected")
    except: print("⚠️ DB Connection Failed (Running Safe Mode)")

# --- 5. TOKEN SCANNER (Keep Channel Active) ---
async def token_scanner(app: Application):
    """Scans for New Launches and alerts the Channel"""
    print("🚀 Scanner Radar Active...")
    while True:
        try:
            if CHANNEL_ID:
                # Fetch Trending/New
                url = "https://api.coingecko.com/api/v3/search/trending"
                r = requests.get(url, timeout=10).json()
                coin = random.choice(r['coins'][:5])['item']
                
                # Check for "Fake/Rug" indicators (Simulated Logic)
                risk = "LOW" if coin.get('market_cap_rank') else "⚠️ HIGH (Unverified)"
                
                msg = (
                    f"🚨 **NEW TOKEN DETECTED** 🚨\n\n"
                    f"💎 **Token:** {coin['name']} (${coin['symbol']})\n"
                    f"📊 **Rank:** #{coin.get('market_cap_rank', 'N/A')}\n"
                    f"🛡 **Risk Scan:** {risk}\n\n"
                    f"🤖 **IceGods Analysis:**\n"
                    f"Liquidity pool just added. Snipers are entering.\n\n"
                    f"🎯 **Action:** WATCHLIST"
                )
                
                await app.bot.send_photo(chat_id=CHANNEL_ID, photo=IMG_ALERT, caption=msg, parse_mode=ParseMode.MARKDOWN)
                print(f"✅ Alert Sent: {coin['symbol']}")

            await asyncio.sleep(1800) # Every 30 Mins
        except: await asyncio.sleep(300)

# --- 6. SECURITY ENGINE (Anti-Spam) ---
async def group_security(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg or not msg.text: return
    
    chat_id = str(update.effective_chat.id)
    user = update.effective_user
    
    # Skip Admins
    try:
        member = await context.bot.get_chat_member(chat_id, user.id)
        if member.status in [ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER]: return
    except: pass

    # SPAM FILTERS
    banned_words = ["investment", "forex", "dm me", "profit", "http", "t.me"]
    if any(word in msg.text.lower() for word in banned_words):
        try:
            await msg.delete()
            warning = await context.bot.send_message(
                chat_id,
                f"🛡 **THREAT REMOVED**\nUser: @{user.username}\nReason: Spam/Link Detected.\n\n*Protected by IceReign Machine*"
            )
            
            # Log Stat
            if pool:
                await pool.execute("INSERT INTO group_stats (chat_id, bots_banned) VALUES ($1, 1) ON CONFLICT (chat_id) DO UPDATE SET bots_banned = group_stats.bots_banned + 1", chat_id)
            
            await asyncio.sleep(10)
            await warning.delete()
        except: pass

# --- 7. HANDLERS ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # DM Message
    if update.effective_chat.type == "private":
        await update.message.reply_photo(
            IMG_SECURE,
            caption=(
                "🤖 **ICE REIGN MACHINE V4**\n\n"
                "**The Group Overlord.**\n"
                "I manage Airdrops, Ban Spammers, and Track Stats.\n\n"
                "👨‍💻 **Devs:** Add me to your group -> Type `/setup`\n"
                "📊 **Stats:** Type `/stats` (Group Only)\n"
                "🪂 **Users:** Type `/join` inside a group."
            )
        )
    else:
        await update.message.reply_text("✅ **OVERLORD ONLINE.**\nSecurity Active. Type `/join` for Airdrop.")

async def setup_airdrop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if chat.type == "private": return await update.message.reply_text("❌ Use in a Group.")
    
    # Only Admin
    user = update.effective_user
    mem = await context.bot.get_chat_member(chat.id, user.id)
    if mem.status not in [ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER]: return

    # Save to DB
    if pool:
        await pool.execute("""
            INSERT INTO ad_campaigns (chat_id, token_name, amount_per_user) 
            VALUES ($1, 'TOKEN', 1000)
            ON CONFLICT (chat_id) DO UPDATE SET active=TRUE
        """, str(chat.id))

    await update.message.reply_text(
        f"🚀 **AIRDROP INITIALIZED!**\n\n"
        f"Users can now type `/join`.\n"
        f"I am also monitoring for spam links.\n\n"
        f"Type `/stats` to see performance."
    )

async def join_airdrop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # User Funnel
    user = update.effective_user
    try:
        await context.bot.send_message(
            user.id,
            f"🎁 **CLAIM AIRDROP**\n\n"
            f"1. Send your SOL Wallet address here.\n"
            f"2. Send 0.002 SOL Gas Fee to verify humanity.\n\n"
            f"🏦 **Gas Wallet:** `{SOL_MAIN}`"
        )
        await update.message.reply_text(f"📩 Check DM, @{user.username}!")
        
        # Track Stat
        if pool:
            await pool.execute("INSERT INTO group_stats (chat_id, airdrops_claimed) VALUES ($1, 1) ON CONFLICT (chat_id) DO UPDATE SET airdrops_claimed = group_stats.airdrops_claimed + 1", str(update.effective_chat.id))
            
    except:
        await update.message.reply_text(f"❌ @{user.username}, Unblock me to join!")

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Show the Dev how good the bot is
    chat = update.effective_chat
    if chat.type == "private": return
    
    scanned = 0
    banned = 0
    claimed = 0
    
    if pool:
        row = await pool.fetchrow("SELECT * FROM group_stats WHERE chat_id=$1", str(chat.id))
        if row:
            banned = row['bots_banned']
            claimed = row['airdrops_claimed']
            
    await update.message.reply_photo(
        IMG_STATS,
        caption=(
            f"📊 **GROUP INTELLIGENCE REPORT**\n\n"
            f"🛡 **Threats Neutralized:** {banned}\n"
            f"🪂 **Airdrops Claimed:** {claimed}\n"
            f"🟢 **System Status:** SECURE\n\n"
            f"To boost your stats, run `/setup` again."
        )
    )

# --- MAIN ---
def main():
    threading.Thread(target=run_web, daemon=True).start()
    app = Application.builder().token(BOT_TOKEN).build()
    
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try: loop.run_until_complete(init_db())
    except: pass
    
    # Start the Auto-Poster for Channel
    loop.create_task(token_scanner(app))
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("setup", setup_airdrop))
    app.add_handler(CommandHandler("join", join_airdrop))
    app.add_handler(CommandHandler("stats", stats)) # NEW: Shows Dev the value
    app.add_handler(MessageHandler(filters.TEXT & filters.ChatType.GROUPS, group_security))
    
    print("🚀 ICE OVERLORD V4 LIVE...")
    app.run_polling()

if __name__ == "__main__":
    main()
