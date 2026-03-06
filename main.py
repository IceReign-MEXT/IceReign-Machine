#!/usr/bin/env python3
"""
ICE REIGN MACHINE V6.7 - POSTGRESQL VERSION
With auto-webhook setup
"""
import os
import asyncio
import logging
import ssl
import urllib.request
from datetime import datetime, timedelta
from typing import Optional, Dict
from flask import Flask, request, jsonify
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand, Bot
from telegram.constants import ParseMode, ChatMemberStatus
from telegram.ext import (
    Application, CommandHandler, ContextTypes, MessageHandler,
    filters, CallbackQueryHandler, ConversationHandler
)
import asyncpg
import aiohttp
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ==================== CONFIG ====================
BOT_TOKEN = os.getenv('BOT_TOKEN')
ADMIN_ID = os.getenv('ADMIN_ID')
SOL_MAIN = os.getenv('SOL_MAIN')
HELIUS_API_KEY = os.getenv('HELIUS_API_KEY')
DATABASE_URL = os.getenv('DATABASE_URL')
PORT = int(os.getenv('PORT', 10000))
SUBSCRIPTION_PRICE = float(os.getenv('SUBSCRIPTION_PRICE', 0.5))
PRO_PRICE = float(os.getenv('PRO_PRICE', 3.0))
AWAITING_PAYMENT = 1

# RENDER URL
RENDER_URL = "https://icereign-machine-des3.onrender.com"

# Global instances
bot = Bot(token=BOT_TOKEN)
application = None

# ==================== AUTO WEBHOOK ====================
def setup_webhook():
    try:
        webhook_url = f"{RENDER_URL}/webhook/telegram"
        api_url = f"https://api.telegram.org/bot{BOT_TOKEN}/setWebhook?url={webhook_url}"
        
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        
        response = urllib.request.urlopen(api_url, context=ctx, timeout=30)
        result = response.read().decode()
        logger.info(f"📡 Webhook setup: {result}")
        return True
    except Exception as e:
        logger.error(f"⚠️ Webhook setup failed: {e}")
        return False

# ==================== FLASK ====================
flask_app = Flask(__name__)

@flask_app.route('/')
def health():
    return jsonify({
        'status': 'ICE REIGN ONLINE',
        'version': '6.7.0',
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
        return jsonify({'ok': False, 'error': str(e)}), 500

@flask_app.route('/webhook/helius', methods=['POST'])
def helius_webhook():
    data = request.json or {}
    logger.info(f"Helius: {data}")
    return jsonify({'received': True}), 200

async def handle_update(update: Update):
    try:
        await application.process_update(update)
    except Exception as e:
        logger.error(f"Update error: {e}")

# ==================== DATABASE ====================
async def init_db():
    conn = await asyncpg.connect(DATABASE_URL)
    
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS dev_subscriptions (
            id SERIAL PRIMARY KEY,
            telegram_id TEXT UNIQUE NOT NULL,
            username TEXT,
            tier TEXT DEFAULT 'none',
            status TEXT DEFAULT 'inactive',
            subscription_end TIMESTAMP
        )
    """)
    
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS platform_payments (
            id SERIAL PRIMARY KEY,
            dev_telegram_id TEXT NOT NULL,
            amount_sol REAL NOT NULL,
            tx_signature TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS protected_groups (
            id SERIAL PRIMARY KEY,
            dev_telegram_id TEXT NOT NULL,
            telegram_chat_id TEXT UNIQUE NOT NULL,
            group_name TEXT,
            is_active INTEGER DEFAULT 1
        )
    """)
    
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS user_engagement (
            group_chat_id TEXT NOT NULL,
            telegram_id TEXT NOT NULL,
            message_count INTEGER DEFAULT 0,
            UNIQUE(group_chat_id, telegram_id)
        )
    """)
    
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS user_wallets (
            telegram_id TEXT PRIMARY KEY,
            wallet_address TEXT NOT NULL
        )
    """)
    
    await conn.close()
    logger.info("✅ PostgreSQL database initialized")

# ==================== SOLANA ====================
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

# ==================== HELPERS ====================
async def get_dev_sub(telegram_id: int) -> Optional[Dict]:
    conn = await asyncpg.connect(DATABASE_URL)
    row = await conn.fetchrow(
        "SELECT * FROM dev_subscriptions WHERE telegram_id = $1",
        str(telegram_id)
    )
    await conn.close()
    return dict(row) if row else None

async def get_revenue() -> float:
    conn = await asyncpg.connect(DATABASE_URL)
    result = await conn.fetchval(
        "SELECT COALESCE(SUM(amount_sol), 0) FROM platform_payments"
    )
    await conn.close()
    return result or 0.0

# ==================== HANDLERS ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat_type = update.effective_chat.type
    
    if chat_type == "private":
        if str(user.id) == ADMIN_ID:
            rev = await get_revenue()
            await update.message.reply_text(
                f"👑 *ADMIN*\nRevenue: `{rev:.4f}` SOL\nWallet: `{SOL_MAIN}`",
                parse_mode=ParseMode.MARKDOWN
            )
            return
        
        dev = await get_dev_sub(user.id)
        if dev and dev['status'] == 'active':
            await update.message.reply_text(
                f"👨‍💻 *DASHBOARD*\nTier: `{dev['tier'].upper()}`\n"
                f"Expires: `{dev['subscription_end']}`",
                parse_mode=ParseMode.MARKDOWN
            )
        else:
            keyboard = [
                [InlineKeyboardButton(f"💎 Basic - {SUBSCRIPTION_PRICE} SOL", callback_data="sub_basic")],
                [InlineKeyboardButton(f"👑 Pro - {PRO_PRICE} SOL", callback_data="sub_pro")]
            ]
            await update.message.reply_text(
                "🚀 *ICE REIGN MACHINE*\n\nAuto-detect & distribute tokens",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode=ParseMode.MARKDOWN
            )
    else:
        await update.message.reply_text(
            "🛡 *Ice Reign Active*\n/wallet - Register SOL\n/airdrop - Check eligibility",
            parse_mode=ParseMode.MARKDOWN
        )

async def wallet_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) != 1:
        return await update.message.reply_text(
            "💼 Usage: `/wallet YOUR_SOL_ADDRESS`",
            parse_mode=ParseMode.MARKDOWN
        )
    
    wallet = context.args[0].strip()
    if len(wallet) < 32 or len(wallet) > 44:
        return await update.message.reply_text("❌ Invalid address")
    
    conn = await asyncpg.connect(DATABASE_URL)
    await conn.execute("""
        INSERT INTO user_wallets (telegram_id, wallet_address)
        VALUES ($1, $2)
        ON CONFLICT (telegram_id) DO UPDATE SET
        wallet_address = EXCLUDED.wallet_address
    """, str(update.effective_user.id), wallet)
    await conn.close()
    
    await update.message.reply_text(
        f"✅ Wallet registered:\n`{wallet}`",
        parse_mode=ParseMode.MARKDOWN
    )

async def airdrop_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    user_id = str(update.effective_user.id)
    
    conn = await asyncpg.connect(DATABASE_URL)
    row = await conn.fetchrow(
        "SELECT message_count FROM user_engagement WHERE group_chat_id = $1 AND telegram_id = $2",
        chat_id, user_id
    )
    await conn.close()
    
    count = row['message_count'] if row else 0
    await update.message.reply_text(
        f"📊 *Your Stats*\nMessages: `{count}`\n\nKeep engaging!",
        parse_mode=ParseMode.MARKDOWN
    )

async def sub_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    tier = query.data.replace("sub_", "")
    amount = SUBSCRIPTION_PRICE if tier == "basic" else PRO_PRICE
    
    context.user_data['payment'] = {'tier': tier, 'amount': amount}
    
    await query.edit_message_text(
        f"💳 *{tier.upper()}*\n\n"
        f"Send `{amount}` SOL to:\n`{SOL_MAIN}`\n\n"
        f"Reply with transaction signature:",
        parse_mode=ParseMode.MARKDOWN
    )
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
        
        conn = await asyncpg.connect(DATABASE_URL)
        await conn.execute("""
            INSERT INTO dev_subscriptions (telegram_id, username, tier, status, subscription_end)
            VALUES ($1, $2, $3, 'active', $4)
            ON CONFLICT (telegram_id) DO UPDATE SET
            tier = EXCLUDED.tier,
            status = 'active',
            subscription_end = EXCLUDED.subscription_end
        """, str(user.id), user.username, payment['tier'], expiry)
        
        await conn.execute("""
            INSERT INTO platform_payments (dev_telegram_id, amount_sol, tx_signature)
            VALUES ($1, $2, $3)
        """, str(user.id), payment['amount'], tx)
        await conn.close()
        
        await context.bot.send_message(
            ADMIN_ID,
            f"💰 {payment['amount']} SOL from @{user.username}"
        )
        
        await update.message.reply_text(
            f"✅ *ACTIVATED!*\n"
            f"Tier: `{payment['tier'].upper()}`\n"
            f"Expires: `{expiry.strftime('%Y-%m-%d')}`",
            parse_mode=ParseMode.MARKDOWN
        )
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
    
    dev = await get_dev_sub(user.id)
    if not dev or dev['status'] != 'active':
        return await update.message.reply_text("❌ Subscription required")
    
    conn = await asyncpg.connect(DATABASE_URL)
    await conn.execute("""
        INSERT INTO protected_groups (dev_telegram_id, telegram_chat_id, group_name, is_active)
        VALUES ($1, $2, $3, 1)
        ON CONFLICT (telegram_chat_id) DO UPDATE SET
        is_active = 1
    """, str(user.id), str(chat.id), chat.title)
    await conn.close()
    
    await context.bot.set_my_commands([
        BotCommand("wallet", "Register SOL"),
        BotCommand("airdrop", "Check eligibility")
    ], scope={"type": "chat", "chat_id": chat.id})
    
    await update.message.reply_text(
        "✅ *GROUP PROTECTED*\n🛡 Anti-spam: ON\n🚀 Airdrop ready",
        parse_mode=ParseMode.MARKDOWN
    )

async def track_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg or not msg.text:
        return
    
    chat_id = str(update.effective_chat.id)
    user = update.effective_user
    
    try:
        member = await context.bot.get_chat_member(chat_id, user.id)
        if member.status in [ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER]:
            return
    except:
        return
    
    conn = await asyncpg.connect(DATABASE_URL)
    result = await conn.fetchval(
        "SELECT 1 FROM protected_groups WHERE telegram_chat_id = $1 AND is_active = 1",
        chat_id
    )
    if not result:
        await conn.close()
        return
    
    await conn.execute("""
        INSERT INTO user_engagement (group_chat_id, telegram_id, message_count)
        VALUES ($1, $2, 1)
        ON CONFLICT (group_chat_id, telegram_id) DO UPDATE SET
        message_count = user_engagement.message_count + 1
    """, chat_id, str(user.id))
    await conn.close()
    
    # Anti-spam
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

# ==================== SETUP ====================
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

# ==================== MAIN ====================
def main():
    # Setup webhook first
    setup_webhook()
    
    # Init database
    asyncio.run(init_db())
    
    # Setup bot
    setup_handlers()
    
    logger.info("🚀 Ice Reign Machine v6.7 started")
    logger.info(f"🌐 URL: {RENDER_URL}")
    logger.info(f"🗄️ Database: PostgreSQL")
    
    # Start server
    flask_app.run(host='0.0.0.0', port=PORT, threaded=True, debug=False, use_reloader=False)

if __name__ == "__main__":
    main()
