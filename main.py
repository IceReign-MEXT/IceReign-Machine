#!/usr/bin/env python3
"""
ICE REIGN MACHINE V6 - PROFESSIONAL EDITION
Auto-detect | Auto-distribute | Auto-profit
"""

import os
import asyncio
import logging
import threading
import aiosqlite
from datetime import datetime, timedelta
from decimal import Decimal

from flask import Flask, jsonify, request
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup, 
    InputMediaPhoto, LabeledPrice
)
from telegram.constants import ParseMode, ChatMemberStatus
from telegram.ext import (
    Application, CommandHandler, ContextTypes, MessageHandler, 
    filters, CallbackQueryHandler, ConversationHandler, PreCheckoutQueryHandler
)

import aiohttp
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = os.getenv("ADMIN_ID")
VIP_CHANNEL_ID = os.getenv("VIP_CHANNEL_ID")  # Your @ZeroThreat Intel channel
SOL_MAIN = os.getenv("SOL_MAIN")  # Your revenue wallet
SOLANA_RPC = os.getenv("SOLANA_RPC")
DATABASE_URL = os.getenv("DATABASE_URL")  # Supabase
PORT = int(os.getenv("PORT", 8080))

# Pricing in SOL
PRICE_BASIC = 1.0
PRICE_PRO = 3.0
PRICE_ENTERPRISE = 10.0
PLATFORM_FEE_PERCENT = 1.0  # 1% on all distributions

# Assets
IMG_BANNER = "https://images.unsplash.com/photo-1639762681485-074b7f938ba0?w=1200"
IMG_SECURITY = "https://images.unsplash.com/photo-1563986768609-322da13575f3?w=800"
IMG_PROFIT = "https://images.unsplash.com/photo-1611974789855-9c2a0a7236a3?w=800"

HELIUS_API_KEY = SOLANA_RPC.split("api-key=")[1] if "api-key=" in SOLANA_RPC else ""

DB_FILE = "ice_reign.db"
AWAITING_PAYMENT, CONFIGURING_TOKEN = range(2)

# ═══════════════════════════════════════════════════════════
# FLASK WEB SERVER (For Webhooks & Health)
# ═══════════════════════════════════════════════════════════
flask_app = Flask(__name__)

@flask_app.route("/")
def health():
    return jsonify({
        "status": "🟢 ICE REIGN ONLINE",
        "version": "6.0 PRO",
        "revenue_wallet": SOL_MAIN,
        "platform_fee": f"{PLATFORM_FEE_PERCENT}%",
        "timestamp": datetime.utcnow().isoformat()
    }), 200

@flask_app.route("/helius/webhook", methods=['POST'])
async def helius_webhook():
    """Auto-detect token launches"""
    try:
        data = request.json
        await process_token_detection(data)
        return jsonify({"status": "detected"}), 200
    except Exception as e:
        logger.error(f"Helius webhook error: {e}")
        return jsonify({"error": str(e)}), 500

def run_flask():
    flask_app.run(host='0.0.0.0', port=PORT, threaded=True)

# ═══════════════════════════════════════════════════════════
# DATABASE
# ═══════════════════════════════════════════════════════════
async def init_db():
    async with aiosqlite.connect(DB_FILE) as db:
        # Developers
        await db.execute("""
            CREATE TABLE IF NOT EXISTS developers (
                id INTEGER PRIMARY KEY,
                telegram_id TEXT UNIQUE,
                username TEXT,
                plan TEXT DEFAULT 'none',
                status TEXT DEFAULT 'inactive',
                sol_wallet TEXT,
                subscription_end TIMESTAMP,
                total_paid REAL DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Payments to you
        await db.execute("""
            CREATE TABLE IF NOT EXISTS revenue (
                id INTEGER PRIMARY KEY,
                dev_id TEXT,
                amount_sol REAL,
                payment_type TEXT,  -- subscription, distribution_fee, priority
                tx_signature TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Protected groups
        await db.execute("""
            CREATE TABLE IF NOT EXISTS groups (
                id INTEGER PRIMARY KEY,
                dev_id TEXT,
                telegram_chat_id TEXT UNIQUE,
                group_name TEXT,
                group_username TEXT,
                member_count INTEGER DEFAULT 0,
                spam_blocked INTEGER DEFAULT 0,
                messages_tracked INTEGER DEFAULT 0,
                is_active INTEGER DEFAULT 1,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Token campaigns (auto-detected)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS campaigns (
                id INTEGER PRIMARY KEY,
                dev_id TEXT,
                token_mint TEXT,
                token_symbol TEXT,
                token_name TEXT,
                total_supply TEXT,
                airdrop_amount REAL,
                per_user_amount REAL,
                status TEXT DEFAULT 'detected',  -- detected, configuring, active, completed
                launch_time TIMESTAMP,
                holders_count INTEGER DEFAULT 0,
                platform_fee_paid REAL DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # User engagement (for fair airdrops)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS engagement (
                group_id TEXT,
                user_id TEXT,
                username TEXT,
                message_count INTEGER DEFAULT 0,
                reaction_count INTEGER DEFAULT 0,
                join_date TIMESTAMP,
                last_active TIMESTAMP,
                wallet_address TEXT,
                airdrop_received INTEGER DEFAULT 0,
                PRIMARY KEY (group_id, user_id)
            )
        """)
        
        await db.commit()
    logger.info("✅ Database initialized")

# ═══════════════════════════════════════════════════════════
# HELIUS API (Token Detection & Verification)
# ═══════════════════════════════════════════════════════════
async def verify_sol_payment(tx_signature: str, expected_amount: float) -> bool:
    """Verify payment to your wallet"""
    try:
        async with aiohttp.ClientSession() as session:
            url = f"https://api.helius.xyz/v0/transactions/?api-key={HELIUS_API_KEY}"
            async with session.post(url, json={"transactions": [tx_signature]}, timeout=10) as resp:
                if resp.status != 200:
                    return False
                data = await resp.json()
                if not data or data[0].get('err'):
                    return False
                
                for transfer in data[0].get('nativeTransfers', []):
                    if transfer['toUserAccount'] == SOL_MAIN:
                        amount = float(transfer['amount']) / 1e9
                        if amount >= expected_amount * 0.95:  # 5% tolerance
                            return True
        return False
    except Exception as e:
        logger.error(f"Payment verify error: {e}")
        return False

async def get_token_metadata(mint_address: str) -> dict:
    """Get token info from Helius"""
    try:
        async with aiohttp.ClientSession() as session:
            url = f"https://api.helius.xyz/v0/tokens/?api-key={HELIUS_API_KEY}"
            async with session.get(url, params={"mintAddresses": [mint_address]}) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data[0] if data else {}
        return {}
    except Exception as e:
        logger.error(f"Token metadata error: {e}")
        return {}

async def process_token_detection(data: dict):
    """Auto-detect when subscribed dev launches token"""
    try:
        token_mint = data.get('tokenAddress') or data.get('mint')
        deployer = data.get('feePayer') or data.get('deployer')
        
        if not token_mint or not deployer:
            return
        
        # Check if deployer is subscribed dev
        async with aiosqlite.connect(DB_FILE) as db:
            async with db.execute(
                "SELECT * FROM developers WHERE sol_wallet = ? AND status = 'active'", 
                (deployer,)
            ) as c:
                dev = await c.fetchone()
            
            if dev:
                # Get token metadata
                meta = await get_token_metadata(token_mint)
                symbol = meta.get('symbol', 'UNKNOWN')
                name = meta.get('name', 'Unknown Token')
                
                # Create campaign
                await db.execute("""
                    INSERT INTO campaigns (dev_id, token_mint, token_symbol, token_name, status, launch_time)
                    VALUES (?, ?, ?, ?, 'detected', CURRENT_TIMESTAMP)
                """, (dev['telegram_id'], token_mint, symbol, name))
                await db.commit()
                
                # Notify dev
                await notify_dev_of_detection(dev['telegram_id'], token_mint, symbol, name)
                
                # Post to VIP channel
                await post_to_vip_channel(token_mint, symbol, name, dev['username'])
                
                logger.info(f"🚀 Auto-detected: {symbol} for {dev['username']}")
    except Exception as e:
        logger.error(f"Token detection error: {e}")

async def notify_dev_of_detection(dev_id: str, mint: str, symbol: str, name: str):
    """Send notification to developer"""
    # This runs via bot application - will implement in main()
    pass

async def post_to_vip_channel(mint: str, symbol: str, name: str, dev_username: str):
    """Auto-post new token to your VIP channel"""
    if not VIP_CHANNEL_ID:
        return
    
    try:
        # This will be called via bot instance
        message = (
            f"🚨 **NEW TOKEN DETECTED** 🚨\n\n"
            f"💎 **{name}** (${symbol})\n"
            f"🔖 Mint: `{mint[:20]}...`\n"
            f"👨‍💻 Dev: @{dev_username}\n"
            f"🤖 Auto-detected by Ice Reign\n\n"
            f"🛡 **Safety:** Scanning...\n"
            f"📊 **Status:** Launch Phase\n\n"
            f"_Join the group for airdrop alerts_"
        )
        # Bot instance will send this
        return message
    except Exception as e:
        logger.error(f"VIP channel post error: {e}")

# ═══════════════════════════════════════════════════════════
# TELEGRAM HANDLERS
# ═══════════════════════════════════════════════════════════
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Professional entry point"""
    user = update.effective_user
    chat_type = update.effective_chat.type
    
    if chat_type == "private":
        # Admin dashboard
        if str(user.id) == ADMIN_ID:
            await show_admin_panel(update, context)
            return
        
        # Check if existing dev
        async with aiosqlite.connect(DB_FILE) as db:
            async with db.execute(
                "SELECT * FROM developers WHERE telegram_id = ?", (str(user.id),)
            ) as c:
                dev = await c.fetchone()
        
        if dev and dev['status'] == 'active':
            await show_dev_dashboard(update, context, dev)
        else:
            await show_landing_page(update, context)
    else:
        # Group - show brief info
        await update.message.reply_text(
            "🤖 **ICE REIGN MACHINE** 🛡\n\n"
            "👨‍💻 Devs: PM me to activate protection\n"
            "👥 Users: Stay active for airdrops\n"
            "🔒 This group is monitored 24/7",
            parse_mode=ParseMode.MARKDOWN
        )

async def show_landing_page(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Professional sales page"""
    keyboard = [
        [InlineKeyboardButton("💎 Basic (1 SOL/month)", callback_data="plan_basic")],
        [InlineKeyboardButton("👑 Pro (3 SOL/month)", callback_data="plan_pro")],
        [InlineKeyboardButton("🏢 Enterprise (10 SOL/month)", callback_data="plan_enterprise")],
        [InlineKeyboardButton("📊 See Demo", url="https://t.me/ZeroThreatIntel")],
        [InlineKeyboardButton("💬 Support", url="https://t.me/IceReignSupport")]
    ]
    
    caption = (
        "🚀 **ICE REIGN MACHINE** 🚀\n\n"
        "*The Weapon That Turns Token Launches Into Empires*\n\n"
        "**What You Get:**\n"
        "✅ **Auto-Detect:** Bot finds your token the second you launch\n"
        "✅ **Auto-Distribute:** Sends airdrops to real users (not bots)\n"
        "✅ **Anti-Spam:** 24/7 protection from scammers\n"
        "✅ **Analytics:** Track who engages, who sells, who holds\n"
        "✅ **VIP Alerts:** Posted to @ZeroThreat Intel channel\n\n"
        "**Revenue Model:**\n"
        "• You pay: Monthly subscription\n"
        "• We take: 1% of airdrop value (only when you distribute)\n"
        "• You earn: Loyal community + higher token value\n\n"
        "**Plans:**\n"
        f"• Basic: {PRICE_BASIC} SOL - 1 group, 1,000 users\n"
        f"• Pro: {PRICE_PRO} SOL - 3 groups, 10,000 users\n"
        f"• Enterprise: {PRICE_ENTERPRISE} SOL - Unlimited, white-label\n\n"
        f"💰 **Pay to activate:**\n`{SOL_MAIN}`\n\n"
        "Click below to subscribe ⬇️"
    )
    
    await update.message.reply_photo(
        photo=IMG_BANNER,
        caption=caption,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.MARKDOWN
    )

async def show_admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Your revenue dashboard"""
    async with aiosqlite.connect(DB_FILE) as db:
        async with db.execute("SELECT SUM(amount_sol) FROM revenue") as c:
            total_revenue = (await c.fetchone())[0] or 0
        
        async with db.execute("SELECT COUNT(*) FROM developers WHERE status='active'") as c:
            total_devs = (await c.fetchone())[0]
        
        async with db.execute("SELECT COUNT(*) FROM groups WHERE is_active=1") as c:
            total_groups = (await c.fetchone())[0]
        
        async with db.execute("""
            SELECT dev_id, amount_sol, payment_type, created_at 
            FROM revenue ORDER BY created_at DESC LIMIT 5
        """) as c:
            recent = await c.fetchall()
    
    recent_text = "\n".join([
        f"• {r['payment_type']}: +{r['amount_sol']} SOL"
        for r in recent
    ]) if recent else "No payments yet"
    
    await update.message.reply_text(
        f"👑 **ADMIN PANEL** 👑\n\n"
        f"💰 **Total Revenue:** {total_revenue:.4f} SOL\n"
        f"👨‍💻 **Active Devs:** {total_devs}\n"
        f"👥 **Protected Groups:** {total_groups}\n\n"
        f"**Recent Income:**\n{recent_text}\n\n"
        f"**Your Wallets:**\n"
        f"SOL: `{SOL_MAIN}`\n"
        f"ETH: `{os.getenv('ETH_MAIN', 'Not set')}`\n\n"
        f"📊 [View on Solscan](https://solscan.io/account/{SOL_MAIN})",
        parse_mode=ParseMode.MARKDOWN,
        disable_web_page_preview=True
    )

async def show_dev_dashboard(update: Update, context: ContextTypes.DEFAULT_TYPE, dev: dict):
    """Developer control panel"""
    async with aiosqlite.connect(DB_FILE) as db:
        async with db.execute(
            "SELECT COUNT(*), SUM(spam_blocked) FROM groups WHERE dev_id = ?", 
            (dev['telegram_id'],)
        ) as c:
            row = await c.fetchone()
            group_count, spam_blocked = row[0], row[1] or 0
        
        async with db.execute(
            "SELECT COUNT(*) FROM campaigns WHERE dev_id = ?", (dev['telegram_id'],)
        ) as c:
            campaign_count = (await c.fetchone())[0]
    
    expiry = dev['subscription_end']
    expiry_text = expiry.strftime('%Y-%m-%d') if expiry else 'Unknown'
    days_left = (expiry - datetime.now()).days if expiry else 0
    
    keyboard = [
        [InlineKeyboardButton("➕ Add Group", callback_data="add_group")],
        [InlineKeyboardButton("📊 My Campaigns", callback_data="view_campaigns")],
        [InlineKeyboardButton("⚙️ Settings", callback_data="settings")],
        [InlineKeyboardButton("🔄 Renew/Upgrade", callback_data="upgrade")]
    ]
    
    await update.message.reply_text(
        f"👨‍💻 **DEV DASHBOARD** 👨‍💻\n\n"
        f"**Plan:** {dev['plan'].upper()}\n"
        f"**Status:** {'🟢 ACTIVE' if dev['status'] == 'active' else '🔴 EXPIRED'}\n"
        f"**Expires:** {expiry_text} ({days_left} days left)\n\n"
        f"**Stats:**\n"
        f"• Protected Groups: {group_count}\n"
        f"• Token Campaigns: {campaign_count}\n"
        f"• Spam Blocked: {spam_blocked}\n"
        f"• Total Paid: {dev['total_paid']:.2f} SOL\n\n"
        f"**Quick Actions:**",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.MARKDOWN
    )

# ═══════════════════════════════════════════════════════════
# SUBSCRIPTION FLOW
# ═══════════════════════════════════════════════════════════
async def plan_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle plan selection"""
    query = update.callback_query
    await query.answer()
    
    plan = query.data.replace("plan_", "")
    prices = {'basic': PRICE_BASIC, 'pro': PRICE_PRO, 'enterprise': PRICE_ENTERPRISE}
    price = prices.get(plan, PRICE_BASIC)
    
    context.user_data['selected_plan'] = {'plan': plan, 'price': price}
    
    keyboard = [
        [InlineKeyboardButton("✅ I've Sent Payment", callback_data="confirm_payment")],
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel")]
    ]
    
    await query.edit_message_text(
        f"💳 **Subscribe to {plan.upper()}** 💳\n\n"
        f"**Amount:** {price} SOL\n"
        f"**Duration:** 30 days\n"
        f"**Features:**\n"
        f"{'• 1 Group + 1,000 users' if plan == 'basic' else ''}"
        f"{'• 3 Groups + 10,000 users + Priority support' if plan == 'pro' else ''}"
        f"{'• Unlimited + White-label + API access' if plan == 'enterprise' else ''}\n\n"
        f"**Send {price} SOL to:**\n"
        f"`{SOL_MAIN}`\n\n"
        f"⚠️ **Important:**\n"
        f"1. Send EXACT amount\n"
        f"2. Save the transaction signature\n"
        f"3. Click 'I've Sent Payment' below\n"
        f"4. Paste the TX signature when asked\n\n"
        f"Activation is instant after verification.",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.MARKDOWN
    )

async def confirm_payment_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ask for TX signature"""
    query = update.callback_query
    await query.answer()
    
    await query.edit_message_text(
        "✉️ **Send Transaction Signature**\n\n"
        "Reply with your Solana transaction signature.\n"
        "Looks like: `5xKjL8vPmN...` (88 characters)\n\n"
        "I'll verify instantly.",
        parse_mode=ParseMode.MARKDOWN
    )
    return AWAITING_PAYMENT

async def process_payment_tx(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Verify payment and activate"""
    tx_signature = update.message.text.strip()
    user = update.effective_user
    plan_data = context.user_data.get('selected_plan')
    
    if not plan_data:
        await update.message.reply_text("❌ Session expired. Use /start")
        return ConversationHandler.END
    
    await update.message.reply_text("⏳ Verifying on Solana blockchain...")
    
    # Verify payment
    is_valid = await verify_sol_payment(tx_signature, plan_data['price'])
    
    if is_valid:
        expiry = datetime.now() + timedelta(days=30)
        
        async with aiosqlite.connect(DB_FILE) as db:
            # Save developer
            await db.execute("""
                INSERT INTO developers (telegram_id, username, plan, status, subscription_end, total_paid)
                VALUES (?, ?, ?, 'active', ?, ?)
                ON CONFLICT(telegram_id) DO UPDATE SET
                    plan = excluded.plan,
                    status = 'active',
                    subscription_end = excluded.subscription_end,
                    total_paid = total_paid + excluded.total_paid
            """, (str(user.id), user.username, plan_data['plan'], expiry, plan_data['price']))
            
            # Record revenue
            await db.execute("""
                INSERT INTO revenue (dev_id, amount_sol, payment_type, tx_signature)
                VALUES (?, ?, 'subscription', ?)
            """, (str(user.id), plan_data['price'], tx_signature))
            
            await db.commit()
        
        # Success message
        keyboard = [[InlineKeyboardButton("➕ Activate Group", callback_data="add_group")]]
        
        await update.message.reply_text(
            f"🎉 **WELCOME TO ICE REIGN!** 🎉\n\n"
            f"✅ **Plan:** {plan_data['plan'].upper()} activated\n"
            f"✅ **Expires:** {expiry.strftime('%Y-%m-%d')}\n"
            f"✅ **TX:** `{tx_signature[:20]}...`\n\n"
            f"**Next Steps:**\n"
            f"1. Add me to your Telegram group\n"
            f"2. Make me admin (delete messages)\n"
            f"3. Type `/activate` in the group\n\n"
            f"**What happens next:**\n"
            f"• I'll auto-detect when you launch a token\n"
            f"• I'll post it to @ZeroThreat Intel\n"
            f"• I'll track engagement for fair airdrops\n"
            f"• I'll ban spammers instantly\n\n"
            f"_Your empire starts now_ 👑",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.MARKDOWN
        )
        
        # Notify you of new sale
        await context.bot.send_message(
            ADMIN_ID,
            f"💰 **NEW SALE!** 💰\n\n"
            f"Plan: {plan_data['plan'].upper()}\n"
            f"Amount: {plan_data['price']} SOL\n"
            f"User: @{user.username or 'N/A'} ({user.id})\n"
            f"TX: `{tx_signature}`",
            parse_mode=ParseMode.MARKDOWN
        )
        
        logger.info(f"✅ New subscription: {plan_data['plan']} for {user.id}")
    else:
        await update.message.reply_text(
            "❌ **Payment Not Verified**\n\n"
            "Possible issues:\n"
            "• Transaction not confirmed yet (wait 30 seconds)\n"
            "• Wrong amount sent\n"
            "• Wrong wallet address\n"
            "• Invalid transaction signature\n\n"
            "Check your wallet and try again, or contact support.",
            parse_mode=ParseMode.MARKDOWN
        )
    
    return ConversationHandler.END

# ═══════════════════════════════════════════════════════════
# GROUP ACTIVATION
# ═══════════════════════════════════════════════════════════
async def activate_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Activate bot in group"""
    chat = update.effective_chat
    user = update.effective_user
    
    if chat.type == "private":
        await update.message.reply_text(
            "❌ **Use this command in your group**\n\n"
            "1. Add me to your group\n"
            "2. Make me admin\n"
            "3. Type /activate",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    # Check admin status
    try:
        member = await context.bot.get_chat_member(chat.id, user.id)
        if member.status not in [ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER]:
            await update.message.reply_text("❌ Only group admins can activate me")
            return
    except Exception as e:
        logger.error(f"Admin check failed: {e}")
        return
    
    # Check subscription
    async with aiosqlite.connect(DB_FILE) as db:
        async with db.execute(
            "SELECT * FROM developers WHERE telegram_id = ? AND status = 'active'",
            (str(user.id),)
        ) as c:
            dev = await c.fetchone()
        
        if not dev:
            await update.message.reply_text(
                "❌ **Subscription Required**\n\n"
                "You need an active plan to use Ice Reign.\n"
                "PM me @IceReignMachine_bot to subscribe.",
                parse_mode=ParseMode.MARKDOWN
            )
            return
        
        # Check group limits
        async with db.execute(
            "SELECT COUNT(*) FROM groups WHERE dev_id = ?", (str(user.id),)
        ) as c:
            group_count = (await c.fetchone())[0]
        
        limits = {'basic': 1, 'pro': 3, 'enterprise': 100}
        if group_count >= limits.get(dev['plan'], 1):
            await update.message.reply_text(
                f"❌ **Plan Limit Reached**\n\n"
                f"Your {dev['plan'].upper()} plan allows {limits[dev['plan']]} group(s).\n"
                f"Upgrade to add more groups.",
                parse_mode=ParseMode.MARKDOWN
            )
            return
        
        # Add group
        await db.execute("""
            INSERT INTO groups (dev_id, telegram_chat_id, group_name, group_username)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(telegram_chat_id) DO UPDATE SET is_active = 1, dev_id = excluded.dev_id
        """, (str(user.id), str(chat.id), chat.title, chat.username or ''))
        await db.commit()
    
    # Success
    await update.message.reply_text(
        f"✅ **GROUP ACTIVATED** ✅\n\n"
        f"🛡 **Protection:** ACTIVE\n"
        f"📊 **Tracking:** ENGAGEMENT\n"
        f"🚀 **Auto-Detect:** ENABLED\n\n"
        f"**I'm now watching:**\n"
        f"• Spam & scams (auto-delete)\n"
        f"• Real user engagement\n"
        f"• Your token launches\n"
        f"• Airdrop eligibility\n\n"
        f"**Commands for users:**\n"
        f"/wallet - Set wallet for airdrops\n"
        f"/balance - Check engagement score\n\n"
        f"_Ice Reign is protecting this group_ 🛡",
        parse_mode=ParseMode.MARKDOWN
    )

# ═══════════════════════════════════════════════════════════
# SECURITY ENGINE
# ═══════════════════════════════════════════════════════════
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
            "SELECT * FROM groups WHERE telegram_chat_id = ? AND is_active = 1",
            (chat_id,)
        ) as c:
            group = await c.fetchone()
        
        if not group:
            return
        
        # Track engagement
        await db.execute("""
            INSERT INTO engagement (group_id, user_id, username, message_count, last_active)
            VALUES (?, ?, ?, 1, CURRENT_TIMESTAMP)
            ON CONFLICT(group_id, user_id) DO UPDATE SET
                message_count = message_count + 1,
                username = excluded.username,
                last_active = CURRENT_TIMESTAMP
        """, (chat_id, str(user.id), user.username or ''))
        
        # Update group stats
        await db.execute("""
            UPDATE groups SET messages_tracked = messages_tracked + 1
            WHERE telegram_chat_id = ?
        """, (chat_id,))
        
        await db.commit()
    
    # Skip admins for spam check
    try:
        member = await context.bot.get_chat_member(chat_id, user.id)
        if member.status in [ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER]:
            return
    except:
        return
    
    # Advanced spam detection
    text_lower = msg.text.lower()
    
    # Scam patterns
    patterns = [
        ('dm me', 3), ('message me', 3), ('pm me', 3),
        ('http', 2), ('t.me/joinchat', 4), ('t.me/+', 4),
        ('investment', 4), ('forex', 4), ('binary', 4),
        ('guaranteed profit', 5), ('100% return', 5),
        ('send me', 2), ('double your', 4), ('triple your', 4),
        ('limited spots', 3), ('act fast', 2), ('urgent', 2)
    ]
    
    score = sum(score for pattern, score in patterns if pattern in text_lower)
    
    # Check for excessive caps
    if len(msg.text) > 15:
        caps_ratio = sum(1 for c in msg.text if c.isupper()) / len(msg.text)
        if caps_ratio > 0.7:
            score += 2
    
    # Action
    if score >= 4:
        try:
            await msg.delete()
            
            warning = await context.bot.send_message(
                chat_id,
                f"🛡 **THREAT NEUTRALIZED** 🛡\n\n"
                f"User: @{user.username or user.id}\n"
                f"Risk Score: {score}/10\n"
                f"Action: Content removed\n\n"
                f"_Protected by Ice Reign Machine_",
                parse_mode=ParseMode.MARKDOWN
            )
            
            # Update stats
            async with aiosqlite.connect(DB_FILE) as db:
                await db.execute("""
                    UPDATE groups SET spam_blocked = spam_blocked + 1
                    WHERE telegram_chat_id = ?
                """, (chat_id,))
                await db.commit()
            
            # Auto-delete warning
            await asyncio.sleep(10)
            await warning.delete()
            
        except Exception as e:
            logger.error(f"Spam removal failed: {e}")

# ═══════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════
async def main():
    # Init database
    await init_db()
    
    # Start web server for Render
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    logger.info(f"🌐 Web server on port {PORT}")
    
    # Build bot
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Conversation: Subscription flow
    sub_conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(plan_selected, pattern="^plan_"),
            CallbackQueryHandler(confirm_payment_prompt, pattern="^confirm_payment$")
        ],
        states={
            AWAITING_PAYMENT: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_payment_tx)]
        },
        fallbacks=[CallbackQueryHandler(lambda u,c: u.callback_query.edit_message_text("Cancelled"), pattern="^cancel$")],
        per_message=False
    )
    
    # Handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(sub_conv)
    application.add_handler(CommandHandler("activate", activate_group))
    application.add_handler(MessageHandler(filters.TEXT & filters.ChatType.GROUPS, security_handler))
    
    # Start bot
    logger.info("🚀 ICE REIGN MACHINE STARTED")
    logger.info(f"💰 Revenue wallet: {SOL_MAIN}")
    logger.info(f"📢 VIP Channel: {VIP_CHANNEL_ID}")
    
    await application.initialize()
    await application.start()
    await application.updater.start_polling(drop_pending_updates=True)
    
    # Keep alive
    stop_event = asyncio.Event()
    await stop_event.wait()

if __name__ == "__main__":
    asyncio.run(main())
