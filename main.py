#!/usr/bin/env python3
"""
ICE REIGN MACHINE V6.5 - PRODUCTION READY
Python 3.14 Compatible | Webhook Based | No Polling
"""
import os
import asyncio
import logging
import aiosqlite
import aiohttp
from datetime import datetime, timedelta
from typing import Optional, Dict
from flask import Flask, request, jsonify
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand, Bot
from telegram.constants import ParseMode, ChatMemberStatus
from telegram.ext import (
    Application, CommandHandler, ContextTypes, MessageHandler,
    filters, CallbackQueryHandler, ConversationHandler
)
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
PORT = int(os.getenv('PORT', 10000))
SUBSCRIPTION_PRICE = float(os.getenv('SUBSCRIPTION_PRICE', 0.5))
PRO_PRICE = float(os.getenv('PRO_PRICE', 3.0))
DB_FILE = 'ice_reign.db'
AWAITING_PAYMENT = 1

# Global bot instance
bot = Bot(token=BOT_TOKEN)
application = None

# ==================== FLASK APP ====================
flask_app = Flask(__name__)

@flask_app.route('/')
def health():
    """Health check for Render"""
    return jsonify({
        'status': 'ICE REIGN ONLINE',
        'version': '6.5.0',
        'wallet': SOL_MAIN,
        'time': datetime.utcnow().isoformat()
    }), 200

@flask_app.route('/webhook/telegram', methods=['POST'])
def telegram_webhook():
    """Receive Telegram updates"""
    try:
        data = request.get_json(force=True)
        update = Update.de_json(data, bot)
        
        # Process in background
        asyncio.create_task(handle_update(update))
        return jsonify({'ok': True}), 200
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return jsonify({'ok': False, 'error': str(e)}), 500

@flask_app.route('/webhook/helius', methods=['POST'])
def helius_webhook():
    """Receive Helius token alerts"""
    data = request.json or {}
    logger.info(f"Helius: {data}")
    return jsonify({'received': True}), 200

async def handle_update(update: Update):
    """Process Telegram update"""
    try:
        await application.process_update(update)
    except Exception as e:
        logger.error(f"Update error: {e}")

# ==================== DATABASE ====================
async def init_db():
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS dev_subscriptions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id TEXT UNIQUE NOT NULL,
                username TEXT,
                tier TEXT DEFAULT 'none',
                status TEXT DEFAULT 'inactive',
                subscription_end TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS platform_payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                dev_telegram_id TEXT NOT NULL,
                amount_sol REAL NOT NULL,
                tx_signature TEXT
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS protected_groups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                dev_telegram_id TEXT NOT NULL,
                telegram_chat_id TEXT UNIQUE NOT NULL,
                group_name TEXT,
                is_active INTEGER DEFAULT 1
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS user_engagement (
                group_chat_id TEXT NOT NULL,
                telegram_id TEXT NOT NULL,
                message_count INTEGER DEFAULT 0,
                UNIQUE(group_chat_id, telegram_id)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS user_wallets (
                telegram_id TEXT PRIMARY KEY,
                wallet_address TEXT NOT NULL
            )
        """)
        await db.commit()
    logger.info("✅ Database initialized")

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
    async with aiosqlite.connect(DB_FILE) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM dev_subscriptions WHERE telegram_id = ?",
            (str(telegram_id),)
        ) as c:
            row = await c.fetchone()
            return dict(row) if row else None

async def get_revenue() -> float:
    async with aiosqlite.connect(DB_FILE) as db:
        async with db.execute(
            "SELECT COALESCE(SUM(amount_sol), 0) FROM platform_payments"
        ) as c:
            return (await c.fetchone())[0]

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
                [InlineKeyboardButton(
                    f"💎 Basic - {SUBSCRIPTION_PRICE} SOL",
                    callback_data="sub_basic"
                )],
                [InlineKeyboardButton(
                    f"👑 Pro - {PRO_PRICE} SOL",
                    callback_data="sub_pro"
                )]
            ]
            await update.message.reply_text(
                "🚀 *ICE REIGN MACHINE*\n\n"
                "Auto-detect & distribute tokens",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode=ParseMode.MARKDOWN
            )
    else:
        await update.message.reply_text(
            "🛡 *Ice Reign Active*\n"
            "/wallet - Register SOL\n"
            "/airdrop - Check eligibility",
            parse_mode=ParseMode.MARKDOWN
        )

async def wallet_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) != 1:
        await update.message.reply_text(
            "💼 Usage: `/wallet YOUR_SOL_ADDRESS`",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    wallet = context.args[0].strip()
    if len(wallet) < 32 or len(wallet) > 44:
        await update.message.reply_text("❌ Invalid address")
        return
    
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute("""
            INSERT INTO user_wallets (telegram_id, wallet_address)
            VALUES (?, ?)
            ON CONFLICT(telegram_id) DO UPDATE SET
            wallet_address = excluded.wallet_address
        """, (str(update.effective_user.id), wallet))
        await db.commit()
    
    await update.message.reply_text(
        f"✅ Wallet registered:\n`{wallet}`",
        parse_mode=ParseMode.MARKDOWN
    )

async def airdrop_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    user_id = str(update.effective_user.id)
    
    async with aiosqlite.connect(DB_FILE) as db:
        async with db.execute(
            "SELECT message_count FROM user_engagement "
            "WHERE group_chat_id = ? AND telegram_id = ?",
            (chat_id, user_id)
        ) as c:
            row = await c.fetchone()
    
    count = row[0] if row else 0
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
        await update.message.reply_text("Session expired. Use /start")
        return ConversationHandler.END
    
    await update.message.reply_text("⏳ Verifying payment...")
    
    if await verify_sol_payment(tx, payment['amount']):
        expiry = datetime.now() + timedelta(days=30)
        
        async with aiosqlite.connect(DB_FILE) as db:
            await db.execute("""
                INSERT INTO dev_subscriptions
                (telegram_id, username, tier, status, subscription_end)
                VALUES (?, ?, ?, 'active', ?)
                ON CONFLICT(telegram_id) DO UPDATE SET
                tier = excluded.tier,
                status = 'active',
                subscription_end = excluded.subscription_end
            """, (str(user.id), user.username, payment['tier'], expiry))
            
            await db.execute("""
                INSERT INTO platform_payments
                (dev_telegram_id, amount_sol, tx_signature)
                VALUES (?, ?, ?)
            """, (str(user.id), payment['amount'], tx))
            
            await db.commit()
        
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
        await update.message.reply_text(
            "❌ Payment not found or insufficient amount"
        )
    
    return ConversationHandler.END

async def activate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    
    if chat.type == "private":
        await update.message.reply_text("Use this command in a group!")
        return
    
    member = await context.bot.get_chat_member(chat.id, user.id)
    if member.status not in [ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER]:
        await update.message.reply_text("❌ Admin only command")
        return
    
    dev = await get_dev_sub(user.id)
    if not dev or dev['status'] != 'active':
        await update.message.reply_text("❌ Active subscription required")
        return
    
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute("""
            INSERT INTO protected_groups
            (dev_telegram_id, telegram_chat_id, group_name, is_active)
            VALUES (?, ?, ?, 1)
            ON CONFLICT(telegram_chat_id) DO UPDATE SET
            is_active = 1
        """, (str(user.id), str(chat.id), chat.title))
        await db.commit()
    
    await context.bot.set_my_commands([
        BotCommand("wallet", "Register SOL wallet"),
        BotCommand("airdrop", "Check eligibility")
    ], scope={"type": "chat", "chat_id": chat.id})
    
    await update.message.reply_text(
        "✅ *GROUP PROTECTED*\n"
        "🛡 Anti-spam: ON\n"
        "🚀 Airdrop ready",
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
    
    async with aiosqlite.connect(DB_FILE) as db:
        async with db.execute(
            "SELECT 1 FROM protected_groups WHERE telegram_chat_id = ? AND is_active = 1",
            (chat_id,)
        ) as c:
            if not await c.fetchone():
                return
        
        await db.execute("""
            INSERT INTO user_engagement (group_chat_id, telegram_id, message_count)
            VALUES (?, ?, 1)
            ON CONFLICT(group_chat_id, telegram_id) DO UPDATE SET
            message_count = message_count + 1
        """, (chat_id, str(user.id)))
        await db.commit()
    
    # Anti-spam
    text_lower = msg.text.lower()
    spam_keywords = ['dm me', 'http', 't.me/', 'investment', 'forex', 'guaranteed profit']
    if sum(1 for k in spam_keywords if k in text_lower) >= 2:
        try:
            await msg.delete()
            warning = await context.bot.send_message(
                chat_id,
                f"🛡 Spam removed from @{user.username or user.id}"
            )
            await asyncio.sleep(3)
            await warning.delete()
        except:
            pass

# ==================== SETUP ====================
def setup_handlers():
    """Setup bot handlers"""
    global application
    
    # CRITICAL: Use updater=None to avoid Python 3.14 __slots__ bug
    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .updater(None)  # No polling - we use webhooks
        .build()
    )
    
    # Conversation handler for payments
    conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(sub_callback, pattern="^sub_")],
        states={
            AWAITING_PAYMENT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, process_payment)
            ]
        },
        fallbacks=[]
    )
    
    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("wallet", wallet_cmd))
    application.add_handler(CommandHandler("airdrop", airdrop_cmd))
    application.add_handler(CommandHandler("activate", activate))
    application.add_handler(conv_handler)
    application.add_handler(
        MessageHandler(filters.TEXT & filters.ChatType.GROUPS, track_msg)
    )
    
    return application

# ==================== MAIN ====================
def main():
    # Initialize database
    asyncio.run(init_db())
    
    # Setup bot handlers
    setup_handlers()
    
    logger.info("🚀 Ice Reign Machine v6.5 started")
    logger.info(f"🌐 Port: {PORT}")
    logger.info(f"🌐 Webhook: /webhook/telegram")
    logger.info(f"🌐 Health: /")
    
    # Start Flask server (keeps process alive)
    flask_app.run(
        host='0.0.0.0',
        port=PORT,
        threaded=True,
        debug=False,
        use_reloader=False
    )

if __name__ == "__main__":
    main()
