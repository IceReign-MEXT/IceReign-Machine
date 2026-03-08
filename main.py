#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════╗
║                    ICE REIGN MACHINE v7.0                        ║
║              Professional Airdrop Distribution System              ║
║                                                                  ║
║  Revenue Model: Subscriptions + Transaction Fees + Premium       ║
║  Blockchain: Solana (Helius RPC)                                ║
║  Database: PostgreSQL (Supabase)                                  ║
║  Deployment: Render.com (Auto-scaling)                          ║
╚══════════════════════════════════════════════════════════════════╝
"""

import os
import asyncio
import logging
import ssl
import urllib.request
import json
import psycopg2
from datetime import datetime, timedelta
from decimal import Decimal
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

# ==================== CONFIGURATION ====================
BOT_TOKEN = os.getenv('BOT_TOKEN')
ADMIN_ID = os.getenv('ADMIN_ID')
SOL_MAIN = os.getenv('SOL_MAIN')
HELIUS_API_KEY = os.getenv('HELIUS_API_KEY')
DATABASE_URL = os.getenv('DATABASE_URL')
RENDER_URL = os.getenv('RENDER_URL', 'https://icereign-machine-des3.onrender.com')
PORT = int(os.getenv('PORT', 10000))

# Pricing (SOL)
SUBSCRIPTION_PRICE = float(os.getenv('SUBSCRIPTION_PRICE', 0.5))
PRO_PRICE = float(os.getenv('PRO_PRICE', 3.0))
ENTERPRISE_PRICE = float(os.getenv('ENTERPRISE_PRICE', 10.0))

# Revenue sharing
PLATFORM_FEE_PERCENT = 2.0  # 2% per distribution

# Globals
bot = Bot(token=BOT_TOKEN)
application = None

# ==================== WEBHOOK MANAGEMENT ====================
def setup_webhook():
    """Auto-configure Telegram webhook on startup"""
    try:
        webhook_url = f"{RENDER_URL}/webhook/telegram"
        api_url = f"https://api.telegram.org/bot{BOT_TOKEN}/setWebhook?url={webhook_url}"
        
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        
        response = urllib.request.urlopen(api_url, context=ctx, timeout=30)
        result = json.loads(response.read().decode())
        
        if result.get('ok'):
            logger.info(f"✅ Webhook active: {webhook_url}")
            return True
        logger.error(f"❌ Webhook failed: {result}")
        return False
    except Exception as e:
        logger.error(f"⚠️ Webhook error: {e}")
        return False

# ==================== FLASK APPLICATION ====================
flask_app = Flask(__name__)

@flask_app.route('/')
def health_check():
    """Health check for Render monitoring"""
    return jsonify({
        'status': 'ICE REIGN ONLINE',
        'version': '7.0.0',
        'revenue_wallet': SOL_MAIN,
        'platform_fee': f"{PLATFORM_FEE_PERCENT}%",
        'time': datetime.now().isoformat(),
        'active': True
    }), 200

@flask_app.route('/api/stats')
def api_stats():
    """Public API for stats (for your website)"""
    conn = get_db()
    cur = conn.cursor()
    
    cur.execute("SELECT COUNT(*) FROM dev_subscriptions WHERE status = 'active'")
    active_devs = cur.fetchone()[0]
    
    cur.execute("SELECT COALESCE(SUM(amount_sol), 0) FROM platform_payments")
    total_revenue = float(cur.fetchone()[0] or 0)
    
    cur.execute("SELECT COUNT(*) FROM protected_groups WHERE is_active = 1")
    protected_groups = cur.fetchone()[0]
    
    cur.close()
    conn.close()
    
    return jsonify({
        'active_developers': active_devs,
        'total_revenue_sol': total_revenue,
        'protected_groups': protected_groups,
        'platform_fee': PLATFORM_FEE_PERCENT
    }), 200

@flask_app.route('/webhook/telegram', methods=['POST'])
def telegram_webhook():
    """Process Telegram updates"""
    try:
        data = request.get_json(force=True)
        update = Update.de_json(data, bot)
        asyncio.create_task(process_update(update))
        return jsonify({'ok': True}), 200
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return jsonify({'ok': False, 'error': str(e)}), 500

@flask_app.route('/webhook/helius', methods=['POST'])
def helius_webhook():
    """Auto-detect new token launches"""
    data = request.json or {}
    logger.info(f"🔔 Token detected: {data}")
    
    # Auto-create campaign for new tokens
    if data.get('type') == 'TOKEN_MINT':
        asyncio.create_task(auto_create_campaign(data))
    
    return jsonify({'received': True, 'processed': True}), 200

async def process_update(update: Update):
    """Route update to handlers"""
    try:
        await application.process_update(update)
    except Exception as e:
        logger.error(f"Update error: {e}")

async def auto_create_campaign(token_data):
    """Auto-create airdrop campaign for new token"""
    logger.info(f"🎯 Auto-creating campaign for: {token_data}")

# ==================== DATABASE LAYER ====================
def get_db():
    """Get database connection"""
    return psycopg2.connect(DATABASE_URL)

def init_database():
    """Initialize all tables"""
    conn = get_db()
    cur = conn.cursor()
    
    # Developers table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS dev_subscriptions (
            id SERIAL PRIMARY KEY,
            telegram_id TEXT UNIQUE NOT NULL,
            username TEXT,
            tier TEXT DEFAULT 'none',
            status TEXT DEFAULT 'inactive',
            subscription_start TIMESTAMP,
            subscription_end TIMESTAMP,
            total_paid_sol DECIMAL(20,9) DEFAULT 0,
            wallet_address TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # Revenue tracking
    cur.execute("""
        CREATE TABLE IF NOT EXISTS platform_payments (
            id SERIAL PRIMARY KEY,
            dev_telegram_id TEXT NOT NULL,
            amount_sol DECIMAL(20,9) NOT NULL,
            tx_signature TEXT UNIQUE,
            payment_type TEXT DEFAULT 'subscription',
            status TEXT DEFAULT 'confirmed',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # Protected groups
    cur.execute("""
        CREATE TABLE IF NOT EXISTS protected_groups (
            id SERIAL PRIMARY KEY,
            dev_telegram_id TEXT NOT NULL,
            telegram_chat_id TEXT UNIQUE NOT NULL,
            group_name TEXT,
            member_count INTEGER DEFAULT 0,
            messages_tracked INTEGER DEFAULT 0,
            spam_blocked INTEGER DEFAULT 0,
            is_active BOOLEAN DEFAULT TRUE,
            activated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # User engagement
    cur.execute("""
        CREATE TABLE IF NOT EXISTS user_engagement (
            id SERIAL PRIMARY KEY,
            group_chat_id TEXT NOT NULL,
            telegram_id TEXT NOT NULL,
            username TEXT,
            message_count INTEGER DEFAULT 0,
            reaction_count INTEGER DEFAULT 0,
            invite_count INTEGER DEFAULT 0,
            wallet_address TEXT,
            first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_active TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(group_chat_id, telegram_id)
        )
    """)
    
    # Token campaigns
    cur.execute("""
        CREATE TABLE IF NOT EXISTS token_campaigns (
            id SERIAL PRIMARY KEY,
            dev_telegram_id TEXT NOT NULL,
            group_chat_id TEXT NOT NULL,
            token_mint TEXT NOT NULL,
            token_symbol TEXT,
            token_name TEXT,
            total_supply DECIMAL(20,9),
            airdrop_amount DECIMAL(20,9),
            min_messages INTEGER DEFAULT 10,
            min_days INTEGER DEFAULT 7,
            distribution_type TEXT DEFAULT 'engagement',
            status TEXT DEFAULT 'active',
            platform_fee_paid BOOLEAN DEFAULT FALSE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            ends_at TIMESTAMP
        )
    """)
    
    # Airdrop distributions
    cur.execute("""
        CREATE TABLE IF NOT EXISTS airdrop_distributions (
            id SERIAL PRIMARY KEY,
            campaign_id INTEGER REFERENCES token_campaigns(id),
            telegram_id TEXT NOT NULL,
            wallet_address TEXT NOT NULL,
            amount DECIMAL(20,9) NOT NULL,
            platform_fee DECIMAL(20,9) NOT NULL,
            tx_signature TEXT,
            status TEXT DEFAULT 'pending',
            distributed_at TIMESTAMP
        )
    """)
    
    conn.commit()
    cur.close()
    conn.close()
    logger.info("✅ Database initialized")

# ==================== SOLANA INTEGRATION ====================
async def verify_sol_payment(tx_sig: str, expected: float) -> bool:
    """Verify SOL payment via Helius"""
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
                        amount = float(t['amount']) / 1e9
                        return amount >= expected * 0.95
                return False
    except Exception as e:
        logger.error(f"Payment verify error: {e}")
        return False

# ==================== BUSINESS LOGIC ====================
def get_dev_subscription(telegram_id: str) -> dict:
    """Get developer subscription"""
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM dev_subscriptions WHERE telegram_id = %s",
        (telegram_id,)
    )
    row = cur.fetchone()
    cur.close()
    conn.close()
    
    if row:
        return {
            'id': row[0], 'telegram_id': row[1], 'username': row[2],
            'tier': row[3], 'status': row[4], 'subscription_end': row[6]
        }
    return None

def get_platform_stats() -> dict:
    """Get revenue statistics"""
    conn = get_db()
    cur = conn.cursor()
    
    cur.execute("SELECT COALESCE(SUM(amount_sol), 0) FROM platform_payments")
    total_revenue = float(cur.fetchone()[0] or 0)
    
    cur.execute("SELECT COUNT(*) FROM dev_subscriptions WHERE status = 'active'")
    active_devs = cur.fetchone()[0]
    
    cur.execute("SELECT COUNT(*) FROM protected_groups WHERE is_active = TRUE")
    active_groups = cur.fetchone()[0]
    
    cur.execute("""
        SELECT COALESCE(SUM(platform_fee), 0) 
        FROM airdrop_distributions 
        WHERE status = 'completed'
    """)
    distribution_fees = float(cur.fetchone()[0] or 0)
    
    cur.close()
    conn.close()
    
    return {
        'total_revenue_sol': total_revenue,
        'active_developers': active_devs,
        'protected_groups': active_groups,
        'distribution_fees': distribution_fees,
        'total_profit': total_revenue + distribution_fees
    }

# ==================== TELEGRAM HANDLERS ====================
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Main entry point"""
    user = update.effective_user
    chat_type = update.effective_chat.type
    
    if chat_type == "private":
        # Admin panel
        if str(user.id) == ADMIN_ID:
            stats = get_platform_stats()
            await update.message.reply_text(
                f"👑 *ADMIN DASHBOARD*\n\n"
                f"💰 Total Revenue: `{stats['total_profit']:.4f}` SOL\n"
                f"💎 From Subs: `{stats['total_revenue_sol']:.4f}` SOL\n"
                f"🎯 From Fees: `{stats['distribution_fees']:.4f}` SOL\n"
                f"👨‍💻 Active Devs: `{stats['active_developers']}`\n"
                f"👥 Protected Groups: `{stats['protected_groups']}`\n\n"
                f"Your Wallet: `{SOL_MAIN}`",
                parse_mode=ParseMode.MARKDOWN
            )
            return
        
        # User dashboard
        dev = get_dev_subscription(str(user.id))
        if dev and dev['status'] == 'active':
            await update.message.reply_text(
                f"👨‍💻 *DEVELOPER DASHBOARD*\n\n"
                f"Tier: `{dev['tier'].upper()}`\n"
                f"Status: `ACTIVE`\n"
                f"Expires: `{dev['subscription_end']}`\n\n"
                f"Commands:\n"
                f"/create - Start new airdrop\n"
                f"/groups - Manage your groups\n"
                f"/stats - View analytics\n"
                f"/wallet - Set payout wallet",
                parse_mode=ParseMode.MARKDOWN
            )
        else:
            # Subscription options
            keyboard = [
                [InlineKeyboardButton(f"💎 Basic - {SUBSCRIPTION_PRICE} SOL/month", callback_data="sub_basic")],
                [InlineKeyboardButton(f"👑 Pro - {PRO_PRICE} SOL/month", callback_data="sub_pro")],
                [InlineKeyboardButton(f"🏢 Enterprise - {ENTERPRISE_PRICE} SOL/month", callback_data="sub_enterprise")]
            ]
            await update.message.reply_text(
                f"🚀 *ICE REIGN MACHINE*\n\n"
                f"Professional Airdrop Distribution Platform\n\n"
                f"*Features:*\n"
                f"• 🤖 Auto-token detection\n"
                f"• 📊 Engagement analytics\n"
                f"• 🛡 Anti-spam protection\n"
                f"• ⚡ One-click distribution\n"
                f"• 💰 Revenue: 2% platform fee\n\n"
                f"Select your tier:",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode=ParseMode.MARKDOWN
            )

async def cmd_wallet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Register developer wallet"""
    if len(context.args) != 1:
        await update.message.reply_text(
            "💼 *Set Your Payout Wallet*\n\n"
            "Usage: `/wallet YOUR_SOL_ADDRESS`\n\n"
            "This is where you receive airdrop fees.",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    wallet = context.args[0].strip()
    if len(wallet) < 32 or len(wallet) > 44:
        await update.message.reply_text("❌ Invalid Solana address")
        return
    
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        UPDATE dev_subscriptions 
        SET wallet_address = %s 
        WHERE telegram_id = %s
    """, (wallet, str(update.effective_user.id)))
    conn.commit()
    cur.close()
    conn.close()
    
    await update.message.reply_text(
        f"✅ *Payout Wallet Set*\n\n`{wallet}`",
        parse_mode=ParseMode.MARKDOWN
    )

async def cmd_airdrop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Check airdrop eligibility"""
    user_id = str(update.effective_user.id)
    chat_id = str(update.effective_chat.id)
    
    conn = get_db()
    cur = conn.cursor()
    
    # Get user stats
    cur.execute("""
        SELECT message_count, reaction_count, wallet_address 
        FROM user_engagement 
        WHERE group_chat_id = %s AND telegram_id = %s
    """, (chat_id, user_id))
    row = cur.fetchone()
    
    # Get active campaigns
    cur.execute("""
        SELECT token_symbol, min_messages, airdrop_amount 
        FROM token_campaigns 
        WHERE group_chat_id = %s AND status = 'active'
    """, (chat_id,))
    campaigns = cur.fetchall()
    
    cur.close()
    conn.close()
    
    messages = row[0] if row else 0
    wallet = row[2] if row else None
    
    text = f"📊 *Your Airdrop Status*\n\n"
    text += f"💬 Messages: `{messages}`\n"
    
    if wallet:
        text += f"💳 Wallet: `{wallet[:20]}...`\n\n"
    else:
        text += f"⚠️ No wallet! Use /wallet\n\n"
    
    if campaigns:
        text += f"🎯 *Active Campaigns:*\n"
        for camp in campaigns:
            symbol, min_msg, amount = camp
            status = "✅ ELIGIBLE" if messages >= min_msg else f"⏳ Need {min_msg - messages} more"
            text += f"• {symbol}: {status} ({amount} tokens)\n"
    else:
        text += "No active campaigns currently."
    
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)

async def cmd_activate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Activate group protection (admin only)"""
    chat = update.effective_chat
    user = update.effective_user
    
    if chat.type == "private":
        await update.message.reply_text("❌ Use this in a group!")
        return
    
    # Check admin
    member = await context.bot.get_chat_member(chat.id, user.id)
    if member.status not in [ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER]:
        await update.message.reply_text("❌ Admin only!")
        return
    
    # Check subscription
    dev = get_dev_subscription(str(user.id))
    if not dev or dev['status'] != 'active':
        await update.message.reply_text(
            "❌ *Subscription Required*\n\n"
            "DM @IceReignMachine_bot to subscribe",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    # Activate
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO protected_groups (dev_telegram_id, telegram_chat_id, group_name, is_active)
        VALUES (%s, %s, %s, TRUE)
        ON CONFLICT (telegram_chat_id) DO UPDATE SET is_active = TRUE
    """, (str(user.id), str(chat.id), chat.title))
    conn.commit()
    cur.close()
    conn.close()
    
    # Set commands
    await context.bot.set_my_commands([
        BotCommand("wallet", "Register SOL wallet"),
        BotCommand("airdrop", "Check eligibility"),
        BotCommand("stats", "View group stats")
    ], scope={"type": "chat", "chat_id": chat.id})
    
    await update.message.reply_text(
        f"✅ *GROUP ACTIVATED*\n\n"
        f"🛡 Anti-spam: ON\n"
        f"📊 Tracking: ACTIVE\n"
        f"🚀 Airdrops: ENABLED\n\n"
        f"Users can now earn tokens by chatting!",
        parse_mode=ParseMode.MARKDOWN
    )

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle subscription callbacks"""
    query = update.callback_query
    await query.answer()
    
    tier = query.data.replace("sub_", "")
    prices = {
        'basic': SUBSCRIPTION_PRICE,
        'pro': PRO_PRICE,
        'enterprise': ENTERPRISE_PRICE
    }
    amount = prices.get(tier, SUBSCRIPTION_PRICE)
    
    context.user_data['payment'] = {'tier': tier, 'amount': amount}
    
    await query.edit_message_text(
        f"💳 *{tier.upper()} SUBSCRIPTION*\n\n"
        f"Amount: `{amount}` SOL\n"
        f"Duration: 30 days\n"
        f"Platform Fee: {PLATFORM_FEE_PERCENT}% per distribution\n\n"
        f"Send `{amount}` SOL to:\n"
        f"`{SOL_MAIN}`\n\n"
        f"Reply with transaction signature to activate:",
        parse_mode=ParseMode.MARKDOWN
    )
    return 1

async def process_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Verify and process subscription payment"""
    tx_sig = update.message.text.strip()
    user = update.effective_user
    payment = context.user_data.get('payment')
    
    if not payment:
        await update.message.reply_text("Session expired. Use /start")
        return ConversationHandler.END
    
    await update.message.reply_text("⏳ Verifying payment...")
    
    if await verify_sol_payment(tx_sig, payment['amount']):
        expiry = datetime.now() + timedelta(days=30)
        
        conn = get_db()
        cur = conn.cursor()
        
        # Insert or update subscription
        cur.execute("""
            INSERT INTO dev_subscriptions 
            (telegram_id, username, tier, status, subscription_start, subscription_end, total_paid_sol)
            VALUES (%s, %s, %s, 'active', NOW(), %s, %s)
            ON CONFLICT (telegram_id) DO UPDATE SET
            tier = EXCLUDED.tier,
            status = 'active',
            subscription_end = EXCLUDED.subscription_end,
            total_paid_sol = dev_subscriptions.total_paid_sol + EXCLUDED.total_paid_sol
        """, (str(user.id), user.username, payment['tier'], expiry, payment['amount']))
        
        # Record payment
        cur.execute("""
            INSERT INTO platform_payments (dev_telegram_id, amount_sol, tx_signature, payment_type)
            VALUES (%s, %s, %s, 'subscription')
        """, (str(user.id), payment['amount'], tx_sig))
        
        conn.commit()
        cur.close()
        conn.close()
        
        # Notify admin
        await context.bot.send_message(
            ADMIN_ID,
            f"💰 *NEW PAYMENT*\n\n"
            f"User: @{user.username}\n"
            f"Tier: {payment['tier'].upper()}\n"
            f"Amount: {payment['amount']} SOL",
            parse_mode=ParseMode.MARKDOWN
        )
        
        await update.message.reply_text(
            f"✅ *ACTIVATED!*\n\n"
            f"Tier: `{payment['tier'].upper()}`\n"
            f"Expires: `{expiry.strftime('%Y-%m-%d')}`\n\n"
            f"Add me to your group and use /activate",
            parse_mode=ParseMode.MARKDOWN
        )
    else:
        await update.message.reply_text(
            "❌ *Payment Not Found*\n\n"
            "Please check:\n"
            "• Transaction is confirmed\n"
            "• Amount is correct\n"
            "• Sent to right address",
            parse_mode=ParseMode.MARKDOWN
        )
    
    return ConversationHandler.END

async def track_engagement(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Track user engagement in groups"""
    msg = update.message
    if not msg or not msg.text:
        return
    
    chat_id = str(update.effective_chat.id)
    user = update.effective_user
    
    # Skip admins
    try:
        member = await context.bot.get_chat_member(chat_id, user.id)
        if member.status in [ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER]:
            return
    except:
        return
    
    # Check if group is protected
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "SELECT 1 FROM protected_groups WHERE telegram_chat_id = %s AND is_active = TRUE",
        (chat_id,)
    )
    if not cur.fetchone():
        cur.close()
        conn.close()
        return
    
    # Update engagement
    cur.execute("""
        INSERT INTO user_engagement (group_chat_id, telegram_id, username, message_count)
        VALUES (%s, %s, %s, 1)
        ON CONFLICT (group_chat_id, telegram_id) DO UPDATE SET
        message_count = user_engagement.message_count + 1,
        last_active = NOW()
    """, (chat_id, str(user.id), user.username))
    conn.commit()
    cur.close()
    conn.close()
    
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
            await asyncio.sleep(5)
            await warning.delete()
            
            # Log spam block
            conn = get_db()
            cur = conn.cursor()
            cur.execute(
                "UPDATE protected_groups SET spam_blocked = spam_blocked + 1 WHERE telegram_chat_id = %s",
                (chat_id,)
            )
            conn.commit()
            cur.close()
            conn.close()
        except:
            pass

# ==================== INITIALIZATION ====================
def setup_application():
    """Setup Telegram application"""
    global application
    application = Application.builder().token(BOT_TOKEN).updater(None).build()
    
    # Conversation for payments
    conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(callback_handler, pattern="^sub_")],
        states={1: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_payment)]},
        fallbacks=[]
    )
    
    # Commands
    application.add_handler(CommandHandler("start", cmd_start))
    application.add_handler(CommandHandler("wallet", cmd_wallet))
    application.add_handler(CommandHandler("airdrop", cmd_airdrop))
    application.add_handler(CommandHandler("activate", cmd_activate))
    application.add_handler(conv_handler)
    
    # Group tracking
    application.add_handler(
        MessageHandler(filters.TEXT & filters.ChatType.GROUPS, track_engagement)
    )
    
    return application

def main():
    """Main entry point"""
    logger.info("🔥 Initializing Ice Reign Machine v7.0")
    
    # Setup webhook
    if not setup_webhook():
        logger.warning("⚠️ Webhook setup failed - may already be configured")
    
    # Initialize database
    init_database()
    
    # Setup bot
    setup_application()
    
    logger.info(f"🚀 System ONLINE at {RENDER_URL}")
    logger.info(f"💰 Revenue wallet: {SOL_MAIN}")
    logger.info(f"📊 Platform fee: {PLATFORM_FEE_PERCENT}%")
    
    # Start Flask server
    flask_app.run(
        host='0.0.0.0',
        port=PORT,
        threaded=True,
        debug=False,
        use_reloader=False
    )

if __name__ == "__main__":
    main()
