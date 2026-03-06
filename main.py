#!/usr/bin/env python3
"""
ICE REIGN MACHINE V5 - STABLE VERSION
"""

import os
import asyncio
import logging
import threading
import aiosqlite
from datetime import datetime, timedelta

from flask import Flask, request, jsonify

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode, ChatMemberStatus
from telegram.ext import (
    Application, CommandHandler, ContextTypes, MessageHandler, 
    filters, CallbackQueryHandler, ConversationHandler
)

import aiohttp
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- CONFIG ---
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = os.getenv("ADMIN_ID")
SOL_MAIN = os.getenv("SOL_MAIN")
PORT = int(os.getenv("PORT", 8080))
SUBSCRIPTION_PRICE = float(os.getenv("SUBSCRIPTION_PRICE", 100))
HELIUS_API_KEY = os.getenv("SOLANA_RPC", "").split("api-key=")[1] if "api-key=" in os.getenv("SOLANA_RPC", "") else ""

DB_FILE = "ice_reign.db"
AWAITING_PAYMENT = 1

# --- FLASK ---
flask_app = Flask(__name__)

@flask_app.route("/")
def health():
    return jsonify({
        "status": "ICE REIGN ONLINE",
        "wallet": SOL_MAIN,
        "time": datetime.utcnow().isoformat()
    }), 200

def run_flask():
    flask_app.run(host='0.0.0.0', port=PORT, threaded=True)

# --- DATABASE ---
async def init_db():
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS dev_subscriptions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id TEXT UNIQUE NOT NULL,
                username TEXT,
                tier TEXT DEFAULT 'none',
                status TEXT DEFAULT 'inactive',
                subscription_end TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS platform_payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                dev_telegram_id TEXT NOT NULL,
                amount_sol REAL NOT NULL,
                tx_signature TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS protected_groups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                dev_telegram_id TEXT NOT NULL,
                telegram_chat_id TEXT UNIQUE NOT NULL,
                group_name TEXT,
                spam_blocked INTEGER DEFAULT 0,
                is_active INTEGER DEFAULT 1
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS user_engagement (
                group_chat_id TEXT NOT NULL,
                telegram_id TEXT NOT NULL,
                message_count INTEGER DEFAULT 0,
                last_active TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(group_chat_id, telegram_id)
            )
        """)
        await db.commit()
    logger.info("✅ Database ready")

# --- HELIUS ---
async def verify_sol_payment(tx_signature: str, expected_amount: float) -> bool:
    try:
        async with aiohttp.ClientSession() as session:
            url = f"https://api.helius.xyz/v0/transactions/?api-key={HELIUS_API_KEY}"
            async with session.post(url, json={"transactions": [tx_signature]}) as resp:
                if resp.status != 200:
                    return False
                data = await resp.json()
                if not data or data[0].get('err'):
                    return False
                for transfer in data[0].get('nativeTransfers', []):
                    if transfer['toUserAccount'] == SOL_MAIN:
                        amount = float(transfer['amount']) / 1e9
                        return amount >= expected_amount * 0.95
        return False
    except Exception as e:
        logger.error(f"Verify error: {e}")
        return False

# --- HANDLERS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if update.effective_chat.type == "private":
        if str(user.id) == ADMIN_ID:
            async with aiosqlite.connect(DB_FILE) as db:
                async with db.execute("SELECT SUM(amount_sol) as total FROM platform_payments") as cursor:
                    row = await cursor.fetchone()
                    total = row[0] if row[0] else 0
            await update.message.reply_text(
                f"👑 ADMIN\nRevenue: {total:.4f} SOL\nWallet: `{SOL_MAIN}`",
                parse_mode=ParseMode.MARKDOWN
            )
            return
        
        async with aiosqlite.connect(DB_FILE) as db:
            async with db.execute("SELECT * FROM dev_subscriptions WHERE telegram_id = ?", (str(user.id),)) as cursor:
                dev = await cursor.fetchone()
        
        if dev and dev[4] == 'active':
            await update.message.reply_text(
                f"👨‍💻 DASHBOARD\nTier: {dev[3]}\nExpires: {dev[5]}\n\n/activate - Add to group",
                parse_mode=ParseMode.MARKDOWN
            )
        else:
            keyboard = [
                [InlineKeyboardButton(f"💎 Basic - {SUBSCRIPTION_PRICE} SOL", callback_data="sub_basic")],
                [InlineKeyboardButton("👑 Pro - 3 SOL", callback_data="sub_pro")]
            ]
            await update.message.reply_text(
                f"🚀 ICE REIGN MACHINE\n\nAuto-detect + Anti-spam\n\nPay: `{SOL_MAIN}`",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode=ParseMode.MARKDOWN
            )

async def subscription_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    tier = query.data.replace("sub_", "")
    amount = SUBSCRIPTION_PRICE if tier == "basic" else 3.0
    context.user_data['payment'] = {'tier': tier, 'amount': amount}
    await query.edit_message_text(
        f"💳 {tier.upper()}\nSend {amount} SOL to:\n`{SOL_MAIN}`\n\nReply with TX:",
        parse_mode=ParseMode.MARKDOWN
    )
    return AWAITING_PAYMENT

async def process_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tx = update.message.text.strip()
    user = update.effective_user
    payment = context.user_data.get('payment')
    if not payment:
        await update.message.reply_text("Use /start")
        return ConversationHandler.END
    
    await update.message.reply_text("⏳ Verifying...")
    
    if await verify_sol_payment(tx, payment['amount']):
        expiry = datetime.now() + timedelta(days=30)
        async with aiosqlite.connect(DB_FILE) as db:
            await db.execute("""
                INSERT INTO dev_subscriptions (telegram_id, username, tier, status, subscription_end)
                VALUES (?, ?, ?, 'active', ?)
                ON CONFLICT(telegram_id) DO UPDATE SET tier = excluded.tier, status = 'active', subscription_end = excluded.subscription_end
            """, (str(user.id), user.username, payment['tier'], expiry))
            await db.execute("""
                INSERT INTO platform_payments (dev_telegram_id, amount_sol, tx_signature) VALUES (?, ?, ?)
            """, (str(user.id), payment['amount'], tx))
            await db.commit()
        
        await update.message.reply_text(
            f"✅ ACTIVATED!\nTier: {payment['tier']}\nExpires: {expiry.strftime('%Y-%m-%d')}\n\nAdd to group: /activate",
            parse_mode=ParseMode.MARKDOWN
        )
        await context.bot.send_message(ADMIN_ID, f"💰 {payment['amount']} SOL from @{user.username}")
    else:
        await update.message.reply_text("❌ Payment not found")
    return ConversationHandler.END

async def activate_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    if chat.type == "private":
        return await update.message.reply_text("Use in group")
    
    member = await context.bot.get_chat_member(chat.id, user.id)
    if member.status not in [ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER]:
        return await update.message.reply_text("Admin only")
    
    async with aiosqlite.connect(DB_FILE) as db:
        async with db.execute("SELECT * FROM dev_subscriptions WHERE telegram_id = ? AND status = 'active'", (str(user.id),)) as cursor:
            dev = await cursor.fetchone()
        if not dev:
            return await update.message.reply_text("❌ Subscribe first")
        await db.execute("""
            INSERT INTO protected_groups (dev_telegram_id, telegram_chat_id, group_name)
            VALUES (?, ?, ?) ON CONFLICT(telegram_chat_id) DO UPDATE SET is_active = 1
        """, (str(user.id), str(chat.id), chat.title))
        await db.commit()
    
    await update.message.reply_text("✅ GROUP PROTECTED\n🛡 Anti-spam: ON\n🚀 Auto-detect: READY", parse_mode=ParseMode.MARKDOWN)

async def security_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg or not msg.text:
        return
    chat_id = str(update.effective_chat.id)
    user = update.effective_user
    
    async with aiosqlite.connect(DB_FILE) as db:
        async with db.execute("SELECT * FROM protected_groups WHERE telegram_chat_id = ? AND is_active = 1", (chat_id,)) as cursor:
            group = await cursor.fetchone()
        if not group:
            return
        await db.execute("""
            INSERT INTO user_engagement (group_chat_id, telegram_id, message_count, last_active)
            VALUES (?, ?, 1, CURRENT_TIMESTAMP)
            ON CONFLICT(group_chat_id, telegram_id) DO UPDATE SET message_count = message_count + 1, last_active = CURRENT_TIMESTAMP
        """, (chat_id, str(user.id)))
        await db.commit()
    
    try:
        member = await context.bot.get_chat_member(chat_id, user.id)
        if member.status in [ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER]:
            return
    except:
        return
    
    text_lower = msg.text.lower()
    spam = ['dm me', 'http', 't.me/', 'investment', 'forex', 'profit guaranteed']
    if sum(1 for s in spam if s in text_lower) >= 2:
        try:
            await msg.delete()
            w = await context.bot.send_message(chat_id, f"🛡 Spam removed from @{user.username or user.id}", parse_mode=ParseMode.MARKDOWN)
            async with aiosqlite.connect(DB_FILE) as db:
                await db.execute("UPDATE protected_groups SET spam_blocked = spam_blocked + 1 WHERE telegram_chat_id = ?", (chat_id,))
                await db.commit()
            await asyncio.sleep(5)
            await w.delete()
        except:
            pass

# --- MAIN ---
def main():
    # Initialize database first
    asyncio.run(init_db())
    
    # Start web server in background thread
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    logger.info(f"🌐 Web server on port {PORT}")
    
    # Build and run bot
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Conversation handler
    conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(subscription_callback, pattern="^sub_")],
        states={AWAITING_PAYMENT: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_payment)]},
        fallbacks=[]
    )
    
    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(conv_handler)
    application.add_handler(CommandHandler("activate", activate_group))
    application.add_handler(MessageHandler(filters.TEXT & filters.ChatType.GROUPS, security_handler))
    
    logger.info("🚀 BOT STARTED - POLLING ACTIVE")
    logger.info(f"💰 Revenue wallet: {SOL_MAIN}")
    
    # Run the bot (blocking)
    application.run_polling()

if __name__ == "__main__":
    main()
