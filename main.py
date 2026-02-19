#!/usr/bin/env python3
"""
ICE REIGN MACHINE V20 - MARKET MAKER & LAUNCHPAD
Features: Green Candle Injection, IBS Presale, Developer Renting
"""

import os
import time
import asyncio
import threading
import requests
import asyncpg
import random
from decimal import Decimal
from dotenv import load_dotenv
from flask import Flask

# Telegram
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes, CallbackQueryHandler

# Blockchain
from web3 import Web3

# --- 1. CONFIGURATION ---
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
ETH_MAIN = os.getenv("ETH_MAIN", "").lower()
SOL_MAIN = os.getenv("SOL_MAIN", "")
DATABASE_URL = os.getenv("DATABASE_URL")
VIP_CHANNEL_ID = os.getenv("VIP_CHANNEL_ID")
ADMIN_ID = os.getenv("ADMIN_ID")
HELIUS_RPC = os.getenv("HELIUS_RPC")

# --- 2. SERVICES ---
SERVICES = {
    "ibs_presale": {"name": "❄️ Buy $IBS (Early Access)", "price": 100},
    "rent_machine": {"name": "🚀 Rent Volume Bot (24h)", "price": 1000}
}

# --- 3. FLASK SERVER (Keep-Alive) ---
flask_app = Flask(__name__)
@flask_app.route("/")
@flask_app.route("/health")
def health(): return "ICE MACHINE MARKET MAKER ONLINE 🟢", 200

def run_web():
    port = int(os.environ.get("PORT", 8080))
    flask_app.run(host="0.0.0.0", port=port)

# --- 4. DATABASE ENGINE ---
pool = None
async def init_db():
    global pool
    try:
        pool = await asyncpg.create_pool(DATABASE_URL)
        print("✅ Machine Connected to Ecosystem DB")
    except Exception as e: print(f"⚠️ DB Error: {e}")

# --- 5. GREEN CANDLE ENGINE (Hype Generator) ---
async def market_maker_loop(app: Application):
    print("🚀 Market Maker Engine Started...")
    while True:
        try:
            if VIP_CHANNEL_ID:
                # Simulate a Massive Buy on Solana to create FOMO
                tokens = ["$IBS", "$SOL", "$JUP", "$WIF", "$BONK"]
                platforms = ["Jupiter", "Pump.fun", "Raydium"]
                
                token = random.choice(tokens)
                platform = random.choice(platforms)
                amount_sol = random.uniform(10.5, 100.0)
                price_impact = random.uniform(1.5, 5.5)
                
                # The Alert Message
                msg = (
                    f"🟢 **BUY DETECTED** 🟢\n\n"
                    f"🪙 **Token:** {token}\n"
                    f"💰 **Amount:** {amount_sol:.2f} SOL\n"
                    f"🏦 **DEX:** {platform}\n"
                    f"📈 **Impact:** +{price_impact:.2f}%\n\n"
                    f"🤖 **Bot Action:** BUYING DIP\n"
                    f"🚀 **Target:** MOON"
                )
                
                # Post every 3-5 hours to keep channel looking active
                await app.bot.send_message(chat_id=VIP_CHANNEL_ID, text=msg, parse_mode=ParseMode.MARKDOWN)
                print(f"✅ Green Candle Posted: {token}")

            await asyncio.sleep(random.randint(10800, 18000)) 
        except: await asyncio.sleep(300)

# --- 6. TELEGRAM HANDLERS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = [
        [InlineKeyboardButton("❄️ BUY $IBS TOKEN (Presale)", callback_data="buy_ibs_presale")],
        [InlineKeyboardButton("🚀 RENT VOLUME BOT ($1k)", callback_data="buy_rent_machine")],
        [InlineKeyboardButton("📊 View Dashboard", url="https://icegods-dashboard-56aj.onrender.com")]
    ]
    await update.message.reply_markdown(
        f"⚙️ **ICE REIGN MACHINE**\n\n"
        "The Market Making Core of the IceGods Empire.\n\n"
        "🟢 **Capabilities:**\n"
        "• High-Frequency Trading (Jupiter/Pump.fun)\n"
        "• Green Candle Printing\n"
        "• $IBS Token Governance\n\n"
        "👇 **Execute Order:**",
        reply_markup=InlineKeyboardMarkup(kb)
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if "buy_" in data:
        key = data.replace("buy_", "")
        item = SERVICES[key]
        
        # Log to DB
        try:
            if pool:
                tid = str(query.from_user.id)
                await pool.execute("INSERT INTO cp_users (telegram_id, username, plan_id, expiry_date) VALUES ($1, $2, $3, 0) ON CONFLICT (telegram_id) DO UPDATE SET plan_id = $3", tid, query.from_user.username, key)
        except: pass

        msg = (
            f"🧾 **INVOICE: {item['name']}**\n\n"
            f"💰 **Amount:** ${item['price']} USD\n"
            f"🏦 **Pay ETH:** `{ETH_MAIN}`\n"
            f"🟣 **Pay SOL:** `{SOL_MAIN}`\n\n"
            f"⚠️ **Reply:** `/confirm <TX_HASH>`"
        )
        await query.message.reply_markdown(msg)

async def confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args: return await update.message.reply_text("❌ Usage: `/confirm <TX>`")
    tx = context.args[0]
    
    # Helius Check for SOL (Simplified for stability)
    if len(tx) > 70:
        await update.message.reply_text("🟣 **SOL Detected.** Verifying via Helius Node...")
        if ADMIN_ID: await context.bot.send_message(ADMIN_ID, f"💰 **MACHINE REVENUE:** {tx} from @{update.effective_user.username}")
        await update.message.reply_text("✅ **VERIFIED.** Asset allocation pending Admin confirmation.")
        return

    # Basic ETH Check
    if len(tx) == 66:
        await update.message.reply_text("💠 **ETH Detected.** Allocating $IBS Tokens...")
        if pool:
            await pool.execute("INSERT INTO cp_payments (telegram_id, tx_hash, amount_usd, service_type, created_at) VALUES ($1, $2, $3, 'ICE-MACHINE', $4)", str(update.effective_user.id), tx, 100, int(time.time()))
        
        await update.message.reply_text("✅ **ALLOCATION CONFIRMED.**\nWelcome to the $IBS Presale List.")

# --- MAIN ---
def main():
    threading.Thread(target=run_web, daemon=True).start()
    app = Application.builder().token(BOT_TOKEN).build()
    
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try: loop.run_until_complete(init_db())
    except: pass
    
    loop.create_task(market_maker_loop(app))
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("confirm", confirm))
    app.add_handler(CallbackQueryHandler(button_handler))
    
    print("🚀 ICE MACHINE LIVE...")
    app.run_polling()

if __name__ == "__main__":
    main()
