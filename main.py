#!/usr/bin/env python3
"""
ICE REIGN MACHINE V6.9 - PSYCOPG2 VERSION
Python 3.14 Compatible | psycopg2-binary | Auto-webhook
"""
import os
import asyncio
import logging
import ssl
import urllib.request
import json
import psycopg2
from datetime import datetime, timedelta
from typing import Optional, Dict
from flask import Flask, request, jsonify
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand, Bot
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

# Config
BOT_TOKEN = os.getenv('BOT_TOKEN')
ADMIN_ID = os.getenv('ADMIN_ID')
SOL_MAIN = os.getenv('SOL_MAIN')
HELIUS_API_KEY = os.getenv('HELIUS_API_KEY')
DATABASE_URL = os.getenv('DATABASE_URL')
RENDER_URL = os.getenv('RENDER_URL', 'https://icereign-machine-des3.onrender.com')
PORT = int(os.getenv('PORT', 10000))
SUBSCRIPTION_PRICE = float(os.getenv('SUBSCRIPTION_PRICE', 0.5))
PRO_PRICE = float(os.getenv('PRO_PRICE', 3.0))
AWAITING_PAYMENT = 1

# Globals
bot = Bot(token=BOT_TOKEN)
application = None

# Flask
flask_app = Flask(__name__)

@flask_app.route('/')
def health():
    return jsonify({
        'status': 'ICE REIGN ONLINE',
        'version': '6.9.0',
        'wallet': SOL_MAIN,
        'time': datetime.now().isoformat()
    }), 200

@flask_app.route('/webhook/telegram', methods=['POST'])
def telegram_webhook():
    try:
        data = request.get_json(force=True)
        update = Update.de_json(data, bot)
        asyncio.create_task(handle_update(update))
        return jsonify({'ok': True}), 200
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return jsonify({'ok': False}), 500

@flask_app.route('/webhook/helius', methods=['POST'])
def helius_webhook():
    logger.info(f"Helius: {request.json}")
    return jsonify({'received': True}), 200

async def handle_update(update: Update):
    try:
        await application.process_update(update)
    except Exception as e:
        logger.error(f"Update error: {e}")

def setup_webhook():
    try:
        webhook_url = f"{RENDER_URL}/webhook/telegram"
        api_url = f"https://api.telegram.org/bot{BOT_TOKEN}/setWebhook?url={webhook_url}"
        
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        
        response = urllib.request.urlopen(api_url, context=ctx, timeout=30)
        result = json.loads(response.read().decode())
        
        if result.get('ok'):
            logger.info(f"✅ Webhook set: {webhook_url}")
            return True
        else:
            logger.error(f"❌ Webhook failed: {result}")
            return False
    except Exception as e:
        logger.error(f"⚠️ Webhook error: {e}")
        return False

# Database - psycopg2 version
def get_db_connection():
    return psycopg2.connect(DATABASE_URL)

def init_db():
    conn = get_db_connection()
    cur = conn.cursor()
    
    cur.execute("""
        CREATE TABLE IF NOT EXISTS dev_subscriptions (
            id SERIAL PRIMARY KEY,
            telegram_id TEXT UNIQUE NOT NULL,
            username TEXT,
            tier TEXT DEFAULT 'none',
            status TEXT DEFAULT 'inactive',
            subscription_end TIMESTAMP
        )
    """)
    
    cur.execute("""
        CREATE TABLE IF NOT EXISTS platform_payments (
            id SERIAL PRIMARY KEY,
            dev_telegram_id TEXT NOT NULL,
            amount_sol REAL NOT NULL,
            tx_signature TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    cur.execute("""
        CREATE TABLE IF NOT EXISTS protected_groups (
            id SERIAL PRIMARY KEY,
            dev_telegram_id TEXT NOT NULL,
            telegram_chat_id TEXT UNIQUE NOT NULL,
            group_name TEXT,
            is_active INTEGER DEFAULT 1
        )
    """)
    
    cur.execute("""
        CREATE TABLE IF NOT EXISTS user_engagement (
            group_chat_id TEXT NOT NULL,
            telegram_id TEXT NOT NULL,
            message_count INTEGER DEFAULT 0,
            UNIQUE(group_chat_id, telegram_id)
        )
    """)
    
    cur.execute("""
        CREATE TABLE IF NOT EXISTS user_wallets (
            telegram_id TEXT PRIMARY KEY,
            wallet_address TEXT NOT NULL
        )
    """)
    
    conn.commit()
    cur.close()
    conn.close()
    logger.info("✅ Database initialized")

def get_dev_sub(telegram_id: int) -> Optional[Dict]:
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM dev_subscriptions WHERE telegram_id = %s", (str(telegram_id),))
    row = cur.fetchone()
    cur.close()
    conn.close()
    
    if row:
        return {
            'id': row[0],
            'telegram_id': row[1],
            'username': row[2],
            'tier': row[3],
            'status': row[4],
            'subscription_end': row[5]
        }
    return None

def get_revenue() -> float:
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT COALESCE(SUM(amount_sol), 0) FROM platform_payments")
    result = cur.fetchone()[0]
    cur.close()
    conn.close()
    return result or 0.0

# Solana
async def verify_sol_payment(tx_sig: str, expected: float) -> bool:
    try:
        async with aiohttp.ClientSession() as s:
            url = f"https://api.helius.xyz/v0/transactions/?api-key={HELIUS_API_KEY}"
            async with s.post(url, json={"transactions": [tx_sig]}) as r:
                if r.status != 200:
                    return False
                data = await r.json()
                if not data or data[0].get('err'):
                    return False
                for t in data[0].get('nativeTransfers', []):
                    if t['toUserAccount'] == SOL_MAIN:
                        return float(t['amount'])/1e9 >= expected * 0.95
                return False
    except Exception as e:
        logger.error(f"Verify error: {e}")
        return False

# Handlers
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat_type = update.effective_chat.type
    
    if chat_type == "private":
        if str(user.id) == ADMIN_ID:
            rev = get_revenue()
            await update.message.reply_text(f"👑 *ADMIN*\nRevenue: `{rev:.4f}` SOL\nWallet: `{SOL_MAIN}`", parse_mode=ParseMode.MARKDOWN)
            return
        
        dev = get_dev_sub(user.id)
        if dev and dev['status'] == 'active':
            await update.message.reply_text(f"👨‍💻 *DASHBOARD*\nTier: `{dev['tier'].upper()}`\nExpires: `{dev['subscription_end']}`", parse_mode=ParseMode.MARKDOWN)
        else:
            keyboard = [
                [InlineKeyboardButton(f"💎 Basic - {SUBSCRIPTION_PRICE} SOL", callback_data="sub_basic")],
                [InlineKeyboardButton(f"👑 Pro - {PRO_PRICE} SOL", callback_data="sub_pro")]
            ]
            await update.message.reply_text("🚀 *ICE REIGN MACHINE*\n\nAuto-detect & distribute tokens", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)
    else:
        await update.message.reply_text("🛡 *Ice Reign Active*\n/wallet - Register SOL\n/airdrop - Check eligibility", parse_mode=ParseMode.MARKDOWN)

async def wallet_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) != 1:
        return await update.message.reply_text("💼 Usage: `/wallet YOUR_SOL_ADDRESS`", parse_mode=ParseMode.MARKDOWN)
    
    wallet = context.args[0].strip()
    if len(wallet) < 32 or len(wallet) > 44:
        return await update.message.reply_text("❌ Invalid address")
    
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO user_wallets (telegram_id, wallet_address) VALUES (%s, %s)
        ON CONFLICT (telegram_id) DO UPDATE SET wallet_address = EXCLUDED.wallet_address
    """, (str(update.effective_user.id), wallet))
    conn.commit()
    cur.close()
    conn.close()
    
    await update.message.reply_text(f"✅ Wallet registered:\n`{wallet}`", parse_mode=ParseMode.MARKDOWN)

async def airdrop_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT message_count FROM user_engagement WHERE group_chat_id = %s AND telegram_id = %s", (chat_id, str(update.effective_user.id)))
    row = cur.fetchone()
    cur.close()
    conn.close()
    
    count = row[0] if row else 0
    await update.message.reply_text(f"📊 *Your Stats*\nMessages: `{count}`\n\nKeep engaging!", parse_mode=ParseMode.MARKDOWN)

async def sub_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    tier = query.data.replace("sub_", "")
    amount = SUBSCRIPTION_PRICE if tier == "basic" else PRO_PRICE
    
    context.user_data['payment'] = {'tier': tier, 'amount': amount}
    
    await query.edit_message_text(f"💳 *{tier.upper()}*\n\nSend `{amount}` SOL to:\n`{SOL_MAIN}`\n\nReply with TX:", parse_mode=ParseMode.MARKDOWN)
    return AWAITING_PAYMENT

async def process_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tx = update.message.text.strip()
    user = update.effective_user
    payment = context.user_data.get('payment')
    
    if not payment:
        await update.message.reply_text("Session expired")
        return ConversationHandler.END
    
    await update.message.reply_text("⏳ Verifying...")
    
    if await verify_sol_payment(tx, payment['amount']):
        expiry = datetime.now() + timedelta(days=30)
        
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO dev_subscriptions (telegram_id, username, tier, status, subscription_end)
            VALUES (%s, %s, %s, 'active', %s)
            ON CONFLICT (telegram_id) DO UPDATE SET
            tier = EXCLUDED.tier, status = 'active', subscription_end = EXCLUDED.subscription_end
        """, (str(user.id), user.username, payment['tier'], expiry))
        
        cur.execute("""
            INSERT INTO platform_payments (dev_telegram_id, amount_sol, tx_signature)
            VALUES (%s, %s, %s)
        """, (str(user.id), payment['amount'], tx))
        conn.commit()
        cur.close()
        conn.close()
        
        await context.bot.send_message(ADMIN_ID, f"💰 {payment['amount']} SOL from @{user.username}")
        await update.message.reply_text(f"✅ *ACTIVATED!*\nTier: `{payment['tier'].upper()}`\nExpires: `{expiry.strftime('%Y-%m-%d')}`", parse_mode=ParseMode.MARKDOWN)
    else:
        await update.message.reply_text("❌ Payment not found")
    
    return ConversationHandler.END

async def activate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    
    if chat.type == "private":
        return await update.message.reply_text("Use in group!")
    
    member = await context.bot.get_chat_member(chat.id, user.id)
    if member.status not in [ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER]:
        return await update.message.reply_text("❌ Admin only")
    
    dev = get_dev_sub(user.id)
    if not dev or dev['status'] != 'active':
        return await update.message.reply_text("❌ Subscription required")
    
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO protected_groups (dev_telegram_id, telegram_chat_id, group_name, is_active)
        VALUES (%s, %s, %s, 1)
        ON CONFLICT (telegram_id) DO UPDATE SET is_active = 1
    """, (str(user.id), str(chat.id), chat.title))
    conn.commit()
    cur.close()
    conn.close()
    
    await context.bot.set_my_commands([
        BotCommand("wallet", "Register SOL"),
        BotCommand("airdrop", "Check eligibility")
    ], scope={"type": "chat", "chat_id": chat.id})
    
    await update.message.reply_text("✅ *GROUP PROTECTED*\n🛡 Anti-spam: ON\n🚀 Airdrop ready", parse_mode=ParseMode.MARKDOWN)

async def track_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg or not msg.text:
        return
    
    chat_id = str(update.effective_chat.id)
    user = update.effective_user
    
    try:
        if (await context.bot.get_chat_member(chat_id, user.id)).status in [ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER]:
            return
    except:
        return
    
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM protected_groups WHERE telegram_chat_id = %s AND is_active = 1", (chat_id,))
    if not cur.fetchone():
        cur.close()
        conn.close()
        return
    
    cur.execute("""
        INSERT INTO user_engagement (group_chat_id, telegram_id, message_count)
        VALUES (%s, %s, 1)
        ON CONFLICT (group_chat_id, telegram_id) DO UPDATE SET
        message_count = user_engagement.message_count + 1
    """, (chat_id, str(user.id)))
    conn.commit()
    cur.close()
    conn.close()
    
    text_lower = msg.text.lower()
    spam_keywords = ['dm me', 'http', 't.me/', 'investment', 'forex']
    if sum(1 for k in spam_keywords if k in text_lower) >= 2:
        try:
            await msg.delete()
            warning = await context.bot.send_message(chat_id, "🛡 Spam removed")
            await asyncio.sleep(3)
            await warning.delete()
        except:
            pass

def setup_handlers():
    global application
    application = Application.builder().token(BOT_TOKEN).updater(None).build()
    
    conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(sub_callback, pattern="^sub_")],
        states={AWAITING_PAYMENT: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_payment)]},
        fallbacks=[]
    )
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("wallet", wallet_cmd))
    application.add_handler(CommandHandler("airdrop", airdrop_cmd))
    application.add_handler(CommandHandler("activate", activate))
    application.add_handler(conv_handler)
    application.add_handler(MessageHandler(filters.TEXT & filters.ChatType.GROUPS, track_msg))
    
    return application

def main():
    # Setup webhook
    if not setup_webhook():
        logger.warning("⚠️ Webhook setup failed - may already be set")
    
    # Init database
    init_db()
    
    # Setup bot
    setup_handlers()
    
    logger.info("🚀 Ice Reign Machine v6.9 started")
    logger.info(f"🌐 URL: {RENDER_URL}")
    logger.info(f"🗄️ Database: PostgreSQL (psycopg2)")
    
    # Start server
    flask_app.run(host='0.0.0.0', port=PORT, threaded=True, debug=False, use_reloader=False)

if __name__ == "__main__":
    main()
