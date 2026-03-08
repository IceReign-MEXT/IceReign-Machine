#!/usr/bin/env python3
"""
ICE REIGN MACHINE v7.1 - FIXED & WORKING
Revenue: Subscriptions + 2% Platform Fee
"""
import os
import asyncio
import logging
import ssl
import urllib.request
import json
import psycopg2
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
RENDER_URL = os.getenv('RENDER_URL', 'https://icereign-machine-des3.onrender.com')
VIP_CHANNEL_ID = os.getenv('VIP_CHANNEL_ID')
PORT = int(os.getenv('PORT', 10000))

# Pricing
SUBSCRIPTION_PRICE = float(os.getenv('SUBSCRIPTION_PRICE', 0.5))
PRO_PRICE = float(os.getenv('PRO_PRICE', 3.0))
ENTERPRISE_PRICE = float(os.getenv('ENTERPRISE_PRICE', 10.0))
PLATFORM_FEE = float(os.getenv('PLATFORM_FEE', 2.0))

# Globals
bot = Bot(token=BOT_TOKEN)
application = None

# ==================== WEBHOOK ====================
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
        return False
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return False

# ==================== FLASK ====================
flask_app = Flask(__name__)

@flask_app.route('/')
def health():
    return jsonify({
        'status': 'ICE REIGN ONLINE',
        'version': '7.1.0',
        'revenue_wallet': SOL_MAIN,
        'platform_fee': f"{PLATFORM_FEE}%",
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

async def handle_update(update: Update):
    try:
        await application.process_update(update)
    except Exception as e:
        logger.error(f"Update error: {e}")

# ==================== DATABASE ====================
def get_db():
    return psycopg2.connect(DATABASE_URL)

def init_db():
    conn = get_db()
    cur = conn.cursor()
    
    cur.execute("""
        CREATE TABLE IF NOT EXISTS dev_subscriptions (
            id SERIAL PRIMARY KEY,
            telegram_id TEXT UNIQUE NOT NULL,
            username TEXT,
            tier TEXT DEFAULT 'none',
            status TEXT DEFAULT 'inactive',
            subscription_end TIMESTAMP,
            total_paid_sol REAL DEFAULT 0,
            wallet_address TEXT
        )
    """)
    
    cur.execute("""
        CREATE TABLE IF NOT EXISTS platform_payments (
            id SERIAL PRIMARY KEY,
            dev_telegram_id TEXT NOT NULL,
            amount_sol REAL NOT NULL,
            tx_signature TEXT UNIQUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    cur.execute("""
        CREATE TABLE IF NOT EXISTS protected_groups (
            id SERIAL PRIMARY KEY,
            dev_telegram_id TEXT NOT NULL,
            telegram_chat_id TEXT UNIQUE NOT NULL,
            group_name TEXT,
            is_active INTEGER DEFAULT 1,
            spam_blocked INTEGER DEFAULT 0
        )
    """)
    
    cur.execute("""
        CREATE TABLE IF NOT EXISTS user_engagement (
            group_chat_id TEXT NOT NULL,
            telegram_id TEXT NOT NULL,
            message_count INTEGER DEFAULT 0,
            wallet_address TEXT,
            UNIQUE(group_chat_id, telegram_id)
        )
    """)
    
    conn.commit()
    cur.close()
    conn.close()
    logger.info("✅ Database ready")

# ==================== HELPERS ====================
def get_dev_sub(telegram_id: str):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM dev_subscriptions WHERE telegram_id = %s", (telegram_id,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    
    if row:
        return {
            'id': row[0], 'telegram_id': row[1], 'username': row[2],
            'tier': row[3], 'status': row[4], 'subscription_end': row[5],
            'total_paid': row[6], 'wallet': row[7]
        }
    return None

def get_revenue():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT COALESCE(SUM(amount_sol), 0) FROM platform_payments")
    result = cur.fetchone()[0]
    cur.close()
    conn.close()
    return float(result or 0)

async def notify_vip_channel(message: str):
    """Send notification to VIP channel"""
    if VIP_CHANNEL_ID:
        try:
            await bot.send_message(
                chat_id=VIP_CHANNEL_ID,
                text=message,
                parse_mode=ParseMode.MARKDOWN
            )
        except Exception as e:
            logger.error(f"VIP channel notify failed: {e}")

# ==================== SOLANA ====================
async def verify_payment(tx_sig: str, expected: float) -> bool:
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

# ==================== HANDLERS ====================
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat_type = update.effective_chat.type
    
    if chat_type == "private":
        # Admin
        if str(user.id) == ADMIN_ID:
            rev = get_revenue()
            await update.message.reply_text(
                f"👑 *ADMIN PANEL*\n\n"
                f"💰 Total Revenue: `{rev:.4f}` SOL\n"
                f"Wallet: `{SOL_MAIN}`\n\n"
                f"Commands:\n"
                f"/revenue - Detailed report\n"
                f"/broadcast - Message all users",
                parse_mode=ParseMode.MARKDOWN
            )
            return
        
        # User
        dev = get_dev_sub(str(user.id))
        if dev and dev['status'] == 'active':
            await update.message.reply_text(
                f"👨‍💻 *YOUR DASHBOARD*\n\n"
                f"Tier: `{dev['tier'].upper()}` ✅\n"
                f"Paid: `{dev['total_paid']:.2f}` SOL\n"
                f"Expires: `{dev['subscription_end']}`\n\n"
                f"Commands:\n"
                f"/prices - View pricing\n"
                f"/wallet - Set payout address\n"
                f"/create - Start airdrop campaign\n"
                f"/activate - Enable in group",
                parse_mode=ParseMode.MARKDOWN
            )
        else:
            keyboard = [
                [InlineKeyboardButton(f"💎 Basic ({SUBSCRIPTION_PRICE} SOL)", callback_data="sub_basic")],
                [InlineKeyboardButton(f"👑 Pro ({PRO_PRICE} SOL)", callback_data="sub_pro")],
                [InlineKeyboardButton(f"🏢 Enterprise ({ENTERPRISE_PRICE} SOL)", callback_data="sub_enterprise")]
            ]
            await update.message.reply_text(
                f"🚀 *ICE REIGN MACHINE*\n\n"
                f"Professional Airdrop Platform\n\n"
                f"*What you get:*\n"
                f"• Auto token detection\n"
                f"• Engagement tracking\n"
                f"• Anti-spam protection\n"
                f"• One-click distribution\n"
                f"• *Platform fee: {PLATFORM_FEE}%*\n\n"
                f"Select tier to subscribe:",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode=ParseMode.MARKDOWN
            )

async def cmd_prices(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show clear pricing"""
    await update.message.reply_text(
        f"💎 *SUBSCRIPTION PRICING*\n\n"
        f"*BASIC* - `{SUBSCRIPTION_PRICE}` SOL/month\n"
        f"• 1 group protection\n"
        f"• Basic analytics\n"
        f"• Standard support\n\n"
        f"*PRO* - `{PRO_PRICE}` SOL/month\n"
        f"• 5 group protection\n"
        f"• Advanced analytics\n"
        f"• Priority support\n"
        f"• Custom branding\n\n"
        f"*ENTERPRISE* - `{ENTERPRISE_PRICE}` SOL/month\n"
        f"• Unlimited groups\n"
        f"• White-label solution\n"
        f"• API access\n"
        f"• Dedicated support\n\n"
        f"*Platform fee: {PLATFORM_FEE}%* on all distributions\n\n"
        f"Use /start to subscribe",
        parse_mode=ParseMode.MARKDOWN
    )

async def cmd_wallet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) != 1:
        await update.message.reply_text(
            "💼 *Set Payout Wallet*\n\n"
            "Usage: `/wallet YOUR_SOL_ADDRESS`\n\n"
            "This is where you receive funds.",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    wallet = context.args[0].strip()
    if len(wallet) < 32:
        await update.message.reply_text("❌ Invalid address")
        return
    
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        UPDATE dev_subscriptions SET wallet_address = %s WHERE telegram_id = %s
    """, (wallet, str(update.effective_user.id)))
    conn.commit()
    cur.close()
    conn.close()
    
    await update.message.reply_text(
        f"✅ *Wallet Set*\n\n`{wallet}`",
        parse_mode=ParseMode.MARKDOWN
    )

async def cmd_airdrop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    user_id = str(update.effective_user.id)
    
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "SELECT message_count, wallet_address FROM user_engagement WHERE group_chat_id = %s AND telegram_id = %s",
        (chat_id, user_id)
    )
    row = cur.fetchone()
    cur.close()
    conn.close()
    
    messages = row[0] if row else 0
    wallet = row[1] if row else None
    
    text = f"📊 *Your Status*\n\nMessages: `{messages}`\n"
    if wallet:
        text += f"Wallet: `{wallet[:20]}...`\n\n"
    else:
        text += "⚠️ No wallet! Use /wallet\n\n"
    text += "Keep chatting to earn airdrops!"
    
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)

async def cmd_activate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    
    if chat.type == "private":
        await update.message.reply_text("❌ Use in group!")
        return
    
    member = await context.bot.get_chat_member(chat.id, user.id)
    if member.status not in [ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER]:
        await update.message.reply_text("❌ Admin only!")
        return
    
    dev = get_dev_sub(str(user.id))
    if not dev or dev['status'] != 'active':
        await update.message.reply_text(
            "❌ *Subscription Required*\n\n"
            "DM me to subscribe first.",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO protected_groups (dev_telegram_id, telegram_chat_id, group_name, is_active)
        VALUES (%s, %s, %s, 1)
        ON CONFLICT (telegram_chat_id) DO UPDATE SET is_active = 1
    """, (str(user.id), str(chat.id), chat.title))
    conn.commit()
    cur.close()
    conn.close()
    
    await context.bot.set_my_commands([
        BotCommand("wallet", "Register SOL wallet"),
        BotCommand("airdrop", "Check eligibility")
    ], scope={"type": "chat", "chat_id": chat.id})
    
    # Notify VIP channel
    await notify_vip_channel(
        f"🔔 *New Group Activated*\n\n"
        f"Group: {chat.title}\n"
        f"By: @{user.username or user.id}\n"
        f"Tier: {dev['tier'].upper()}"
    )
    
    await update.message.reply_text(
        "✅ *GROUP ACTIVATED*\n\n"
        "🛡 Anti-spam: ON\n"
        "📊 Tracking: ACTIVE\n"
        "🚀 Airdrops: ENABLED",
        parse_mode=ParseMode.MARKDOWN
    )

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    tier = query.data.replace("sub_", "")
    prices = {'basic': SUBSCRIPTION_PRICE, 'pro': PRO_PRICE, 'enterprise': ENTERPRISE_PRICE}
    amount = prices.get(tier, SUBSCRIPTION_PRICE)
    
    context.user_data['payment'] = {'tier': tier, 'amount': amount}
    
    await query.edit_message_text(
        f"💳 *{tier.upper()} SUBSCRIPTION*\n\n"
        f"Price: `{amount}` SOL (30 days)\n"
        f"Platform fee: {PLATFORM_FEE}% per distribution\n\n"
        f"Send `{amount}` SOL to:\n"
        f"`{SOL_MAIN}`\n\n"
        f"Reply with TX signature:",
        parse_mode=ParseMode.MARKDOWN
    )
    return 1

async def process_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tx_sig = update.message.text.strip()
    user = update.effective_user
    payment = context.user_data.get('payment')
    
    if not payment:
        await update.message.reply_text("Session expired")
        return ConversationHandler.END
    
    await update.message.reply_text("⏳ Verifying...")
    
    if await verify_payment(tx_sig, payment['amount']):
        expiry = datetime.now() + timedelta(days=30)
        
        conn = get_db()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO dev_subscriptions (telegram_id, username, tier, status, subscription_end, total_paid_sol)
            VALUES (%s, %s, %s, 'active', %s, %s)
            ON CONFLICT (telegram_id) DO UPDATE SET
            tier = EXCLUDED.tier, status = 'active', subscription_end = EXCLUDED.subscription_end,
            total_paid_sol = dev_subscriptions.total_paid_sol + EXCLUDED.total_paid_sol
        """, (str(user.id), user.username, payment['tier'], expiry, payment['amount']))
        
        cur.execute("""
            INSERT INTO platform_payments (dev_telegram_id, amount_sol, tx_signature)
            VALUES (%s, %s, %s)
        """, (str(user.id), payment['amount'], tx_sig))
        conn.commit()
        cur.close()
        conn.close()
        
        # Notify channels
        await context.bot.send_message(
            ADMIN_ID,
            f"💰 *NEW PAYMENT*\n\n"
            f"User: @{user.username}\n"
            f"Tier: {payment['tier'].upper()}\n"
            f"Amount: {payment['amount']} SOL",
            parse_mode=ParseMode.MARKDOWN
        )
        
        await notify_vip_channel(
            f"💎 *New {payment['tier'].upper()} Subscriber*\n\n"
            f"@{user.username or user.id} just paid {payment['amount']} SOL!"
        )
        
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

async def track_engagement(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
    
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM protected_groups WHERE telegram_chat_id = %s AND is_active = 1", (chat_id,))
    if not cur.fetchone():
        cur.close()
        conn.close()
        return
    
    cur.execute("""
        INSERT INTO user_engagement (group_chat_id, telegram_id, username, message_count)
        VALUES (%s, %s, %s, 1)
        ON CONFLICT (group_chat_id, telegram_id) DO UPDATE SET
        message_count = user_engagement.message_count + 1
    """, (chat_id, str(user.id), user.username))
    conn.commit()
    cur.close()
    conn.close()
    
    # Anti-spam
    text_lower = msg.text.lower()
    spam = ['dm me', 'http', 't.me/', 'investment', 'forex']
    if sum(1 for k in spam if k in text_lower) >= 2:
        try:
            await msg.delete()
            warning = await context.bot.send_message(chat_id, "🛡 Spam removed")
            await asyncio.sleep(5)
            await warning.delete()
            
            conn = get_db()
            cur = conn.cursor()
            cur.execute("UPDATE protected_groups SET spam_blocked = spam_blocked + 1 WHERE telegram_chat_id = %s", (chat_id,))
            conn.commit()
            cur.close()
            conn.close()
        except:
            pass

def setup_application():
    global application
    application = Application.builder().token(BOT_TOKEN).updater(None).build()
    
    conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(callback_handler, pattern="^sub_")],
        states={1: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_payment)]},
        fallbacks=[]
    )
    
    application.add_handler(CommandHandler("start", cmd_start))
    application.add_handler(CommandHandler("prices", cmd_prices))
    application.add_handler(CommandHandler("wallet", cmd_wallet))
    application.add_handler(CommandHandler("airdrop", cmd_airdrop))
    application.add_handler(CommandHandler("activate", cmd_activate))
    application.add_handler(conv)
    application.add_handler(MessageHandler(filters.TEXT & filters.ChatType.GROUPS, track_engagement))
    
    return application

def main():
    logger.info("🔥 Ice Reign v7.1 Starting...")
    
    setup_webhook()
    init_db()
    setup_application()
    
    logger.info(f"🚀 ONLINE at {RENDER_URL}")
    logger.info(f"💰 Wallet: {SOL_MAIN}")
    logger.info(f"📢 VIP Channel: {VIP_CHANNEL_ID}")
    
    flask_app.run(host='0.0.0.0', port=PORT, threaded=True, debug=False, use_reloader=False)

if __name__ == "__main__":
    main()
