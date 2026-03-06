#!/usr/bin/env python3
"""
ICE REIGN MACHINE V5 - SQLITE VERSION (Zero Compilation)
Revenue flows to SOL_MAIN automatically
"""

import os
import json
import asyncio
import logging
import threading
import aiosqlite
from datetime import datetime, timedelta
from decimal import Decimal

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
DATABASE_URL = os.getenv("DATABASE_URL")  # Will ignore for SQLite
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
        "version": "5.0-sqlite",
        "wallet": SOL_MAIN,
        "time": datetime.utcnow().isoformat()
    }), 200

def run_flask():
    flask_app.run(host='0.0.0.0', port=PORT, threaded=True)

# --- DATABASE (SQLite - Zero Compilation) ---
async def init_db():
    try:
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
        logger.info("✅ SQLite Database ready")
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
                f"👑 **ADMIN DASHBOARD**\n\n"
                f"💰 **Total Revenue:** {total:.4f} SOL\n"
                f"🏦 **Wallet:** `{SOL_MAIN}`\n\n"
                f"All payments flow here automatically.",
                parse_mode=ParseMode.MARKDOWN
            )
            return
        
        async with aiosqlite.connect(DB_FILE) as db:
            async with db.execute("SELECT * FROM dev_subscriptions WHERE telegram_id = ?", (str(user.id),)) as cursor:
                dev = await cursor.fetchone()
        
        if dev and dev[4] == 'active':  # status column index
            expiry = dev[5] if dev[5] else 'N/A'
            await update.message.reply_text(
                f"👨‍💻 **DEV DASHBOARD**\n\n"
                f"Tier: {dev[3].upper()}\n"
                f"Status: ✅ ACTIVE\n"
                f"Expires: {expiry}\n\n"
                f"**Commands:**\n"
                f"/activate - Add bot to group\n"
                f"/stats - View engagement",
                parse_mode=ParseMode.MARKDOWN
            )
        else:
            keyboard = [
                [InlineKeyboardButton(f"💎 Basic - {SUBSCRIPTION_PRICE} SOL", callback_data="sub_basic")],
                [InlineKeyboardButton("👑 Pro - 3 SOL", callback_data="sub_pro")]
            ]
            await update.message.reply_text(
                f"🚀 **ICE REIGN MACHINE**\n\n"
                f"Auto-detect token launches\n"
                f"Anti-spam protection\n"
                f"Automatic distribution\n\n"
                f"**Pricing:**\n"
                f"• Basic: {SUBSCRIPTION_PRICE} SOL/month\n"
                f"• Pro: 3 SOL/month\n\n"
                f"**Payment Address:**\n`{SOL_MAIN}`\n\n"
                f"Click to subscribe:",
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
        f"💳 **{tier.upper()} Subscription**\n\n"
        f"Send **{amount} SOL** to:\n"
        f"`{SOL_MAIN}`\n\n"
        f"Reply with transaction signature (TX ID):",
        parse_mode=ParseMode.MARKDOWN
    )
    return AWAITING_PAYMENT

async def process_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tx = update.message.text.strip()
    user = update.effective_user
    payment = context.user_data.get('payment')
    
    if not payment:
        await update.message.reply_text("Use /start first")
        return ConversationHandler.END
    
    await update.message.reply_text("⏳ Verifying payment on Solana...")
    
    if await verify_sol_payment(tx, payment['amount']):
        expiry = datetime.now() + timedelta(days=30)
        
        async with aiosqlite.connect(DB_FILE) as db:
            # Insert or update dev
            await db.execute("""
                INSERT INTO dev_subscriptions (telegram_id, username, tier, status, subscription_end)
                VALUES (?, ?, ?, 'active', ?)
                ON CONFLICT(telegram_id) DO UPDATE SET
                    tier = excluded.tier,
                    status = 'active',
                    subscription_end = excluded.subscription_end
            """, (str(user.id), user.username, payment['tier'], expiry))
            
            # Record payment
            await db.execute("""
                INSERT INTO platform_payments (dev_telegram_id, amount_sol, tx_signature)
                VALUES (?, ?, ?)
            """, (str(user.id), payment['amount'], tx))
            
            await db.commit()
        
        await update.message.reply_text(
            f"✅ **SUBSCRIPTION ACTIVATED!**\n\n"
            f"**Tier:** {payment['tier'].upper()}\n"
            f"**Expires:** {expiry.strftime('%Y-%m-%d')}\n\n"
            f"**Next Steps:**\n"
            f"1. Add me to your Telegram group\n"
            f"2. Make me admin (delete messages)\n"
            f"3. Type `/activate` in group\n\n"
            f"_Your token launches will be detected automatically_",
            parse_mode=ParseMode.MARKDOWN
        )
        
        # Notify admin (you)
        await context.bot.send_message(
            ADMIN_ID,
            f"💰 **NEW PAYMENT RECEIVED**\n\n"
            f"From: @{user.username or user.id}\n"
            f"Amount: **{payment['amount']} SOL**\n"
            f"Tier: {payment['tier'].upper()}\n"
            f"TX: `{tx[:25]}...`",
            parse_mode=ParseMode.MARKDOWN
        )
    else:
        await update.message.reply_text(
            "❌ **Payment Not Verified**\n\n"
            "Possible issues:\n"
            "• Transaction not confirmed yet (wait 30s)\n"
            "• Wrong amount sent\n"
            "• Wrong wallet address\n\n"
            "Try again or contact support.",
            parse_mode=ParseMode.MARKDOWN
        )
    
    return ConversationHandler.END

async def activate_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    
    if chat.type == "private":
        await update.message.reply_text("❌ Use this in a group chat")
        return
    
    # Check admin status
    try:
        member = await context.bot.get_chat_member(chat.id, user.id)
        if member.status not in [ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER]:
            await update.message.reply_text("❌ Only group admins can activate")
            return
    except Exception as e:
        logger.error(f"Admin check error: {e}")
        return
    
    # Check subscription
    async with aiosqlite.connect(DB_FILE) as db:
        async with db.execute(
            "SELECT * FROM dev_subscriptions WHERE telegram_id = ? AND status = 'active'",
            (str(user.id),)
        ) as cursor:
            dev = await cursor.fetchone()
        
        if not dev:
            await update.message.reply_text(
                "❌ **Active Subscription Required**\n\n"
                "PM @IceReignBot to subscribe first."
            )
            return
        
        # Add group
        await db.execute("""
            INSERT INTO protected_groups (dev_telegram_id, telegram_chat_id, group_name)
            VALUES (?, ?, ?)
            ON CONFLICT(telegram_chat_id) DO UPDATE SET is_active = 1
        """, (str(user.id), str(chat.id), chat.title))
        await db.commit()
    
    await update.message.reply_text(
        "✅ **GROUP PROTECTED BY ICE REIGN**\n\n"
        "🛡 **Anti-Spam:** ACTIVE\n"
        "📊 **Engagement Tracking:** ON\n"
        "🚀 **Auto-Detect:** ENABLED\n\n"
        "The bot will:\n"
        "• Delete spam automatically\n"
        "• Track active users for airdrops\n"
        "• Detect when you launch tokens\n"
        "• Notify you of new launches\n\n"
        f"_Revenue wallet: `{SOL_MAIN[:15]}...`_",
        parse_mode=ParseMode.MARKDOWN
    )

async def security_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Anti-spam and engagement tracking"""
    msg = update.message
    if not msg or not msg.text:
        return
    
    chat_id = str(update.effective_chat.id)
    user = update.effective_user
    
    # Check if protected group
    async with aiosqlite.connect(DB_FILE) as db:
        async with db.execute(
            "SELECT * FROM protected_groups WHERE telegram_chat_id = ? AND is_active = 1",
            (chat_id,)
        ) as cursor:
            group = await cursor.fetchone()
        
        if not group:
            return
        
        # Track engagement
        await db.execute("""
            INSERT INTO user_engagement (group_chat_id, telegram_id, message_count, last_active)
            VALUES (?, ?, 1, CURRENT_TIMESTAMP)
            ON CONFLICT(group_chat_id, telegram_id) DO UPDATE SET
                message_count = message_count + 1,
                last_active = CURRENT_TIMESTAMP
        """, (chat_id, str(user.id)))
        await db.commit()
    
    # Skip admins for spam check
    try:
        member = await context.bot.get_chat_member(chat_id, user.id)
        if member.status in [ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER]:
            return
    except:
        return
    
    # Spam detection
    text_lower = msg.text.lower()
    spam_keywords = ['dm me', 'message me', 'http', 't.me/', 'investment', 'forex', 
                     'binary', 'profit guaranteed', 'double your', 'send me crypto']
    spam_count = sum(1 for keyword in spam_keywords if keyword in text_lower)
    
    # Check for excessive capitalization
    if len(msg.text) > 10:
        caps_ratio = sum(1 for c in msg.text if c.isupper()) / len(msg.text)
        if caps_ratio > 0.8:
            spam_count += 1
    
    if spam_count >= 2:
        try:
            await msg.delete()
            warning = await context.bot.send_message(
                chat_id,
                f"🛡 **THREAT NEUTRALIZED**\n\n"
                f"User: @{user.username or user.id}\n"
                f"Action: Spam removed\n\n"
                f"_Protected by Ice Reign Machine_",
                parse_mode=ParseMode.MARKDOWN
            )
            
            # Update spam count
            async with aiosqlite.connect(DB_FILE) as db:
                await db.execute(
                    "UPDATE protected_groups SET spam_blocked = spam_blocked + 1 WHERE telegram_chat_id = ?",
                    (chat_id,)
                )
                await db.commit()
            
            # Auto-delete warning
            await asyncio.sleep(8)
            await warning.delete()
            
        except Exception as e:
            logger.error(f"Spam removal failed: {e}")

# --- MAIN ---
async def main():
    await init_db()
    
    # Start web server in background
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    logger.info(f"🌐 Web server started on port {PORT}")
    
    # Start bot
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Conversation handler for subscriptions
    conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(subscription_callback, pattern="^sub_")],
        states={
            AWAITING_PAYMENT: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_payment)]
        },
        fallbacks=[]
    )
    
    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(conv_handler)
    application.add_handler(CommandHandler("activate", activate_group))
    application.add_handler(MessageHandler(filters.TEXT & filters.ChatType.GROUPS, security_handler))
    
    logger.info("🚀 ICE REIGN MACHINE V5 STARTED")
    logger.info(f"💰 All revenue flows to: {SOL_MAIN}")
    
    await application.run_polling()

if __name__ == "__main__":
    asyncio.run(main())
