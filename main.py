#!/usr/bin/env python3
"""
ICE REIGN MACHINE V5 - AUTONOMOUS AIRDROP EMPIRE
Revenue Model: Subscriptions + Distribution Fees
All payments flow to platform wallet: SOL_MAIN
"""

import os
import json
import asyncio
import logging
import threading
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Optional, Dict, List
import psycopg2
from psycopg2.extras import RealDictCursor

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

# Setup logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- CONFIGURATION FROM YOUR .ENV ---
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = os.getenv("ADMIN_ID")
VIP_CHANNEL_ID = os.getenv("VIP_CHANNEL_ID")
SOL_MAIN = os.getenv("SOL_MAIN")
ETH_MAIN = os.getenv("ETH_MAIN")
SOLANA_RPC = os.getenv("SOLANA_RPC")
DATABASE_URL = os.getenv("DATABASE_URL")
PORT = int(os.getenv("PORT", 8080))
SUBSCRIPTION_PRICE = float(os.getenv("SUBSCRIPTION_PRICE", 100))

# Extract Helius API key from RPC URL
HELIUS_API_KEY = SOLANA_RPC.split("api-key=")[1] if "api-key=" in SOLANA_RPC else ""

# Global DB connection
db_conn = None

# Conversation states
AWAITING_PAYMENT = 1

# --- FLASK WEB SERVER (For Render) ---
flask_app = Flask(__name__)

@flask_app.route("/")
def health():
    """Render health check"""
    return jsonify({
        "status": "ICE REIGN MACHINE ONLINE",
        "version": "5.0",
        "revenue_wallet": SOL_MAIN,
        "timestamp": datetime.utcnow().isoformat()
    }), 200

@flask_app.route("/helius/webhook", methods=['POST'])
def helius_webhook():
    """Helius webhook for token detection"""
    try:
        data = request.json
        # Process in background
        asyncio.create_task(process_token_launch(data))
        return jsonify({"status": "received"}), 200
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return jsonify({"error": str(e)}), 500

def run_flask():
    flask_app.run(host='0.0.0.0', port=PORT, threaded=True)

# --- DATABASE (psycopg2) ---
def init_db():
    global db_conn
    try:
        db_conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
        
        with db_conn.cursor() as cur:
            # Create tables
            cur.execute("""
                CREATE TABLE IF NOT EXISTS dev_subscriptions (
                    id SERIAL PRIMARY KEY,
                    telegram_id TEXT UNIQUE NOT NULL,
                    username TEXT,
                    tier TEXT DEFAULT 'none',
                    status TEXT DEFAULT 'inactive',
                    sol_wallet TEXT,
                    subscription_end TIMESTAMP,
                    created_at TIMESTAMP DEFAULT NOW()
                )
            """)
            
            cur.execute("""
                CREATE TABLE IF NOT EXISTS platform_payments (
                    id SERIAL PRIMARY KEY,
                    dev_telegram_id TEXT NOT NULL,
                    amount_sol DECIMAL(20,9) NOT NULL,
                    tx_signature TEXT,
                    created_at TIMESTAMP DEFAULT NOW()
                )
            """)
            
            cur.execute("""
                CREATE TABLE IF NOT EXISTS protected_groups (
                    id SERIAL PRIMARY KEY,
                    dev_telegram_id TEXT NOT NULL,
                    telegram_chat_id TEXT UNIQUE NOT NULL,
                    group_name TEXT,
                    spam_blocked INT DEFAULT 0,
                    is_active BOOLEAN DEFAULT TRUE
                )
            """)
            
            cur.execute("""
                CREATE TABLE IF NOT EXISTS user_engagement (
                    group_chat_id TEXT NOT NULL,
                    telegram_id TEXT NOT NULL,
                    message_count INT DEFAULT 0,
                    last_active TIMESTAMP DEFAULT NOW(),
                    UNIQUE(group_chat_id, telegram_id)
                )
            """)
            
            db_conn.commit()
        
        logger.info("✅ Database ready")
        return True
    except Exception as e:
        logger.error(f"Database error: {e}")
        return False

def get_db():
    """Get fresh connection if needed"""
    global db_conn
    try:
        # Test connection
        with db_conn.cursor() as cur:
            cur.execute("SELECT 1")
    except:
        # Reconnect if failed
        db_conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
    return db_conn

# --- HELIUS FUNCTIONS ---
async def verify_sol_payment(tx_signature: str, expected_amount: float) -> bool:
    """Verify payment via Helius"""
    try:
        async with aiohttp.ClientSession() as session:
            url = f"https://api.helius.xyz/v0/transactions/?api-key={HELIUS_API_KEY}"
            async with session.post(url, json={"transactions": [tx_signature]}) as resp:
                if resp.status != 200:
                    return False
                data = await resp.json()
                if not data:
                    return False
                
                tx = data[0]
                if tx.get('err'):
                    return False
                
                for transfer in tx.get('nativeTransfers', []):
                    amount_sol = float(transfer['amount']) / 1e9
                    if (transfer['toUserAccount'] == SOL_MAIN and 
                        amount_sol >= expected_amount * 0.95):
                        return True
        return False
    except Exception as e:
        logger.error(f"Verify error: {e}")
        return False

async def process_token_launch(data: dict):
    """Auto-detect token launches"""
    try:
        token_mint = data.get('tokenAddress') or data.get('mint')
        deployer = data.get('deployer')
        
        if not token_mint:
            return
        
        conn = get_db()
        with conn.cursor() as cur:
            cur.execute("""
                SELECT * FROM dev_subscriptions 
                WHERE sol_wallet = %s AND status = 'active'
            """, (deployer,))
            dev = cur.fetchone()
            
            if dev:
                logger.info(f"🚀 Token detected for dev {dev['telegram_id']}: {token_mint}")
                # Here you would notify the dev
    except Exception as e:
        logger.error(f"Token launch error: {e}")

# --- TELEGRAM HANDLERS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Main entry"""
    user = update.effective_user
    
    if update.effective_chat.type == "private":
        if str(user.id) == ADMIN_ID:
            await show_admin_dashboard(update)
            return
        
        conn = get_db()
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM dev_subscriptions WHERE telegram_id = %s", (str(user.id),))
            dev = cur.fetchone()
        
        if dev and dev['status'] == 'active':
            await show_dev_dashboard(update, dev)
        else:
            await show_subscription_menu(update)
    else:
        await update.message.reply_text(
            "🤖 **ICE REIGN ACTIVATED**\n"
            "🛡 Anti-spam: ON\n"
            "👨‍💻 Devs: PM me to subscribe",
            parse_mode=ParseMode.MARKDOWN
        )

async def show_admin_dashboard(update: Update):
    """Admin panel"""
    conn = get_db()
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM platform_payments ORDER BY created_at DESC LIMIT 5")
        payments = cur.fetchall()
    
    total = sum(p['amount_sol'] for p in payments) if payments else 0
    
    await update.message.reply_text(
        f"👑 **ADMIN DASHBOARD**\n\n"
        f"**Total Revenue:** {total:.4f} SOL\n"
        f"**Wallet:** `{SOL_MAIN}`\n\n"
        f"All payments go directly to your wallet above.",
        parse_mode=ParseMode.MARKDOWN
    )

async def show_subscription_menu(update: Update):
    """Show pricing"""
    keyboard = [
        [InlineKeyboardButton(f"💎 Basic - {SUBSCRIPTION_PRICE} SOL", callback_data="sub_basic")],
        [InlineKeyboardButton("👑 Pro - 3 SOL", callback_data="sub_pro")],
    ]
    
    await update.message.reply_text(
        f"🚀 **ICE REIGN MACHINE**\n\n"
        f"Auto-detect launches + Anti-spam protection\n\n"
        f"**Pricing:**\n"
        f"• Basic: {SUBSCRIPTION_PRICE} SOL/mo\n"
        f"• Pro: 3 SOL/mo\n\n"
        f"**Payment Address:**\n`{SOL_MAIN}`\n\n"
        f"Click below to subscribe:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.MARKDOWN
    )

async def subscription_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle sub selection"""
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
    """Verify and activate"""
    tx = update.message.text.strip()
    user = update.effective_user
    payment = context.user_data.get('payment')
    
    if not payment:
        await update.message.reply_text("Use /start first")
        return ConversationHandler.END
    
    await update.message.reply_text("⏳ Verifying payment...")
    
    if await verify_sol_payment(tx, payment['amount']):
        expiry = datetime.now() + timedelta(days=30)
        
        conn = get_db()
        with conn.cursor() as cur:
            # Insert or update
            cur.execute("""
                INSERT INTO dev_subscriptions (telegram_id, username, tier, status, subscription_end)
                VALUES (%s, %s, %s, 'active', %s)
                ON CONFLICT (telegram_id) DO UPDATE SET
                    tier = EXCLUDED.tier,
                    status = 'active',
                    subscription_end = EXCLUDED.subscription_end
            """, (str(user.id), user.username, payment['tier'], expiry))
            
            # Record payment
            cur.execute("""
                INSERT INTO platform_payments (dev_telegram_id, amount_sol, tx_signature)
                VALUES (%s, %s, %s)
            """, (str(user.id), payment['amount'], tx))
            
            conn.commit()
        
        await update.message.reply_text(
            f"✅ **ACTIVATED!**\n\n"
            f"Tier: {payment['tier'].upper()}\n"
            f"Expires: {expiry.strftime('%Y-%m-%d')}\n\n"
            f"Add me to your group and type /activate",
            parse_mode=ParseMode.MARKDOWN
        )
        
        # Notify admin
        await context.bot.send_message(
            ADMIN_ID,
            f"💰 **NEW PAYMENT**\n\n"
            f"From: @{user.username or user.id}\n"
            f"Amount: {payment['amount']} SOL\n"
            f"Tier: {payment['tier']}\n"
            f"TX: `{tx[:20]}...`",
            parse_mode=ParseMode.MARKDOWN
        )
    else:
        await update.message.reply_text(
            "❌ **Payment not found**\n\n"
            "Check:\n"
            "• Correct amount sent\n"
            "• Transaction confirmed\n"
            "• Full signature provided",
            parse_mode=ParseMode.MARKDOWN
        )
    
    return ConversationHandler.END

async def show_dev_dashboard(update: Update, dev: dict):
    """Dev panel"""
    expiry = dev['subscription_end'].strftime('%Y-%m-%d') if dev['subscription_end'] else 'N/A'
    
    await update.message.reply_text(
        f"👨‍💻 **DEV DASHBOARD**\n\n"
        f"Tier: {dev['tier'].upper()}\n"
        f"Status: {'✅ Active' if dev['status'] == 'active' else '❌ Expired'}\n"
        f"Expires: {expiry}\n\n"
        f"**Commands:**\n"
        f"/activate - Add bot to group\n"
        f"/stats - View engagement stats",
        parse_mode=ParseMode.MARKDOWN
    )

async def activate_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Activate in group"""
    chat = update.effective_chat
    user = update.effective_user
    
    if chat.type == "private":
        await update.message.reply_text("Use this in a group chat")
        return
    
    # Check admin
    member = await context.bot.get_chat_member(chat.id, user.id)
    if member.status not in [ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER]:
        await update.message.reply_text("Admin only")
        return
    
    # Check subscription
    conn = get_db()
    with conn.cursor() as cur:
        cur.execute("""
            SELECT * FROM dev_subscriptions 
            WHERE telegram_id = %s AND status = 'active'
        """, (str(user.id),))
        dev = cur.fetchone()
        
        if not dev:
            await update.message.reply_text("❌ Subscribe first. PM me.")
            return
        
        cur.execute("""
            INSERT INTO protected_groups (dev_telegram_id, telegram_chat_id, group_name)
            VALUES (%s, %s, %s)
            ON CONFLICT (telegram_chat_id) DO UPDATE SET is_active = TRUE
        """, (dev['telegram_id'], str(chat.id), chat.title))
        conn.commit()
    
    await update.message.reply_text(
        "✅ **GROUP PROTECTED**\n\n"
        "🛡 Anti-spam: ACTIVE\n"
        "📊 Tracking engagement\n"
        "🚀 Will auto-detect your token launches\n\n"
        "_Ice Reign is watching..._",
        parse_mode=ParseMode.MARKDOWN
    )

# --- SECURITY ENGINE ---
async def group_security(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Anti-spam + engagement tracking"""
    msg = update.message
    if not msg or not msg.text:
        return
    
    chat_id = str(update.effective_chat.id)
    user = update.effective_user
    
    # Check if protected
    conn = get_db()
    with conn.cursor() as cur:
        cur.execute("""
            SELECT * FROM protected_groups 
            WHERE telegram_chat_id = %s AND is_active = TRUE
        """, (chat_id,))
        group = cur.fetchone()
        
        if not group:
            return
        
        # Track engagement
        cur.execute("""
            INSERT INTO user_engagement (group_chat_id, telegram_id, message_count, last_active)
            VALUES (%s, %s, 1, NOW())
            ON CONFLICT (group_chat_id, telegram_id) 
            DO UPDATE SET message_count = user_engagement.message_count + 1, last_active = NOW()
        """, (chat_id, str(user.id)))
        conn.commit()
    
    # Skip admins for spam check
    try:
        member = await context.bot.get_chat_member(chat_id, user.id)
        if member.status in [ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER]:
            return
    except:
        return
    
    # Spam detection
    text_lower = msg.text.lower()
    spam_words = ['dm me', 'http', 't.me/', 'investment', 'forex', 'profit guaranteed', 'double your money']
    spam_score = sum(1 for word in spam_words if word in text_lower)
    
    if spam_score >= 2:
        try:
            await msg.delete()
            warning = await context.bot.send_message(
                chat_id,
                f"🛡 Spam removed from @{user.username or user.id}\n_Protected by Ice Reign_",
                parse_mode=ParseMode.MARKDOWN
            )
            
            # Update stats
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE protected_groups SET spam_blocked = spam_blocked + 1
                    WHERE telegram_chat_id = %s
                """, (chat_id,))
                conn.commit()
            
            await asyncio.sleep(5)
            await warning.delete()
        except:
            pass

# --- MAIN ---
async def main():
    # Init database
    init_db()
    
    # Start Flask in background thread
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    logger.info(f"🌐 Web server on port {PORT}")
    
    # Start bot
    app = Application.builder().token(BOT_TOKEN).build()
    
    # Conversation handler
    conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(subscription_callback, pattern="^sub_")],
        states={AWAITING_PAYMENT: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_payment)]},
        fallbacks=[]
    )
    
    # Add handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(conv_handler)
    app.add_handler(CommandHandler("activate", activate_group))
    app.add_handler(MessageHandler(filters.TEXT & filters.ChatType.GROUPS, group_security))
    
    logger.info("🚀 ICE REIGN MACHINE STARTED")
    logger.info(f"💰 Revenue wallet: {SOL_MAIN}")
    
    await app.run_polling()

if __name__ == "__main__":
    asyncio.run(main())
