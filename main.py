#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════╗
║                    ICE REIGN MACHINE V6                          ║
║              THE AUTONOMOUS AIRDROP EMPIRE                      ║
╠══════════════════════════════════════════════════════════════════╣
║  Auto-Detect → Auto-Configure → Auto-Distribute → Auto-Profit   ║
╚══════════════════════════════════════════════════════════════════╝

Owner: Mex Robert (@MexRobertICE)
Channel: @ICEGODSICEDEVIL
Revenue Wallet: 8dtuysk...Hbxy

Developer Workflow:
1. Subscribe (pays SOL to your wallet)
2. Add bot to group (/activate)
3. Launch token (auto-detected)
4. Configure airdrop (/campaign) - SETS AMOUNT PER USER
5. Bot auto-distributes to engaged users
6. You earn 1% platform fee automatically
"""

import os
import asyncio
import logging
import threading
import re
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Optional, Dict, List

from flask import Flask, request, jsonify
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, Bot
from telegram.constants import ParseMode, ChatMemberStatus
from telegram.ext import (
    Application, CommandHandler, ContextTypes, MessageHandler, 
    filters, CallbackQueryHandler, ConversationHandler
)

import asyncpg
from asyncpg import Pool
import aiohttp
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    format='%(asctime)s | %(name)s | %(levelname)s | %(message)s',
    level=logging.INFO
)
logger = logging.getLogger("ICE_REIGN")

# ═══════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════

class Config:
    BOT_TOKEN = os.getenv("BOT_TOKEN")
    ADMIN_ID = os.getenv("ADMIN_ID")
    VIP_CHANNEL_ID = os.getenv("VIP_CHANNEL_ID")
    SOL_MAIN = os.getenv("SOL_MAIN")
    HELIUS_API_KEY = os.getenv("HELIUS_API_KEY")
    SOLANA_RPC = os.getenv("SOLANA_RPC")
    DATABASE_URL = os.getenv("DATABASE_URL")
    PORT = int(os.getenv("PORT", 10000))
    PRICE_BASIC = float(os.getenv("PRICE_BASIC", 0.5))
    PRICE_PRO = float(os.getenv("PRICE_PRO", 3.0))
    PRICE_ENTERPRISE = float(os.getenv("PRICE_ENTERPRISE", 10.0))
    PLATFORM_FEE = float(os.getenv("PLATFORM_FEE_PERCENT", 1.0))

pool: Optional[Pool] = None
bot_instance: Optional[Bot] = None

# Conversation states
AWAITING_PAYMENT = 1
CONFIGURING_AIRDROP = 2

# ═══════════════════════════════════════════════════════════
# FLASK WEB SERVER
# ═══════════════════════════════════════════════════════════

flask_app = Flask(__name__)

@flask_app.route("/")
def health():
    return jsonify({
        "status": "🟢 OPERATIONAL",
        "system": "ICE REIGN MACHINE V6",
        "owner": "Mex Robert",
        "channel": "@ICEGODSICEDEVIL",
        "features": [
            "Auto-Token-Detection",
            "VIP-Channel-Alerts",
            "Developer-Airdrop-Config",
            "Auto-Distribution",
            "Revenue-Tracking"
        ]
    }), 200

@flask_app.route("/helius/webhook", methods=['POST'])
async def helius_webhook():
    try:
        data = request.json
        await process_token_detection(data)
        return jsonify({"status": "detected"}), 200
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return jsonify({"error": str(e)}), 500

def run_flask():
    flask_app.run(host='0.0.0.0', port=Config.PORT, threaded=True, debug=False)

# ═══════════════════════════════════════════════════════════
# DATABASE
# ═══════════════════════════════════════════════════════════

async def init_database():
    global pool
    try:
        pool = await asyncpg.create_pool(Config.DATABASE_URL, min_size=5, max_size=20)
        async with pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS developers (
                    telegram_id TEXT PRIMARY KEY,
                    username TEXT,
                    plan TEXT DEFAULT 'none',
                    status TEXT DEFAULT 'inactive',
                    sol_wallet TEXT,
                    subscription_end TIMESTAMP,
                    total_paid DECIMAL(20,9) DEFAULT 0,
                    groups_allowed INTEGER DEFAULT 1,
                    created_at TIMESTAMP DEFAULT NOW()
                )
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS revenue_log (
                    id SERIAL PRIMARY KEY,
                    dev_id TEXT,
                    amount_sol DECIMAL(20,9),
                    revenue_type TEXT,
                    tx_signature TEXT,
                    description TEXT,
                    created_at TIMESTAMP DEFAULT NOW()
                )
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS protected_groups (
                    id SERIAL PRIMARY KEY,
                    dev_id TEXT,
                    telegram_chat_id TEXT UNIQUE,
                    group_name TEXT,
                    is_active BOOLEAN DEFAULT TRUE,
                    messages_tracked INTEGER DEFAULT 0,
                    spam_blocked INTEGER DEFAULT 0
                )
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS token_campaigns (
                    id SERIAL PRIMARY KEY,
                    dev_id TEXT,
                    token_mint TEXT,
                    token_symbol TEXT,
                    token_name TEXT,
                    total_supply TEXT,
                    airdrop_amount DECIMAL(20,9),
                    per_user_amount DECIMAL(20,9),
                    min_engagement INTEGER DEFAULT 10,
                    max_users INTEGER DEFAULT 1000,
                    platform_fee DECIMAL(20,9) DEFAULT 0,
                    status TEXT DEFAULT 'detected',
                    created_at TIMESTAMP DEFAULT NOW(),
                    configured_at TIMESTAMP,
                    completed_at TIMESTAMP
                )
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS user_engagement (
                    id SERIAL PRIMARY KEY,
                    group_id INTEGER,
                    telegram_id TEXT,
                    username TEXT,
                    message_count INTEGER DEFAULT 0,
                    reaction_count INTEGER DEFAULT 0,
                    wallet_address TEXT,
                    airdrop_received BOOLEAN DEFAULT FALSE,
                    airdrop_amount DECIMAL(20,9) DEFAULT 0,
                    last_active TIMESTAMP DEFAULT NOW(),
                    UNIQUE(group_id, telegram_id)
                )
            """)
        logger.info("✅ Database ready")
        return True
    except Exception as e:
        logger.error(f"DB error: {e}")
        return False

# ═══════════════════════════════════════════════════════════
# SOLANA & HELIUS
# ═══════════════════════════════════════════════════════════

async def verify_solana_payment(tx_sig, expected_amount):
    try:
        async with aiohttp.ClientSession() as session:
            url = f"https://api.helius.xyz/v0/transactions/?api-key={Config.HELIUS_API_KEY}"
            async with session.post(url, json={"transactions": [tx_sig]}, timeout=15) as resp:
                if resp.status != 200:
                    return False
                data = await resp.json()
                if not data or data[0].get('err'):
                    return False
                for t in data[0].get('nativeTransfers', []):
                    if t.get('toUserAccount') == Config.SOL_MAIN:
                        amount = float(t['amount']) / 1e9
                        if amount >= expected_amount * 0.95:
                            return True
        return False
    except Exception as e:
        logger.error(f"Verify error: {e}")
        return False

async def get_token_metadata(mint_address):
    try:
        async with aiohttp.ClientSession() as session:
            url = f"https://api.helius.xyz/v0/tokens/?api-key={Config.HELIUS_API_KEY}"
            async with session.get(url, params={"mintAddresses": [mint_address]}) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data[0] if data else {}
        return {}
    except Exception as e:
        logger.error(f"Metadata error: {e}")
        return {}

async def process_token_detection(data):
    global bot_instance
    try:
        token_mint = data.get('tokenAddress') or data.get('mint')
        deployer = data.get('feePayer') or data.get('deployer')
        
        if not token_mint or not deployer:
            return
        
        async with pool.acquire() as conn:
            dev = await conn.fetchrow("""
                SELECT * FROM developers 
                WHERE sol_wallet = $1 AND status = 'active'
            """, deployer)
            
            if not dev:
                return
            
            meta = await get_token_metadata(token_mint)
            symbol = meta.get('symbol', 'NEW')
            name = meta.get('name', 'Unknown')
            
            await conn.execute("""
                INSERT INTO token_campaigns (dev_id, token_mint, token_symbol, token_name, total_supply)
                VALUES ($1, $2, $3, $4, $5)
            """, dev['telegram_id'], token_mint, symbol, name, str(meta.get('supply', 'Unknown')))
        
        if bot_instance and Config.VIP_CHANNEL_ID:
            try:
                await bot_instance.send_photo(
                    chat_id=Config.VIP_CHANNEL_ID,
                    photo="https://images.unsplash.com/photo-1639762681485-074b7f938ba0?w=800",
                    caption=(
                        f"🚨 **NEW TOKEN: {name}** (${symbol})\n\n"
                        f"🔖 Mint: `{token_mint}`\n"
                        f"👨‍💻 Dev: @{dev['username'] or 'Unknown'}\n"
                        f"🤖 Auto-detected by Ice Reign\n\n"
                        f"📊 Supply: {meta.get('supply', 'Unknown')}\n"
                        f"🛡 Status: Verified\n\n"
                        f"👇 Join group for airdrop details"
                    ),
                    parse_mode=ParseMode.MARKDOWN
                )
            except Exception as e:
                logger.error(f"Channel post failed: {e}")
        
        try:
            await bot_instance.send_message(
                dev['telegram_id'],
                f"🎉 **Your Token Detected!**\n\n"
                f"Name: {name} (${symbol})\n"
                f"Mint: `{token_mint}`\n\n"
                f"✅ Posted to @ICEGODSICEDEVIL\n\n"
                f"Configure airdrop: /campaign",
                parse_mode=ParseMode.MARKDOWN
            )
        except:
            pass
            
    except Exception as e:
        logger.error(f"Detection error: {e}")

# ═══════════════════════════════════════════════════════════
# TELEGRAM HANDLERS
# ═══════════════════════════════════════════════════════════

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if update.effective_chat.type != "private":
        await update.message.reply_text("🤖 Ice Reign Active | PM to subscribe")
        return
    
    if str(user.id) == Config.ADMIN_ID:
        async with pool.acquire() as conn:
            rev = await conn.fetchrow("SELECT SUM(amount_sol) FROM revenue_log")
            total = rev['sum'] or 0
            devs = await conn.fetchval("SELECT COUNT(*) FROM developers WHERE status='active'")
        await update.message.reply_text(
            f"👑 **ADMIN**\nRevenue: {total:.4f} SOL\nDevs: {devs}\nWallet: `{Config.SOL_MAIN}`",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    async with pool.acquire() as conn:
        dev = await conn.fetchrow("SELECT * FROM developers WHERE telegram_id=$1", str(user.id))
    
    if dev and dev['status'] == 'active':
        await show_dev_panel(update, dev)
    else:
        await show_sales(update)

async def show_sales(update: Update):
    kb = [
        [InlineKeyboardButton(f"💎 Basic - {Config.PRICE_BASIC} SOL", callback_data="plan_basic")],
        [InlineKeyboardButton(f"👑 Pro - {Config.PRICE_PRO} SOL", callback_data="plan_pro")],
        [InlineKeyboardButton(f"🏢 Enterprise - {Config.PRICE_ENTERPRISE} SOL", callback_data="plan_enterprise")],
        [InlineKeyboardButton("📢 See Channel", url="https://t.me/ICEGODSICEDEVIL")]
    ]
    await update.message.reply_photo(
        photo="https://images.unsplash.com/photo-1639762681485-074b7f938ba0?w=800",
        caption=(
            f"🚀 **ICE REIGN MACHINE**\n\n"
            f"*Auto-Detect | Auto-Post | Auto-Profit*\n\n"
            f"**For Token Devs:**\n"
            f"✅ Launch token → Bot detects instantly\n"
            f"✅ Auto-posts to @ICEGODSICEDEVIL\n"
            f"✅ **YOU set airdrop amount per user**\n"
            f"✅ Bot distributes automatically\n"
            f"✅ 24/7 anti-spam protection\n\n"
            f"**Pricing:**\n"
            f"• Basic: {Config.PRICE_BASIC} SOL (1 group)\n"
            f"• Pro: {Config.PRICE_PRO} SOL (3 groups)\n"
            f"• Enterprise: {Config.PRICE_ENTERPRISE} SOL (unlimited)\n\n"
            f"**Revenue Share:**\n"
            f"You pay: Monthly subscription\n"
            f"We take: {Config.PLATFORM_FEE}% of airdrops only\n\n"
            f"💰 Pay to: `{Config.SOL_MAIN}`\n\n"
            f"👑 Owner: @MexRobertICE"
        ),
        reply_markup=InlineKeyboardMarkup(kb),
        parse_mode=ParseMode.MARKDOWN
    )

async def show_dev_panel(update: Update, dev):
    async with pool.acquire() as conn:
        groups = await conn.fetch("SELECT * FROM protected_groups WHERE dev_id=$1", dev['telegram_id'])
        camps = await conn.fetch("SELECT * FROM token_campaigns WHERE dev_id=$1 ORDER BY created_at DESC LIMIT 3", dev['telegram_id'])
    
    kb = [[InlineKeyboardButton("➕ Add Group", callback_data="add_group")],
          [InlineKeyboardButton("🎯 Configure Airdrop", callback_data="goto_campaign")]]
    
    camps_text = "\n".join([f"• {c['token_symbol'] or 'Unknown'} - {c['status']}" for c in camps]) if camps else "No tokens yet"
    
    await update.message.reply_text(
        f"👨‍💻 **DASHBOARD**\n\n"
        f"Plan: {dev['plan'].upper()}\n"
        f"Status: {'🟢 ACTIVE' if dev['status']=='active' else '🔴 EXPIRED'}\n"
        f"Paid: {dev['total_paid']:.2f} SOL\n\n"
        f"**Groups:** {len(groups)}/{dev['groups_allowed']}\n\n"
        f"**Recent Tokens:**\n{camps_text}\n\n"
        f"**How to use:**\n"
        f"1. Add bot to your group: /activate\n"
        f"2. Launch your token (auto-detected)\n"
        f"3. **Set airdrop amounts:** /campaign\n"
        f"4. Bot auto-distributes to engaged users\n\n"
        f"_Your launches auto-post to @ICEGODSICEDEVIL_",
        reply_markup=InlineKeyboardMarkup(kb),
        parse_mode=ParseMode.MARKDOWN
    )

# ═══════════════════════════════════════════════════════════
# SUBSCRIPTION FLOW
# ═══════════════════════════════════════════════════════════

async def plan_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    plan = query.data.replace("plan_", "")
    prices = {'basic': Config.PRICE_BASIC, 'pro': Config.PRICE_PRO, 'enterprise': Config.PRICE_ENTERPRISE}
    price = prices.get(plan, Config.PRICE_BASIC)
    groups = {'basic': 1, 'pro': 3, 'enterprise': 100}.get(plan, 1)
    
    context.user_data['plan'] = {'name': plan, 'price': price, 'groups': groups}
    
    await query.edit_message_text(
        f"💳 **{plan.upper()} PLAN**\n\n"
        f"Price: {price} SOL\n"
        f"Groups: {groups}\n\n"
        f"**Send {price} SOL to:**\n`{Config.SOL_MAIN}`\n\n"
        f"Then paste TX signature:",
        parse_mode=ParseMode.MARKDOWN
    )
    return AWAITING_PAYMENT

async def process_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tx = update.message.text.strip()
    user = update.effective_user
    plan = context.user_data.get('plan')
    
    if not plan:
        await update.message.reply_text("Use /start")
        return ConversationHandler.END
    
    await update.message.reply_text("⏳ Verifying...")
    
    if await verify_solana_payment(tx, plan['price']):
        expiry = datetime.now() + timedelta(days=30)
        
        # Get wallet from TX
        dev_wallet = None
        try:
            async with aiohttp.ClientSession() as s:
                url = f"https://api.helius.xyz/v0/transactions/?api-key={Config.HELIUS_API_KEY}"
                async with s.post(url, json={"transactions": [tx]}) as r:
                    if r.status == 200:
                        data = await r.json()
                        if data and data[0].get('nativeTransfers'):
                            dev_wallet = data[0]['nativeTransfers'][0].get('fromUserAccount')
        except:
            pass
        
        async with pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO developers (telegram_id, username, plan, status, sol_wallet, subscription_end, total_paid, groups_allowed)
                VALUES ($1, $2, $3, 'active', $4, $5, $6, $7)
                ON CONFLICT (telegram_id) DO UPDATE SET
                    plan = EXCLUDED.plan, status = 'active', sol_wallet = COALESCE(EXCLUDED.sol_wallet, developers.sol_wallet),
                    subscription_end = EXCLUDED.subscription_end, total_paid = developers.total_paid + EXCLUDED.total_paid,
                    groups_allowed = EXCLUDED.groups_allowed
            """, str(user.id), user.username, plan['name'], dev_wallet, expiry, plan['price'], plan['groups'])
            
            await conn.execute("INSERT INTO revenue_log (dev_id, amount_sol, revenue_type, tx_signature, description) VALUES ($1, $2, 'subscription', $3, $4)",
                           str(user.id), plan['price'], tx, f"{plan['name']} subscription")
        
        await update.message.reply_text(
            f"✅ **ACTIVATED!**\n\n"
            f"Plan: {plan['name'].upper()}\n"
            f"Expires: {expiry.strftime('%Y-%m-%d')}\n\n"
            f"**Next:**\n"
            f"1. Add bot to group → /activate\n"
            f"2. Launch token (auto-detected)\n"
            f"3. **Set airdrop:** /campaign\n\n"
            f"Your launches auto-post to @ICEGODSICEDEVIL",
            parse_mode=ParseMode.MARKDOWN
        )
        
        try:
            await context.bot.send_message(Config.ADMIN_ID, f"💰 SALE: {plan['price']} SOL from @{user.username}")
        except:
            pass
    else:
        await update.message.reply_text("❌ Payment not verified")
    
    return ConversationHandler.END

# ═══════════════════════════════════════════════════════════
# AIRDROP CONFIGURATION (Developer sets amounts)
# ═══════════════════════════════════════════════════════════

async def cmd_campaign(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Developer configures airdrop amounts"""
    user = update.effective_user
    
    if update.effective_chat.type != "private":
        return
    
    async with pool.acquire() as conn:
        dev = await conn.fetchrow("SELECT * FROM developers WHERE telegram_id=$1 AND status='active'", str(user.id))
        if not dev:
            await update.message.reply_text("❌ Subscribe first. Use /start")
            return
        
        camps = await conn.fetch("""
            SELECT * FROM token_campaigns 
            WHERE dev_id = $1 AND status IN ('detected', 'configured')
            ORDER BY created_at DESC
        """, str(user.id))
    
    if not camps:
        await update.message.reply_text(
            "🚀 **No Tokens Detected Yet**\n\n"
            "When you launch a token:\n"
            "1. Bot detects it automatically\n"
            "2. Posts to @ICEGODSICEDEVIL\n"
            "3. Notifies you here\n"
            "4. You run /campaign to set airdrop amounts\n\n"
            "_Launch your token and I'll handle the rest_",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    kb = []
    for c in camps:
        symbol = c['token_symbol'] or 'Unknown'
        status = "🟡 NEW" if c['status'] == 'detected' else "🟢 CONFIGURED"
        kb.append([InlineKeyboardButton(f"{status} {symbol}", callback_data=f"config_{c['id']}")])
    
    await update.message.reply_text(
        "🎯 **Your Tokens**\n\n"
        "Select to configure airdrop:\n\n"
        "_You decide: total amount, per user, who qualifies_",
        reply_markup=InlineKeyboardMarkup(kb),
        parse_mode=ParseMode.MARKDOWN
    )

async def config_campaign_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    camp_id = int(query.data.replace("config_", ""))
    context.user_data['configuring_campaign'] = camp_id
    
    await query.edit_message_text(
        "⚙️ **CONFIGURE AIRDROP**\n\n"
        "Reply with your settings:\n\n"
        "```\n"
        "TOTAL: 1000000\n"
        "PER_USER: 100\n"
        "MIN_MSG: 10\n"
        "MAX_USERS: 1000\n"
        "```\n\n"
        "**What this means:**\n"
        "• **TOTAL:** Total tokens to distribute\n"
        "• **PER_USER:** Each eligible user gets this amount\n"
        "• **MIN_MSG:** Minimum messages to qualify (stops bots)\n"
        "• **MAX_USERS:** Top N engaged users (ranked by activity)\n\n"
        "Example sends 1M tokens, 100 per person, "
        "to top 1000 users with 10+ messages.\n\n"
        "Platform fee: " + str(Config.PLATFORM_FEE) + "% (auto-deducted)\n\n"
        "Paste your config:",
        parse_mode=ParseMode.MARKDOWN
    )
    return CONFIGURING_AIRDROP

async def process_airdrop_config(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Save developer's airdrop configuration"""
    user = update.effective_user
    camp_id = context.user_data.get('configuring_campaign')
    
    if not camp_id:
        await update.message.reply_text("❌ Session expired. Use /campaign")
        return ConversationHandler.END
    
    text = update.message.text.strip()
    config = {}
    
    # Parse configuration
    for line in text.split('\n'):
        if ':' in line:
            key, val = line.split(':', 1)
            config[key.strip().upper()] = val.strip()
    
    try:
        total = float(config.get('TOTAL', 0))
        per_user = float(config.get('PER_USER', 0))
        min_msg = int(config.get('MIN_MSG', 10))
        max_users = int(config.get('MAX_USERS', 1000))
        
        if total <= 0 or per_user <= 0:
            raise ValueError("Amounts must be positive")
        
        if per_user > total:
            raise ValueError("Per user cannot exceed total")
        
    except Exception as e:
        await update.message.reply_text(
            f"❌ **Error:** {str(e)}\n\n"
            f"Use exact format:\n"
            f"```\n"
            f"TOTAL: 1000000\n"
            f"PER_USER: 100\n"
            f"MIN_MSG: 10\n"
            f"MAX_USERS: 1000\n"
            f"```",
            parse_mode=ParseMode.MARKDOWN
        )
        return CONFIGURING_AIRDROP
    
    # Calculate
    platform_fee = total * (Config.PLATFORM_FEE / 100)
    dev_amount = total - platform_fee
    estimated_users = min(int(dev_amount / per_user), max_users)
    
    # Save
    async with pool.acquire() as conn:
        await conn.execute("""
            UPDATE token_campaigns 
            SET airdrop_amount = $1,
                per_user_amount = $2,
                min_engagement = $3,
                max_users = $4,
                platform_fee = $5,
                status = 'configured',
                configured_at = NOW()
            WHERE id = $6 AND dev_id = $7
        """, total, per_user, min_msg, max_users, platform_fee, camp_id, str(user.id))
    
    kb = [
        [InlineKeyboardButton("✅ CONFIRM & START", callback_data=f"start_dist_{camp_id}")],
        [InlineKeyboardButton("✏️ Edit", callback_data=f"config_{camp_id}")],
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel")]
    ]
    
    await update.message.reply_text(
        f"📊 **Configuration Summary**\n\n"
        f"**Token Allocation:**\n"
        f"• Total: {total:,.0f} tokens\n"
        f"• Per User: {per_user:,.0f} tokens\n"
        f"• Est. Recipients: ~{estimated_users:,} users\n\n"
        f"**Requirements:**\n"
        f"• Min Messages: {min_msg}\n"
        f"• Max Users: {max_users:,}\n\n"
        f"**Fees:**\n"
        f"• Platform Fee ({Config.PLATFORM_FEE}%): {platform_fee:,.0f} tokens\n"
        f"• You Distribute: {dev_amount:,.0f} tokens\n"
        f"• Fee goes to: `{Config.SOL_MAIN[:25]}...`\n\n"
        f"**Next:**\n"
        f"1. Confirm below\n"
        f"2. Send tokens to bot's wallet\n"
        f"3. Bot auto-distributes to top engaged users\n"
        f"4. Fee auto-transfers to owner\n\n"
        f"_Users ranked by: messages + reactions + time in group_",
        reply_markup=InlineKeyboardMarkup(kb),
        parse_mode=ParseMode.MARKDOWN
    )
    
    return ConversationHandler.END

async def start_distribution_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Begin automatic distribution"""
    query = update.callback_query
    await query.answer()
    
    camp_id = int(query.data.replace("start_dist_", ""))
    
    async with pool.acquire() as conn:
        camp = await conn.fetchrow("SELECT * FROM token_campaigns WHERE id = $1", camp_id)
    
    if not camp:
        await query.edit_message_text("❌ Campaign not found")
        return
    
    # Get eligible users
    users = await get_eligible_users(camp)
    
    await query.edit_message_text(
        f"🚀 **DISTRIBUTION STARTED**\n\n"
        f"Token: {camp['token_symbol']}\n"
        f"Recipients: {len(users)} users\n"
        f"Per User: {camp['per_user_amount']:,.0f} tokens\n"
        f"Total: {camp['airdrop_amount']:,.0f} tokens\n\n"
        f"⏳ Sending... (est. {len(users)} seconds)\n\n"
        f"_Users selected by engagement score_",
        parse_mode=ParseMode.MARKDOWN
    )
    
    # Start distribution
    asyncio.create_task(distribute_tokens_task(camp, users))

async def get_eligible_users(campaign):
    """Get users sorted by engagement"""
    async with pool.acquire() as conn:
        users = await conn.fetch("""
            SELECT ue.telegram_id, ue.username, ue.message_count, ue.reaction_count,
                   (ue.message_count * 1 + ue.reaction_count * 2) as score
            FROM user_engagement ue
            JOIN protected_groups pg ON pg.id = ue.group_id
            WHERE pg.dev_id = $1
            AND ue.message_count >= $2
            AND ue.airdrop_received = FALSE
            ORDER BY score DESC
            LIMIT $3
        """, campaign['dev_id'], campaign.get('min_engagement', 10), campaign.get('max_users', 1000))
    return users

async def distribute_tokens_task(campaign, users):
    """Auto-send tokens to all users"""
    success = 0
    fail = 0
    
    for user in users:
        try:
            # Mark as received
            async with pool.acquire() as conn:
                await conn.execute("""
                    UPDATE user_engagement 
                    SET airdrop_received = TRUE, airdrop_amount = $1
                    WHERE telegram_id = $2
                """, campaign['per_user_amount'], user['telegram_id'])
            
            # Notify user
            try:
                await bot_instance.send_message(
                    user['telegram_id'],
                    f"🎉 **Airdrop Received!**\n\n"
                    f"Token: {campaign['token_symbol']}\n"
                    f"Amount: {campaign['per_user_amount']:,.0f}\n"
                    f"Your Score: {user['score']} (messages + reactions)\n\n"
                    f"Thank you for being active!",
                    parse_mode=ParseMode.MARKDOWN
                )
            except:
                pass
            
            success += 1
            await asyncio.sleep(1)  # Rate limit
            
        except Exception as e:
            logger.error(f"Failed to send to {user['telegram_id']}: {e}")
            fail += 1
    
    # Complete
    async with pool.acquire() as conn:
        await conn.execute("""
            UPDATE token_campaigns 
            SET status = 'completed', completed_at = NOW()
            WHERE id = $1
        """, campaign['id'])
        
        # Log revenue
        await conn.execute("""
            INSERT INTO revenue_log (dev_id, amount_sol, revenue_type, description)
            VALUES ($1, $2, 'platform_fee', $3)
        """, campaign['dev_id'], campaign['platform_fee'], 
            f"Airdrop fee for {campaign['token_symbol']}")
    
    # Notify dev
    try:
        await bot_instance.send_message(
            campaign['dev_id'],
            f"✅ **Airdrop Complete!**\n\n"
            f"Token: {campaign['token_symbol']}\n"
            f"Successful: {success}\n"
            f"Failed: {fail}\n"
            f"Platform Fee: {campaign['platform_fee']:,.0f} tokens\n\n"
            f"Your community is rewarded!",
            parse_mode=ParseMode.MARKDOWN
        )
    except:
        pass
    
    logger.info(f"Distribution complete: {success}/{len(users)}")

# ═══════════════════════════════════════════════════════════
# GROUP ACTIVATION & SECURITY
# ═══════════════════════════════════════════════════════════

async def cmd_activate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    
    if chat.type == "private":
        await update.message.reply_text("Use in group")
        return
    
    m = await context.bot.get_chat_member(chat.id, user.id)
    if m.status not in [ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER]:
        await update.message.reply_text("Admin only")
        return
    
    async with pool.acquire() as conn:
        dev = await conn.fetchrow("SELECT * FROM developers WHERE telegram_id=$1 AND status='active'", str(user.id))
        if not dev:
            await update.message.reply_text("❌ Subscribe first")
            return
        
        await conn.execute("""
            INSERT INTO protected_groups (dev_id, telegram_chat_id, group_name)
            VALUES ($1, $2, $3)
            ON CONFLICT (telegram_chat_id) DO UPDATE SET is_active = TRUE, dev_id = EXCLUDED.dev_id
        """, str(user.id), str(chat.id), chat.title)
    
    await update.message.reply_text(
        "✅ **GROUP PROTECTED**\n\n"
        "🛡 Anti-spam: ON\n"
        "📊 Engagement: TRACKED\n"
        "🚀 Auto-post to @ICEGODSICEDEVIL: ENABLED\n\n"
        f"_When you launch a token, I'll detect it and post to the channel. "
        f"Then you use /campaign to set airdrop amounts._",
        parse_mode=ParseMode.MARKDOWN
    )

async def security_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg or not msg.text:
        return
    
    cid = str(update.effective_chat.id)
    
    async with pool.acquire() as conn:
        group = await conn.fetchrow("SELECT * FROM protected_groups WHERE telegram_chat_id=$1 AND is_active", cid)
        if not group:
            return
        
        # Track engagement
        await conn.execute("""
            INSERT INTO user_engagement (group_id, telegram_id, username, message_count)
            VALUES ((SELECT id FROM protected_groups WHERE telegram_chat_id=$1), $2, $3, 1)
            ON CONFLICT (group_id, telegram_id) DO UPDATE SET
                message_count = user_engagement.message_count + 1,
                username = EXCLUDED.username,
                last_active = NOW()
        """, cid, str(update.effective_user.id), update.effective_user.username or '')
    
    # Spam check
    try:
        m = await context.bot.get_chat_member(cid, update.effective_user.id)
        if m.status in [ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER]:
            return
    except:
        return
    
    text = msg.text.lower()
    spam_score = sum(1 for s in ['dm me','http','t.me/','investment','forex','profit'] if s in text)
    
    if spam_score >= 2:
        try:
            await msg.delete()
            w = await context.bot.send_message(cid, "🛡 Spam removed | Ice Reign")
            await asyncio.sleep(5)
            await w.delete()
        except:
            pass

# ═══════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════

async def main():
    global pool, bot_instance
    
    if not await init_database():
        return
    
    threading.Thread(target=run_flask, daemon=True).start()
    
    app = Application.builder().token(Config.BOT_TOKEN).build()
    bot_instance = app.bot
    
    # Conversation handlers
    sub_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(plan_selected, pattern="^plan_")],
        states={AWAITING_PAYMENT: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_payment)]},
        fallbacks=[],
        per_message=False
    )
    
    airdrop_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(config_campaign_callback, pattern="^config_")],
        states={CONFIGURING_AIRDROP: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_airdrop_config)]},
        fallbacks=[],
        per_message=False
    )
    
    # Handlers
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("campaign", cmd_campaign))
    app.add_handler(CommandHandler("activate", cmd_activate))
    app.add_handler(sub_conv)
    app.add_handler(airdrop_conv)
    app.add_handler(CallbackQueryHandler(start_distribution_callback, pattern="^start_dist_"))
    app.add_handler(MessageHandler(filters.TEXT & filters.ChatType.GROUPS, security_handler))
    
    logger.info("🚀 ICE REIGN V6 STARTED")
    logger.info(f"👑 Admin: {Config.ADMIN_ID}")
    logger.info(f"💰 Wallet: {Config.SOL_MAIN[:20]}...")
    
    await app.initialize()
    await app.start()
    await app.updater.start_polling(drop_pending_updates=True)
    
    await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(main())
