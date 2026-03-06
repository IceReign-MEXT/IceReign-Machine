#!/usr/bin/env python3
"""
ICE REIGN MACHINE V5 - AUTONOMOUS AIRDROP EMPIRE
Revenue Model: Subscriptions + Distribution Fees + Priority Fees
All payments flow to platform wallet: SOL_MAIN
"""

import os
import json
import asyncio
import logging
import base58
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Optional, Dict, List

# Web Framework
from flask import Flask, request, jsonify
import threading

# Telegram
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode, ChatMemberStatus
from telegram.ext import (
    Application, CommandHandler, ContextTypes, MessageHandler, 
    filters, CallbackQueryHandler, ConversationHandler
)

# Database
import asyncpg
from asyncpg import Pool

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
SOL_MAIN = os.getenv("SOL_MAIN")  # Your revenue wallet
ETH_MAIN = os.getenv("ETH_MAIN")
SOLANA_RPC = os.getenv("SOLANA_RPC")
DATABASE_URL = os.getenv("DATABASE_URL")
PORT = int(os.getenv("PORT", 8080))
SUBSCRIPTION_PRICE = float(os.getenv("SUBSCRIPTION_PRICE", 100))

# Extract Helius API key from RPC URL
HELIUS_API_KEY = SOLANA_RPC.split("api-key=")[1] if "api-key=" in SOLANA_RPC else ""

# Global pool
pool: Optional[Pool] = None

# Conversation states
SELECTING_TIER, AWAITING_PAYMENT, CONFIGURING_AIRDROP = range(3)

# --- FLASK WEB SERVER (For Render Health Checks & Webhooks) ---
flask_app = Flask(__name__)

@flask_app.route("/")
def health():
    """Render health check endpoint"""
    return jsonify({
        "status": "ICE REIGN MACHINE ONLINE",
        "version": "5.0",
        "revenue_wallet": SOL_MAIN,
        "platform": "Render",
        "timestamp": datetime.utcnow().isoformat()
    }), 200

@flask_app.route("/helius/webhook", methods=['POST'])
async def helius_webhook():
    """Receive token launch notifications from Helius"""
    try:
        data = request.json
        
        # Process token launch detection
        await process_token_launch(data)
        return jsonify({"status": "processed"}), 200
        
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return jsonify({"error": str(e)}), 500

def run_web():
    """Run Flask in separate thread for Render"""
    flask_app.run(host="0.0.0.0", port=PORT, threaded=True)

# --- DATABASE INITIALIZATION ---
async def init_db():
    global pool
    try:
        pool = await asyncpg.create_pool(DATABASE_URL, min_size=2, max_size=10)
        
        async with pool.acquire() as conn:
            # Create all tables if not exist
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS dev_subscriptions (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    telegram_id TEXT UNIQUE NOT NULL,
                    username TEXT,
                    tier TEXT DEFAULT 'none',
                    status TEXT DEFAULT 'inactive',
                    sol_wallet TEXT,
                    subscription_start TIMESTAMP,
                    subscription_end TIMESTAMP,
                    created_at TIMESTAMP DEFAULT NOW()
                )
            """)
            
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS platform_payments (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    dev_telegram_id TEXT NOT NULL,
                    amount_sol DECIMAL(20,9) NOT NULL,
                    payment_type TEXT,
                    tx_signature TEXT,
                    status TEXT DEFAULT 'completed',
                    created_at TIMESTAMP DEFAULT NOW()
                )
            """)
            
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS token_campaigns (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    dev_telegram_id TEXT NOT NULL,
                    token_mint TEXT,
                    token_symbol TEXT,
                    token_name TEXT,
                    total_supply DECIMAL(20,9),
                    airdrop_allocation DECIMAL(20,9),
                    per_user_amount DECIMAL(20,9),
                    status TEXT DEFAULT 'detected',
                    launch_detected_at TIMESTAMP,
                    created_at TIMESTAMP DEFAULT NOW()
                )
            """)
            
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS protected_groups (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    dev_telegram_id TEXT NOT NULL,
                    telegram_chat_id TEXT UNIQUE NOT NULL,
                    group_name TEXT,
                    group_username TEXT,
                    member_count INT DEFAULT 0,
                    spam_blocked INT DEFAULT 0,
                    is_active BOOLEAN DEFAULT TRUE,
                    added_at TIMESTAMP DEFAULT NOW()
                )
            """)
            
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS user_engagement (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    group_chat_id TEXT NOT NULL,
                    telegram_id TEXT NOT NULL,
                    username TEXT,
                    message_count INT DEFAULT 0,
                    last_active TIMESTAMP DEFAULT NOW(),
                    UNIQUE(group_chat_id, telegram_id)
                )
            """)
            
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS platform_stats (
                    id SERIAL PRIMARY KEY,
                    total_devs INT DEFAULT 0,
                    active_groups INT DEFAULT 0,
                    spam_blocked_total INT DEFAULT 0,
                    revenue_sol DECIMAL(20,9) DEFAULT 0,
                    updated_at TIMESTAMP DEFAULT NOW()
                )
            """)
            
            # Insert initial stats row
            await conn.execute("""
                INSERT INTO platform_stats (id) VALUES (1) 
                ON CONFLICT DO NOTHING
            """)
            
        logger.info("✅ Database initialized")
        return True
    except Exception as e:
        logger.error(f"Database failed: {e}")
        return False

# --- HELIUS API FUNCTIONS ---
async def verify_sol_payment(tx_signature: str, expected_amount: float, recipient: str = SOL_MAIN) -> bool:
    """Verify Solana payment via Helius API"""
    try:
        async with aiohttp.ClientSession() as session:
            url = f"https://api.helius.xyz/v0/transactions/?api-key={HELIUS_API_KEY}"
            async with session.post(url, json={"transactions": [tx_signature]}) as resp:
                if resp.status != 200:
                    return False
                    
                data = await resp.json()
                if not data or len(data) == 0:
                    return False
                
                tx = data[0]
                
                # Check for errors
                if tx.get('err'):
                    return False
                
                # Verify native SOL transfers
                for transfer in tx.get('nativeTransfers', []):
                    amount_sol = float(transfer['amount']) / 1e9
                    if (transfer['toUserAccount'] == recipient and 
                        amount_sol >= expected_amount * 0.95):  # 5% tolerance
                        return True
                        
                # Verify SPL token transfers (USDC, etc)
                for token_tx in tx.get('tokenTransfers', []):
                    amount = float(token_tx.get('tokenAmount', 0))
                    if (token_tx.get('toUserAccount') == recipient and 
                        amount >= expected_amount * 0.95):
                        return True
                        
        return False
    except Exception as e:
        logger.error(f"Payment verification error: {e}")
        return False

async def get_token_info(token_mint: str) -> dict:
    """Get token metadata from Helius"""
    try:
        async with aiohttp.ClientSession() as session:
            url = f"https://mainnet.helius-rpc.com/?api-key={HELIUS_API_KEY}"
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getAsset",
                "params": [token_mint]
            }
            async with session.post(url, json=payload) as resp:
                data = await resp.json()
                return data.get('result', {})
    except Exception as e:
        logger.error(f"Token info error: {e}")
        return {}

async def process_token_launch(data: dict):
    """Process new token detection from Helius webhook"""
    try:
        # Extract token info from webhook data
        token_mint = data.get('tokenAddress') or data.get('mint')
        deployer = data.get('deployer') or data.get('feePayer')
        
        if not token_mint:
            return
        
        logger.info(f"🚀 Token detected: {token_mint} by {deployer}")
        
        # Check if deployer is subscribed dev
        async with pool.acquire() as conn:
            dev = await conn.fetchrow("""
                SELECT * FROM dev_subscriptions 
                WHERE sol_wallet = $1 AND status = 'active'
            """, deployer)
            
            if dev:
                # Auto-create campaign
                await conn.execute("""
                    INSERT INTO token_campaigns 
                    (dev_telegram_id, token_mint, status, launch_detected_at)
                    VALUES ($1, $2, 'detected', NOW())
                """, dev['telegram_id'], token_mint)
                
                # Notify dev via Telegram
                # This requires bot instance - handled separately
                logger.info(f"✅ Campaign auto-created for dev {dev['telegram_id']}")
            else:
                # Check if any protected group should be notified
                pass
                
    except Exception as e:
        logger.error(f"Token launch processing error: {e}")

# --- TELEGRAM HANDLERS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Main entry point"""
    user = update.effective_user
    chat_type = update.effective_chat.type
    
    if chat_type == "private":
        # Check if user is admin
        if str(user.id) == ADMIN_ID:
            await show_admin_dashboard(update)
            return
            
        # Check if user is subscribed dev
        async with pool.acquire() as conn:
            dev = await conn.fetchrow(
                "SELECT * FROM dev_subscriptions WHERE telegram_id = $1", 
                str(user.id)
            )
        
        if dev and dev['status'] == 'active':
            await show_dev_dashboard(update, dev)
        else:
            await show_subscription_menu(update)
    else:
        # Group chat
        await update.message.reply_text(
            "🤖 **ICE REIGN MACHINE ACTIVATED**\n\n"
            "🛡 Anti-spam protection: **ACTIVE**\n"
            "🎯 Auto-airdrop: **STANDBY**\n\n"
            "👨‍💻 Devs: PM @IceReignBot to subscribe\n"
            "👥 Users: Airdrops will be announced here",
            parse_mode=ParseMode.MARKDOWN
        )

async def show_admin_dashboard(update: Update):
    """Show platform owner dashboard"""
    async with pool.acquire() as conn:
        stats = await conn.fetchrow("SELECT * FROM platform_stats WHERE id = 1")
        recent_payments = await conn.fetch("""
            SELECT * FROM platform_payments 
            ORDER BY created_at DESC LIMIT 5
        """)
    
    payments_text = "\n".join([
        f"• {p['amount_sol']} SOL - {p['payment_type']}"
        for p in recent_payments
    ]) if recent_payments else "No payments yet"
    
    await update.message.reply_text(
        f"👑 **ADMIN DASHBOARD**\n\n"
        f"**Platform Stats:**\n"
        f"• Total Devs: {stats['total_devs']}\n"
        f"• Active Groups: {stats['active_groups']}\n"
        f"• Spam Blocked: {stats['spam_blocked_total']}\n"
        f"• Total Revenue: {stats['revenue_sol']:.4f} SOL\n\n"
        f"**Recent Payments:**\n{payments_text}\n\n"
        f"**Your Wallets:**\n"
        f"`{SOL_MAIN}`\n(SOL)\n\n"
        f"`{ETH_MAIN}`\n(ETH/BSC)",
        parse_mode=ParseMode.MARKDOWN
    )

async def show_subscription_menu(update: Update):
    """Show pricing tiers to potential customers"""
    keyboard = [
        [InlineKeyboardButton(f"💎 Basic - ${SUBSCRIPTION_PRICE} SOL/mo", callback_data="sub_basic")],
        [InlineKeyboardButton("👑 Pro - 3 SOL/mo", callback_data="sub_pro")],
        [InlineKeyboardButton("🏢 Enterprise - 10 SOL/mo", callback_data="sub_enterprise")],
        [InlineKeyboardButton("📖 How It Works", callback_data="how_it_works")]
    ]
    
    await update.message.reply_photo(
        photo="https://images.unsplash.com/photo-1639762681485-074b7f938ba0?w=800",
        caption=(
            "🚀 **ICE REIGN MACHINE**\n"
            "*The Autonomous Airdrop Empire*\n\n"
            "**What You Get:**\n"
            "✅ Auto-detect token launches\n"
            "✅ Anti-spam protection\n"
            "✅ Engagement tracking\n"
            "✅ Automatic distribution\n\n"
            "**Pricing:**\n"
            f"• Basic: {SUBSCRIPTION_PRICE} SOL/mo\n"
            f"• Pro: 3 SOL/mo (Priority support)\n"
            f"• Enterprise: 10 SOL/mo (White-label)\n\n"
            "**+ 1% platform fee on distributions**\n\n"
            f"**Payment Address:**\n`{SOL_MAIN}`\n\n"
            "Click below to subscribe:"
        ),
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.MARKDOWN
    )

async def subscription_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle subscription selection"""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    
    if data == "how_it_works":
        await query.edit_message_text(
            "📖 **How Ice Reign Works**\n\n"
            "1. **Subscribe** - Pay monthly fee to SOL_MAIN\n"
            "2. **Add to Group** - Bot protects & tracks engagement\n"
            "3. **Launch Token** - We auto-detect via Helius\n"
            "4. **Configure** - Set allocation per user\n"
            "5. **Distribute** - Bot sends tokens automatically\n"
            "6. **Profit** - Users get airdrops, you grow community\n\n"
            "**Revenue Flow:**\n"
            "• Subscriptions → Your wallet (SOL_MAIN)\n"
            "• 1% of every airdrop → Your wallet\n"
            "• Priority fees → Your wallet\n\n"
            "Click /start to subscribe",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    tier_prices = {
        'sub_basic': SUBSCRIPTION_PRICE,
        'sub_pro': 3.0,
        'sub_enterprise': 10.0
    }
    
    amount = tier_prices.get(data, SUBSCRIPTION_PRICE)
    tier_name = data.replace('sub_', '').upper()
    
    context.user_data['pending_payment'] = {
        'tier': tier_name,
        'amount': amount
    }
    
    await query.edit_message_text(
        f"💳 **Subscribe to {tier_name}**\n\n"
        f"Amount: **{amount} SOL**\n\n"
        f"**Payment Steps:**\n"
        f"1. Send exactly {amount} SOL to:\n"
        f"`{SOL_MAIN}`\n\n"
        f"2. Reply with transaction signature\n"
        f"(Example: `5x...`)\n\n"
        f"3. Bot will verify and activate instantly\n\n"
        f"⚠️ *Payment is monthly. Cancel anytime.*",
        parse_mode=ParseMode.MARKDOWN
    )
    
    return AWAITING_PAYMENT

async def process_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Verify payment and activate subscription"""
    tx_signature = update.message.text.strip()
    user = update.effective_user
    payment_info = context.user_data.get('pending_payment')
    
    if not payment_info:
        await update.message.reply_text("❌ No pending payment. Use /start")
        return ConversationHandler.END
    
    # Verify transaction
    await update.message.reply_text("⏳ Verifying payment...")
    
    is_valid = await verify_sol_payment(
        tx_signature, 
        payment_info['amount'], 
        SOL_MAIN
    )
    
    if is_valid:
        # Calculate subscription end date (30 days)
        sub_end = datetime.now() + timedelta(days=30)
        
        async with pool.acquire() as conn:
            # Insert or update dev subscription
            await conn.execute("""
                INSERT INTO dev_subscriptions 
                (telegram_id, username, tier, status, subscription_start, subscription_end)
                VALUES ($1, $2, $3, 'active', NOW(), $4)
                ON CONFLICT (telegram_id) DO UPDATE SET
                    tier = $3,
                    status = 'active',
                    subscription_start = NOW(),
                    subscription_end = $4
            """, str(user.id), user.username, payment_info['tier'], sub_end)
            
            # Record payment
            await conn.execute("""
                INSERT INTO platform_payments 
                (dev_telegram_id, amount_sol, payment_type, tx_signature)
                VALUES ($1, $2, 'subscription', $3)
            """, str(user.id), payment_info['amount'], tx_signature)
            
            # Update platform stats
            await conn.execute("""
                UPDATE platform_stats 
                SET total_devs = total_devs + 1,
                    revenue_sol = revenue_sol + $1
                WHERE id = 1
            """, payment_info['amount'])
        
        await update.message.reply_text(
            f"✅ **Payment Verified!**\n\n"
            f"**Tier:** {payment_info['tier']}\n"
            f"**Expires:** {sub_end.strftime('%Y-%m-%d')}\n\n"
            f"**Next Steps:**\n"
            f"1. Add me to your Telegram group\n"
            f"2. Make me admin (delete messages permission)\n"
            f"3. Type `/activate` in the group\n\n"
            f"When you launch a token, I'll detect it automatically!",
            parse_mode=ParseMode.MARKDOWN
        )
        
        # Notify admin (you)
        await context.bot.send_message(
            ADMIN_ID,
            f"💰 **NEW PAYMENT**\n\n"
            f"User: @{user.username} ({user.id})\n"
            f"Tier: {payment_info['tier']}\n"
            f"Amount: {payment_info['amount']} SOL\n"
            f"TX: `{tx_signature}`",
            parse_mode=ParseMode.MARKDOWN
        )
    else:
        await update.message.reply_text(
            "❌ **Payment Not Found**\n\n"
            "Please verify:\n"
            "• Correct amount sent\n"
            "• Transaction confirmed on Solana\n"
            "• Signature is complete (88 characters)\n\n"
            "Try again or contact support.",
            parse_mode=ParseMode.MARKDOWN
        )
    
    context.user_data.clear()
    return ConversationHandler.END

async def show_dev_dashboard(update: Update, dev: dict):
    """Show active developer their dashboard"""
    async with pool.acquire() as conn:
        campaigns = await conn.fetch("""
            SELECT * FROM token_campaigns 
            WHERE dev_telegram_id = $1
            ORDER BY created_at DESC
        """, dev['telegram_id'])
        
        groups = await conn.fetch("""
            SELECT * FROM protected_groups 
            WHERE dev_telegram_id = $1 AND is_active = TRUE
        """, dev['telegram_id'])
    
    campaigns_text = "\n".join([
        f"• {c['token_symbol'] or 'Unknown'} - {c['status'].upper()}"
        for c in campaigns[:3]
    ]) if campaigns else "No campaigns yet"
    
    groups_text = "\n".join([
        f"• {g['group_name']} ({g['member_count']} members)"
        for g in groups
    ]) if groups else "No groups activated"
    
    await update.message.reply_text(
        f"👨‍💻 **DEV DASHBOARD**\n\n"
        f"**Plan:** {dev['tier'].upper()}\n"
        f"**Status:** {'✅ ACTIVE' if dev['status'] == 'active' else '❌ EXPIRED'}\n"
        f"**Expires:** {dev['subscription_end'].strftime('%Y-%m-%d') if dev['subscription_end'] else 'N/A'}\n\n"
        f"**Recent Campaigns:**\n{campaigns_text}\n\n"
        f"**Protected Groups:**\n{groups_text}\n\n"
        f"**Commands:**\n"
        f"/activate - Add to new group\n"
        f"/campaigns - View all campaigns\n"
        f"/stats - View engagement stats",
        parse_mode=ParseMode.MARKDOWN
    )

async def activate_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Activate bot in a group (dev only)"""
    chat = update.effective_chat
    user = update.effective_user
    
    # Verify this is a group
    if chat.type == "private":
        await update.message.reply_text("❌ Use this command in a group")
        return
    
    # Verify user is admin in this group
    try:
        member = await context.bot.get_chat_member(chat.id, user.id)
        if member.status not in [ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER]:
            await update.message.reply_text("❌ Only group admins can activate")
            return
    except Exception as e:
        logger.error(f"Admin check failed: {e}")
        return
    
    # Check if dev has active subscription
    async with pool.acquire() as conn:
        dev = await conn.fetchrow("""
            SELECT * FROM dev_subscriptions 
            WHERE telegram_id = $1 AND status = 'active'
        """, str(user.id))
        
        if not dev:
            await update.message.reply_text(
                "❌ **Subscription Required**\n\n"
                "You need an active subscription to use this bot.\n"
                "PM @IceReignBot to subscribe."
            )
            return
        
        # Add/update group
        await conn.execute("""
            INSERT INTO protected_groups 
            (dev_telegram_id, telegram_chat_id, group_name, group_username, added_at)
            VALUES ($1, $2, $3, $4, NOW())
            ON CONFLICT (telegram_chat_id) DO UPDATE SET
                is_active = TRUE,
                dev_telegram_id = $1
        """, dev['telegram_id'], str(chat.id), chat.title, chat.username or '')
        
        # Update stats
        await conn.execute("""
            UPDATE platform_stats 
            SET active_groups = active_groups + 1
            WHERE id = 1
        """)
    
    await update.message.reply_text(
        "✅ **GROUP ACTIVATED**\n\n"
        "🛡 **Security:** Active (Anti-spam enabled)\n"
        "📊 **Tracking:** User engagement monitored\n"
        "🎯 **Airdrop:** Auto-detect when you launch token\n\n"
        "The bot will now:\n"
        "• Delete spam automatically\n"
        "• Track active users\n"
        "• Detect your token launches\n"
        "• Distribute airdrops automatically\n\n"
        "_Ice Reign Machine is now protecting this group_",
        parse_mode=ParseMode.MARKDOWN
    )

# --- SECURITY & ENGAGEMENT ENGINE ---
async def group_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle all group messages - security + engagement tracking"""
    msg = update.message
    if not msg or not msg.text:
        return
    
    chat_id = str(update.effective_chat.id)
    user = update.effective_user
    
    # Skip if not in protected group
    async with pool.acquire() as conn:
        group = await conn.fetchrow("""
            SELECT * FROM protected_groups 
            WHERE telegram_chat_id = $1 AND is_active = TRUE
        """, chat_id)
        
        if not group:
            return
    
    # Skip admins for spam check (but track engagement)
    is_admin = False
    try:
        member = await context.bot.get_chat_member(chat_id, user.id)
        if member.status in [ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER]:
            is_admin = True
    except:
        pass
    
    # Track engagement for all users
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO user_engagement 
            (group_chat_id, telegram_id, username, message_count, last_active)
            VALUES ($1, $2, $3, 1, NOW())
            ON CONFLICT (group_chat_id, telegram_id) DO UPDATE SET
                message_count = user_engagement.message_count + 1,
                username = $3,
                last_active = NOW()
        """, chat_id, str(user.id), user.username or '')
    
    # Spam detection for non-admins
    if not is_admin:
        spam_score = 0
        text_lower = msg.text.lower()
        
        # Spam indicators
        spam_patterns = [
            ('dm me', 3), ('message me', 3), ('pm me', 3),
            ('http', 2), ('t.me/', 2), ('t.me/joinchat', 3),
            ('investment', 4), ('forex', 4), ('binary options', 4),
            ('guaranteed profit', 5), ('100% return', 5),
            ('send me', 2), ('double your', 4)
        ]
        
        for pattern, score in spam_patterns:
            if pattern in text_lower:
                spam_score += score
        
        # Check for excessive caps
        if len(msg.text) > 10:
            caps_ratio = sum(1 for c in msg.text if c.isupper()) / len(msg.text)
            if caps_ratio > 0.8:
                spam_score += 2
        
        # Action if spam detected
        if spam_score >= 4:
            try:
                await msg.delete()
                
                warning = await context.bot.send_message(
                    chat_id,
                    f"🛡 **SPAM NEUTRALIZED**\n\n"
                    f"User: @{user.username or user.id}\n"
                    f"Risk Score: {spam_score}/10\n"
                    f"Action: Message deleted\n\n"
                    f"_Protected by Ice Reign Machine_",
                    parse_mode=ParseMode.MARKDOWN
                )
                
                # Update stats
                await conn.execute("""
                    UPDATE protected_groups 
                    SET spam_blocked = spam_blocked + 1
                    WHERE telegram_chat_id = $1
                """, chat_id)
                
                await conn.execute("""
                    UPDATE platform_stats 
                    SET spam_blocked_total = spam_blocked_total + 1
                    WHERE id = 1
                """)
                
                # Delete warning after 10 seconds
                await asyncio.sleep(10)
                await warning.delete()
                
            except Exception as e:
                logger.error(f"Failed to delete spam: {e}")

# --- MAIN ENTRY POINT ---
async def main():
    # Initialize database
    await init_db()
    
    # Start web server for Render in background thread
    web_thread = threading.Thread(target=run_web, daemon=True)
    web_thread.start()
    logger.info(f"🌐 Web server started on port {PORT}")
    
    # Build Telegram bot
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Conversation handler for subscription flow
    subscription_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(subscription_callback, pattern="^sub_")],
        states={
            AWAITING_PAYMENT: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_payment)]
        },
        fallbacks=[CommandHandler("cancel", lambda u, c: u.message.reply_text("Cancelled"))]
    )
    
    # Command handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(subscription_conv)
    application.add_handler(CommandHandler("activate", activate_group))
    
    # Group message handler (security + engagement)
    application.add_handler(MessageHandler(
        filters.TEXT & filters.ChatType.GROUPS, 
        group_message_handler
    ))
    
    logger.info("🚀 ICE REIGN MACHINE V5 STARTED")
    logger.info(f"💰 Revenue wallet: {SOL_MAIN}")
    
    # Start polling
    await application.run_polling()

if __name__ == "__main__":
    asyncio.run(main())
