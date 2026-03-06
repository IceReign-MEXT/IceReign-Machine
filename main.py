#!/usr/bin/env python3
"""
ICE REIGN MACHINE V5 - AUTONOMOUS AIRDROP EMPIRE
"""

import os
import json
import asyncio
import logging
import threading
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Optional, Dict, List
import asyncpg

# Web Framework
from flask import Flask, request, jsonify

# Telegram
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode, ChatMemberStatus
from telegram.ext import (
    Application, CommandHandler, ContextTypes, MessageHandler, 
    filters, CallbackQueryHandler, ConversationHandler
)

# HTTP Client
import aiohttp

# Configuration
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
DATABASE_URL = os.getenv("DATABASE_URL")
PORT = int(os.getenv("PORT", 8080))
SUBSCRIPTION_PRICE = float(os.getenv("SUBSCRIPTION_PRICE", 100))
HELIUS_API_KEY = os.getenv("SOLANA_RPC", "").split("api-key=")[1] if "api-key=" in os.getenv("SOLANA_RPC", "") else ""

pool: Optional[asyncpg.Pool] = None
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
    global pool
    try:
        pool = await asyncpg.create_pool(DATABASE_URL, min_size=2, max_size=5)
        async with pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS dev_subscriptions (
                    id SERIAL PRIMARY KEY,
                    telegram_id TEXT UNIQUE NOT NULL,
                    username TEXT,
                    tier TEXT DEFAULT 'none',
                    status TEXT DEFAULT 'inactive',
                    subscription_end TIMESTAMP,
                    created_at TIMESTAMP DEFAULT NOW()
                )
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS platform_payments (
                    id SERIAL PRIMARY KEY,
                    dev_telegram_id TEXT NOT NULL,
                    amount_sol DECIMAL(20,9) NOT NULL,
                    tx_signature TEXT,
                    created_at TIMESTAMP DEFAULT NOW()
                )
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS protected_groups (
                    id SERIAL PRIMARY KEY,
                    dev_telegram_id TEXT NOT NULL,
                    telegram_chat_id TEXT UNIQUE NOT NULL,
                    group_name TEXT,
                    is_active BOOLEAN DEFAULT TRUE
                )
            """)
        logger.info("✅ DB ready")
        return True
    except Exception as e:
        logger.error(f"DB error: {e}")
        return False

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
                        return float(transfer['amount']) / 1e9 >= expected_amount * 0.95
        return False
    except Exception as e:
        logger.error(f"Verify error: {e}")
        return False

# --- HANDLERS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if update.effective_chat.type == "private":
        if str(user.id) == ADMIN_ID:
            async with pool.acquire() as conn:
                rows = await conn.fetch("SELECT SUM(amount_sol) as total FROM platform_payments")
                total = rows[0]['total'] or 0
            await update.message.reply_text(f"👑 ADMIN\nRevenue: {total:.4f} SOL\nWallet: `{SOL_MAIN}`", parse_mode=ParseMode.MARKDOWN)
            return
        
        async with pool.acquire() as conn:
            dev = await conn.fetchrow("SELECT * FROM dev_subscriptions WHERE telegram_id = $1", str(user.id))
        
        if dev and dev['status'] == 'active':
            await update.message.reply_text(
                f"👨‍💻 DASHBOARD\nTier: {dev['tier']}\nExpires: {dev['subscription_end'].strftime('%Y-%m-%d') if dev['subscription_end'] else 'N/A'}\n\n/activate - Add to group",
                parse_mode=ParseMode.MARKDOWN
            )
        else:
            keyboard = [
                [InlineKeyboardButton(f"💎 Basic - {SUBSCRIPTION_PRICE} SOL", callback_data="sub_basic")],
                [InlineKeyboardButton("👑 Pro - 3 SOL", callback_data="sub_pro")]
            ]
            await update.message.reply_text(
                f"🚀 ICE REIGN MACHINE\n\nAuto-detect + Anti-spam\n\nPay to: `{SOL_MAIN}`",
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
        f"💳 {tier.upper()}\nSend {amount} SOL to:\n`{SOL_MAIN}`\n\nReply with TX signature:",
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
        async with pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO dev_subscriptions (telegram_id, username, tier, status, subscription_end)
                VALUES ($1, $2, $3, 'active', $4)
                ON CONFLICT (telegram_id) DO UPDATE SET tier = $3, status = 'active', subscription_end = $4
            """, str(user.id), user.username, payment['tier'], expiry)
            await conn.execute("""
                INSERT INTO platform_payments (dev_telegram_id, amount_sol, tx_signature) VALUES ($1, $2, $3)
            """, str(user.id), payment['amount'], tx)
        
        await update.message.reply_text(f"✅ ACTIVATED!\nTier: {payment['tier']}\nExpires: {expiry.strftime('%Y-%m-%d')}\n\nAdd me to group: /activate", parse_mode=ParseMode.MARKDOWN)
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
    
    async with pool.acquire() as conn:
        dev = await conn.fetchrow("SELECT * FROM dev_subscriptions WHERE telegram_id = $1 AND status = 'active'", str(user.id))
        if not dev:
            return await update.message.reply_text("❌ Subscribe first")
        await conn.execute("""
            INSERT INTO protected_groups (dev_telegram_id, telegram_chat_id, group_name)
            VALUES ($1, $2, $3) ON CONFLICT (telegram_chat_id) DO UPDATE SET is_active = TRUE
        """, dev['telegram_id'], str(chat.id), chat.title)
    
    await update.message.reply_text("✅ GROUP PROTECTED\n🛡 Anti-spam: ON\n🚀 Auto-detect: READY", parse_mode=ParseMode.MARKDOWN)

async def security(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg or not msg.text:
        return
    chat_id = str(update.effective_chat.id)
    user = update.effective_user
    
    async with pool.acquire() as conn:
        group = await conn.fetchrow("SELECT * FROM protected_groups WHERE telegram_chat_id = $1 AND is_active = TRUE", chat_id)
        if not group:
            return
    
    try:
        member = await context.bot.get_chat_member(chat_id, user.id)
        if member.status in [ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER]:
            return
    except:
        return
    
    text_lower = msg.text.lower()
    spam = ['dm me', 'http', 't.me/', 'investment', 'forex', 'profit']
    if sum(1 for s in spam if s in text_lower) >= 2:
        try:
            await msg.delete()
            w = await context.bot.send_message(chat_id, f"🛡 Spam removed from @{user.username or user.id}", parse_mode=ParseMode.MARKDOWN)
            await asyncio.sleep(5)
            await w.delete()
        except:
            pass

# --- MAIN ---
async def main():
    await init_db()
    threading.Thread(target=run_flask, daemon=True).start()
    
    app = Application.builder().token(BOT_TOKEN).build()
    conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(subscription_callback, pattern="^sub_")],
        states={AWAITING_PAYMENT: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_payment)]},
        fallbacks=[]
    )
    app.add_handler(CommandHandler("start", start))
    app.add_handler(conv)
    app.add_handler(CommandHandler("activate", activate_group))
    app.add_handler(MessageHandler(filters.TEXT & filters.ChatType.GROUPS, security))
    
    logger.info("🚀 BOT STARTED")
    await app.run_polling()

if __name__ == "__main__":
    asyncio.run(main())
