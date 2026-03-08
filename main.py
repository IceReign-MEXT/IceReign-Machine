#!/usr/bin/env python3
"""
ICE REIGN MACHINE v8.0 - AUTONOMOUS MONEY PRINTER
Self-healing, auto-scaling, zero-maintenance revenue generator
"""
import os
import sys
import asyncio
import logging
import ssl
import urllib.request
import json
import threading
import time
import requests
from datetime import datetime, timedelta
from flask import Flask, request, jsonify
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand, Bot
from telegram.constants import ParseMode, ChatMemberStatus
from telegram.ext import (
    Application, CommandHandler, ContextTypes, MessageHandler,
    filters, CallbackQueryHandler, ConversationHandler
)
import aiohttp
from dotenv import load_dotenv
import pg8000
from pg8000.dbapi import Connection

load_dotenv()

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

class Config:
    BOT_TOKEN = os.getenv('BOT_TOKEN')
    ADMIN_ID = os.getenv('ADMIN_ID')
    SOL_MAIN = os.getenv('SOL_MAIN')
    HELIUS_API_KEY = os.getenv('HELIUS_API_KEY')
    DATABASE_URL = os.getenv('DATABASE_URL')
    RENDER_URL = os.getenv('RENDER_URL', 'https://icereign-machine.onrender.com')
    VIP_CHANNEL_ID = os.getenv('VIP_CHANNEL_ID')
    PORT = int(os.getenv('PORT', 10000))
    SUBSCRIPTION_PRICE = float(os.getenv('SUBSCRIPTION_PRICE', 0.5))
    PRO_PRICE = float(os.getenv('PRO_PRICE', 3.0))
    ENTERPRISE_PRICE = float(os.getenv('ENTERPRISE_PRICE', 10.0))
    PLATFORM_FEE = float(os.getenv('PLATFORM_FEE', 2.0))

class Database:
    _conn = None
    
    @classmethod
    def get_conn(cls):
        if cls._conn is None:
            import urllib.parse
            parsed = urllib.parse.urlparse(Config.DATABASE_URL)
            cls._conn = pg8000.connect(
                user=parsed.username,
                password=parsed.password,
                host=parsed.hostname,
                port=parsed.port or 5432,
                database=parsed.path[1:],
                ssl_context=True
            )
        return cls._conn
    
    @classmethod
    def put_conn(cls, conn):
        pass

class WebhookManager:
    def __init__(self):
        self.bot = Bot(token=Config.BOT_TOKEN)
        self.healthy = False
        
    def setup(self):
        for attempt in range(5):
            try:
                webhook_url = f"{Config.RENDER_URL}/webhook/telegram"
                delete_url = f"https://api.telegram.org/bot{Config.BOT_TOKEN}/deleteWebhook"
                urllib.request.urlopen(delete_url, timeout=10)
                time.sleep(1)
                api_url = f"https://api.telegram.org/bot{Config.BOT_TOKEN}/setWebhook?url={webhook_url}&drop_pending_updates=true"
                ctx = ssl.create_default_context()
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE
                response = urllib.request.urlopen(api_url, context=ctx, timeout=30)
                result = json.loads(response.read().decode())
                if result.get('ok'):
                    logger.info(f"Webhook set: {webhook_url}")
                    self.healthy = True
                    return True
            except Exception as e:
                logger.error(f"Webhook attempt {attempt + 1} failed: {e}")
                time.sleep(2 ** attempt)
        return False
    
    def health_check(self):
        while True:
            time.sleep(30)
            try:
                info_url = f"https://api.telegram.org/bot{Config.BOT_TOKEN}/getWebhookInfo"
                response = urllib.request.urlopen(info_url, timeout=10)
                data = json.loads(response.read().decode())
                if not data.get('ok') or not data['result'].get('url'):
                    logger.warning("Webhook lost, auto-healing...")
                    self.setup()
            except Exception as e:
                logger.error(f"Health check error: {e}")

flask_app = Flask(__name__)
webhook_manager = WebhookManager()
application = None
start_time = time.time()

@flask_app.route('/')
def health():
    return jsonify({
        'status': 'ICE REIGN AUTONOMOUS',
        'version': '8.0.0',
        'revenue_wallet': Config.SOL_MAIN,
        'platform_fee': f"{Config.PLATFORM_FEE}%",
        'webhook_healthy': webhook_manager.healthy,
        'time': datetime.now().isoformat()
    }), 200

@flask_app.route('/webhook/telegram', methods=['POST'])
def telegram_webhook():
    try:
        data = request.get_json(force=True)
        def process():
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                update = Update.de_json(data, webhook_manager.bot)
                loop.run_until_complete(application.process_update(update))
                loop.close()
            except Exception as e:
                logger.error(f"Update processing error: {e}")
        threading.Thread(target=process, daemon=True).start()
        return jsonify({'ok': True}), 200
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return jsonify({'ok': False}), 500

@flask_app.route('/api/stats')
def api_stats():
    try:
        conn = Database.get_conn()
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM dev_subscriptions WHERE status='active'")
        active_users = cur.fetchone()[0]
        cur.execute("SELECT COALESCE(SUM(amount_sol), 0) FROM platform_payments")
        revenue = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM protected_groups WHERE is_active=1")
        groups = cur.fetchone()[0]
        return jsonify({
            'active_subscribers': active_users,
            'total_revenue_sol': float(revenue),
            'protected_groups': groups
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

def init_db():
    conn = Database.get_conn()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS dev_subscriptions (
            id SERIAL PRIMARY KEY, telegram_id TEXT UNIQUE NOT NULL, username TEXT,
            tier TEXT DEFAULT 'none', status TEXT DEFAULT 'inactive',
            subscription_end TIMESTAMP, total_paid_sol REAL DEFAULT 0,
            wallet_address TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS platform_payments (
            id SERIAL PRIMARY KEY, dev_telegram_id TEXT NOT NULL,
            amount_sol REAL NOT NULL, tx_signature TEXT UNIQUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS protected_groups (
            id SERIAL PRIMARY KEY, dev_telegram_id TEXT NOT NULL,
            telegram_chat_id TEXT UNIQUE NOT NULL, group_name TEXT,
            is_active INTEGER DEFAULT 1, spam_blocked INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS user_engagement (
            group_chat_id TEXT NOT NULL, telegram_id TEXT NOT NULL,
            username TEXT, message_count INTEGER DEFAULT 0,
            wallet_address TEXT, last_message TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(group_chat_id, telegram_id)
        )
    """)
    conn.commit()
    logger.info("Database initialized")

async def verify_payment(tx_sig: str, expected: float) -> bool:
    try:
        async with aiohttp.ClientSession() as session:
            url = f"https://api.helius.xyz/v0/transactions/?api-key={Config.HELIUS_API_KEY}"
            async with session.post(url, json={"transactions": [tx_sig]}) as response:
                if response.status != 200:
                    return False
                data = await response.json()
                if not data or data[0].get('err'):
                    return False
                for transfer in data[0].get('nativeTransfers', []):
                    if transfer['toUserAccount'] == Config.SOL_MAIN:
                        amount = float(transfer['amount']) / 1e9
                        if amount >= expected * 0.95:
                            return True
                return False
    except Exception as e:
        logger.error(f"Payment verification error: {e}")
        return False

def get_dev_sub(telegram_id: str):
    try:
        conn = Database.get_conn()
        cur = conn.cursor()
        cur.execute("SELECT * FROM dev_subscriptions WHERE telegram_id = %s", (telegram_id,))
        row = cur.fetchone()
        if row:
            return {
                'id': row[0], 'telegram_id': row[1], 'username': row[2],
                'tier': row[3], 'status': row[4], 'subscription_end': str(row[5]),
                'total_paid': row[6], 'wallet': row[7]
            }
    except Exception as e:
        logger.error(f"DB error: {e}")
    return None

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if update.effective_chat.type != "private":
        return
    if str(user.id) == Config.ADMIN_ID:
        conn = Database.get_conn()
        cur = conn.cursor()
        cur.execute("SELECT COALESCE(SUM(amount_sol), 0) FROM platform_payments")
        total_revenue = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM dev_subscriptions WHERE status='active'")
        active_subs = cur.fetchone()[0]
        await update.message.reply_text(
            f"👑 *ADMIN PANEL*\n\n"
            f"💰 Total Revenue: `{total_revenue:.4f}` SOL\n"
            f"👥 Active Subscribers: `{active_subs}`\n"
            f"Wallet: `{Config.SOL_MAIN}`",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    dev = get_dev_sub(str(user.id))
    if dev and dev['status'] == 'active':
        await update.message.reply_text(
            f"👨‍💻 *YOUR DASHBOARD*\n\n"
            f"Tier: `{dev['tier'].upper()}` ✅\n"
            f"Paid: `{dev['total_paid']:.2f}` SOL\n"
            f"Expires: `{dev['subscription_end'][:10]}`",
            parse_mode=ParseMode.MARKDOWN
        )
    else:
        keyboard = [
            [InlineKeyboardButton(f"💎 Basic ({Config.SUBSCRIPTION_PRICE} SOL)", callback_data="sub_basic")],
            [InlineKeyboardButton(f"👑 Pro ({Config.PRO_PRICE} SOL)", callback_data="sub_pro")],
            [InlineKeyboardButton(f"🏢 Enterprise ({Config.ENTERPRISE_PRICE} SOL)", callback_data="sub_enterprise")]
        ]
        await update.message.reply_text(
            f"🚀 *ICE REIGN MACHINE*\n\n"
            f"*The #1 Automated Airdrop Platform*\n\n"
            f"✅ Auto token detection\n"
            f"✅ Engagement tracking\n"
            f"✅ Anti-spam protection\n"
            f"✅ One-click distribution\n\n"
            f"*Platform fee: Only {Config.PLATFORM_FEE}%*\n\n"
            f"🎯 *Choose your tier:*",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.MARKDOWN
        )

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data.startswith("sub_"):
        tier = query.data.replace("sub_", "")
        prices = {'basic': Config.SUBSCRIPTION_PRICE, 'pro': Config.PRO_PRICE, 'enterprise': Config.ENTERPRISE_PRICE}
        amount = prices.get(tier, Config.SUBSCRIPTION_PRICE)
        context.user_data['payment'] = {'tier': tier, 'amount': amount}
        await query.edit_message_text(
            f"💳 *{tier.upper()} SUBSCRIPTION*\n\n"
            f"Price: `{amount}` SOL (30 days)\n\n"
            f"📤 *Send exactly `{amount}` SOL to:*\n"
            f"`{Config.SOL_MAIN}`\n\n"
            f"⬇️ *Reply with your TX signature:*",
            parse_mode=ParseMode.MARKDOWN
        )
        return 1

async def process_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tx_sig = update.message.text.strip()
    user = update.effective_user
    payment = context.user_data.get('payment')
    if not payment:
        await update.message.reply_text("❌ Session expired. Use /start")
        return ConversationHandler.END
    await update.message.reply_text("⏳ Verifying payment...")
    if await verify_payment(tx_sig, payment['amount']):
        expiry = datetime.now() + timedelta(days=30)
        conn = Database.get_conn()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO dev_subscriptions (telegram_id, username, tier, status, subscription_end, total_paid_sol)
            VALUES (%s, %s, %s, 'active', %s, %s)
            ON CONFLICT (telegram_id) DO UPDATE SET
            tier = EXCLUDED.tier, status = 'active',
            subscription_end = EXCLUDED.subscription_end,
            total_paid_sol = dev_subscriptions.total_paid_sol + EXCLUDED.total_paid_sol
        """, (str(user.id), user.username, payment['tier'], expiry, payment['amount']))
        cur.execute("""
            INSERT INTO platform_payments (dev_telegram_id, amount_sol, tx_signature)
            VALUES (%s, %s, %s)
        """, (str(user.id), payment['amount'], tx_sig))
        conn.commit()
        await update.message.reply_text(
            f"✅ *ACTIVATED!*\n\n"
            f"Tier: `{payment['tier'].upper()}`\n"
            f"Expires: `{expiry.strftime('%Y-%m-%d')}`\n\n"
            f"Add me to group → /activate",
            parse_mode=ParseMode.MARKDOWN
        )
    else:
        await update.message.reply_text("❌ Payment not found")
    return ConversationHandler.END

async def cmd_activate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    if chat.type == "private":
        await update.message.reply_text("❌ Use in groups only!")
        return
    try:
        member = await context.bot.get_chat_member(chat.id, user.id)
        if member.status not in [ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER]:
            await update.message.reply_text("❌ Admin only!")
            return
    except:
        await update.message.reply_text("❌ Error checking admin status")
        return
    dev = get_dev_sub(str(user.id))
    if not dev or dev['status'] != 'active':
        await update.message.reply_text("❌ Subscribe first! DM me.")
        return
    conn = Database.get_conn()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO protected_groups (dev_telegram_id, telegram_chat_id, group_name, is_active)
        VALUES (%s, %s, %s, 1)
        ON CONFLICT (telegram_chat_id) DO UPDATE SET is_active = 1
    """, (str(user.id), str(chat.id), chat.title))
    conn.commit()
    await context.bot.set_my_commands([
        BotCommand("wallet", "Register SOL wallet"),
        BotCommand("airdrop", "Check eligibility")
    ], scope={"type": "chat", "chat_id": chat.id})
    await update.message.reply_text(
        f"✅ *GROUP ACTIVATED: {chat.title}*\n\n"
        f"🛡 Anti-spam: ON\n"
        f"📊 Tracking: ACTIVE\n"
        f"🚀 Airdrops: ENABLED",
        parse_mode=ParseMode.MARKDOWN
    )

async def track_engagement(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
    conn = Database.get_conn()
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM protected_groups WHERE telegram_chat_id = %s AND is_active = 1", (chat_id,))
    if not cur.fetchone():
        return
    cur.execute("""
        INSERT INTO user_engagement (group_chat_id, telegram_id, username, message_count)
        VALUES (%s, %s, %s, 1)
        ON CONFLICT (group_chat_id, telegram_id) DO UPDATE SET
        message_count = user_engagement.message_count + 1
    """, (chat_id, str(user.id), user.username))
    conn.commit()
    text_lower = msg.text.lower()
    spam_keywords = ['dm me', 't.me/', 'http', 'investment', 'forex']
    if sum(1 for k in spam_keywords if k in text_lower) >= 2:
        try:
            await msg.delete()
            warning = await context.bot.send_message(chat_id, "🛡 Spam removed")
            await asyncio.sleep(5)
            await warning.delete()
            cur.execute("UPDATE protected_groups SET spam_blocked = spam_blocked + 1 WHERE telegram_chat_id = %s", (chat_id,))
            conn.commit()
        except:
            pass

def setup_application():
    global application
    application = Application.builder().token(Config.BOT_TOKEN).updater(None).build()
    conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(callback_handler, pattern="^sub_")],
        states={1: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_payment)]},
        fallbacks=[]
    )
    application.add_handler(CommandHandler("start", cmd_start))
    application.add_handler(CommandHandler("activate", cmd_activate))
    application.add_handler(conv)
    application.add_handler(MessageHandler(filters.TEXT & filters.ChatType.GROUPS, track_engagement))
    return application

def main():
    logger.info("🔥 Ice Reign v8.0 Starting...")
    init_db()
    if not webhook_manager.setup():
        logger.error("Webhook setup failed, will retry...")
    health_thread = threading.Thread(target=webhook_manager.health_check, daemon=True)
    health_thread.start()
    setup_application()
    logger.info(f"🚀 ONLINE at {Config.RENDER_URL}")
    flask_app.run(host='0.0.0.0', port=Config.PORT, threaded=True, debug=False, use_reloader=False)

if __name__ == "__main__":
    main()
