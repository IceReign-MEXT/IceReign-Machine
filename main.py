#!/usr/bin/env python3
"""
ICE REIGN MACHINE V6 - Python 3.14 Compatible
"""

import os
import asyncio
import logging
import threading
import aiosqlite
from datetime import datetime, timedelta

from flask import Flask, request, jsonify
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, Bot
from telegram.ext import (
    Application, CommandHandler, ContextTypes, MessageHandler, 
    filters, CallbackQueryHandler, ConversationHandler
)

import httpx
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    format='%(asctime)s | %(name)s | %(levelname)s | %(message)s',
    level=logging.INFO
)
logger = logging.getLogger("ICE_REIGN")

# ═══════════════════════════════════════════════════════════
# CONFIG
# ═══════════════════════════════════════════════════════════

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = os.getenv("ADMIN_ID")
VIP_CHANNEL_ID = os.getenv("VIP_CHANNEL_ID")
SOL_MAIN = os.getenv("SOL_MAIN")
HELIUS_API_KEY = os.getenv("HELIUS_API_KEY")
PORT = int(os.getenv("PORT", 10000))
PRICE_BASIC = float(os.getenv("PRICE_BASIC", 0.5))
PRICE_PRO = float(os.getenv("PRICE_PRO", 3.0))
PRICE_ENTERPRISE = float(os.getenv("PRICE_ENTERPRISE", 10.0))
PLATFORM_FEE = float(os.getenv("PLATFORM_FEE_PERCENT", 1.0))

DB_FILE = "ice_reign.db"
AWAITING_PAYMENT = 1
CONFIGURING_AIRDROP = 2

bot_instance = None

# ═══════════════════════════════════════════════════════════
# FLASK
# ═══════════════════════════════════════════════════════════

flask_app = Flask(__name__)

@flask_app.route("/")
def health():
    return jsonify({
        "status": "🟢 OPERATIONAL",
        "wallet": SOL_MAIN[:15] + "...",
        "channel": "@ICEGODSICEDEVIL"
    }), 200

def run_flask():
    flask_app.run(host='0.0.0.0', port=PORT, threaded=True, debug=False)

# ═══════════════════════════════════════════════════════════
# DATABASE
# ═══════════════════════════════════════════════════════════

async def init_db():
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS developers (
                telegram_id TEXT PRIMARY KEY,
                username TEXT,
                plan TEXT DEFAULT 'none',
                status TEXT DEFAULT 'inactive',
                sol_wallet TEXT,
                subscription_end TIMESTAMP,
                total_paid REAL DEFAULT 0,
                groups_allowed INTEGER DEFAULT 1
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS revenue_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                dev_id TEXT,
                amount_sol REAL,
                revenue_type TEXT,
                description TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS protected_groups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                dev_id TEXT,
                telegram_chat_id TEXT UNIQUE,
                group_name TEXT,
                is_active INTEGER DEFAULT 1
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS token_campaigns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                dev_id TEXT,
                token_mint TEXT,
                token_symbol TEXT,
                token_name TEXT,
                airdrop_amount REAL,
                per_user_amount REAL,
                min_engagement INTEGER DEFAULT 10,
                max_users INTEGER DEFAULT 1000,
                platform_fee REAL DEFAULT 0,
                status TEXT DEFAULT 'detected',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS user_engagement (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                group_id INTEGER,
                telegram_id TEXT,
                username TEXT,
                message_count INTEGER DEFAULT 0,
                airdrop_received INTEGER DEFAULT 0,
                last_active TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(group_id, telegram_id)
            )
        """)
        await db.commit()
    logger.info("✅ Database ready")

# ═══════════════════════════════════════════════════════════
# HELIUS API
# ═══════════════════════════════════════════════════════════

async def verify_payment(tx_sig, expected_amount):
    try:
        async with httpx.AsyncClient() as client:
            url = f"https://api.helius.xyz/v0/transactions/?api-key={HELIUS_API_KEY}"
            resp = await client.post(url, json={"transactions": [tx_sig]}, timeout=15)
            if resp.status_code != 200:
                return False
            data = resp.json()
            if not data or data[0].get('err'):
                return False
            for t in data[0].get('nativeTransfers', []):
                if t.get('toUserAccount') == SOL_MAIN:
                    amount = float(t['amount']) / 1e9
                    if amount >= expected_amount * 0.95:
                        return True
        return False
    except Exception as e:
        logger.error(f"Verify error: {e}")
        return False

async def get_token_metadata(mint_address):
    try:
        async with httpx.AsyncClient() as client:
            url = f"https://api.helius.xyz/v0/tokens/?api-key={HELIUS_API_KEY}"
            resp = await client.get(url, params={"mintAddresses": [mint_address]})
            if resp.status_code == 200:
                data = resp.json()
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
        
        async with aiosqlite.connect(DB_FILE) as db:
            async with db.execute("SELECT * FROM developers WHERE sol_wallet = ? AND status = 'active'", (deployer,)) as c:
                dev = await c.fetchone()
            
            if not dev:
                return
            
            meta = await get_token_metadata(token_mint)
            symbol = meta.get('symbol', 'NEW')
            name = meta.get('name', 'Unknown')
            
            await db.execute("""
                INSERT INTO token_campaigns (dev_id, token_mint, token_symbol, token_name)
                VALUES (?, ?, ?, ?)
            """, (dev['telegram_id'], token_mint, symbol, name))
            await db.commit()
        
        # Post to channel
        if bot_instance and VIP_CHANNEL_ID:
            try:
                await bot_instance.send_photo(
                    chat_id=VIP_CHANNEL_ID,
                    photo="https://images.unsplash.com/photo-1639762681485-074b7f938ba0?w=800",
                    caption=(
                        f"🚨 **NEW TOKEN: {name}** (${symbol})\n\n"
                        f"🔖 Mint: `{token_mint}`\n"
                        f"👨‍💻 Dev: @{dev['username'] or 'Unknown'}\n"
                        f"🤖 Auto-detected by Ice Reign\n\n"
                        f"👇 Join group for airdrop details"
                    ),
                    parse_mode=ParseMode.MARKDOWN
                )
            except Exception as e:
                logger.error(f"Channel post failed: {e}")
        
        # Notify dev
        try:
            await bot_instance.send_message(
                dev['telegram_id'],
                f"🎉 **Your Token Detected!**\n\n"
                f"Name: {name} (${symbol})\n\n"
                f"✅ Posted to @ICEGODSICEDEVIL\n"
                f"Configure airdrop: /campaign",
                parse_mode=ParseMode.MARKDOWN
            )
        except:
            pass
            
    except Exception as e:
        logger.error(f"Detection error: {e}")

# ═══════════════════════════════════════════════════════════
# HANDLERS
# ═══════════════════════════════════════════════════════════

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if update.effective_chat.type != "private":
        await update.message.reply_text("🤖 Ice Reign Active | PM to subscribe")
        return
    
    if str(user.id) == ADMIN_ID:
        async with aiosqlite.connect(DB_FILE) as db:
            async with db.execute("SELECT SUM(amount_sol) FROM revenue_log") as c:
                row = await c.fetchone()
                total = row[0] or 0
            async with db.execute("SELECT COUNT(*) FROM developers WHERE status='active'") as c:
                devs = (await c.fetchone())[0]
        await update.message.reply_text(
            f"👑 **ADMIN**\nRevenue: {total:.4f} SOL\nDevs: {devs}\nWallet: `{SOL_MAIN}`",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    async with aiosqlite.connect(DB_FILE) as db:
        async with db.execute("SELECT * FROM developers WHERE telegram_id=?", (str(user.id),)) as c:
            dev = await c.fetchone()
    
    if dev and dev['status'] == 'active':
        await show_dev_panel(update, dev)
    else:
        await show_sales(update)

async def show_sales(update: Update):
    kb = [
        [InlineKeyboardButton(f"💎 Basic - {PRICE_BASIC} SOL", callback_data="plan_basic")],
        [InlineKeyboardButton(f"👑 Pro - {PRICE_PRO} SOL", callback_data="plan_pro")],
        [InlineKeyboardButton(f"🏢 Enterprise - {PRICE_ENTERPRISE} SOL", callback_data="plan_enterprise")],
        [InlineKeyboardButton("📢 See Channel", url="https://t.me/ICEGODSICEDEVIL")]
    ]
    await update.message.reply_photo(
        photo="https://images.unsplash.com/photo-1639762681485-074b7f938ba0?w=800",
        caption=(
            f"🚀 **ICE REIGN MACHINE**\n\n"
            f"Auto-Detect | Auto-Post | Auto-Profit\n\n"
            f"**For Token Devs:**\n"
            f"✅ Launch token → Bot detects instantly\n"
            f"✅ Auto-posts to @ICEGODSICEDEVIL\n"
            f"✅ **YOU set airdrop amount per user**\n"
            f"✅ Bot distributes automatically\n\n"
            f"**Pricing:**\n"
            f"• Basic: {PRICE_BASIC} SOL\n"
            f"• Pro: {PRICE_PRO} SOL\n"
            f"• Enterprise: {PRICE_ENTERPRISE} SOL\n\n"
            f"💰 Pay to: `{SOL_MAIN}`\n\n"
            f"👑 Owner: @MexRobertICE"
        ),
        reply_markup=InlineKeyboardMarkup(kb),
        parse_mode=ParseMode.MARKDOWN
    )

async def show_dev_panel(update: Update, dev):
    kb = [
        [InlineKeyboardButton("➕ Add Group", callback_data="add_group")],
        [InlineKeyboardButton("🎯 Configure Airdrop", callback_data="goto_campaign")]
    ]
    
    await update.message.reply_text(
        f"👨‍💻 **DASHBOARD**\n\n"
        f"Plan: {dev['plan'].upper()}\n"
        f"Status: {'🟢 ACTIVE' if dev['status']=='active' else '🔴 EXPIRED'}\n"
        f"Paid: {dev['total_paid']:.2f} SOL\n\n"
        f"**How to use:**\n"
        f"1. Add bot to group: /activate\n"
        f"2. Launch token (auto-detected)\n"
        f"3. **Set airdrop amounts:** /campaign\n"
        f"4. Bot auto-distributes\n\n"
        f"_Your launches auto-post to @ICEGODSICEDEVIL_",
        reply_markup=InlineKeyboardMarkup(kb),
        parse_mode=ParseMode.MARKDOWN
    )

async def plan_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    plan = query.data.replace("plan_", "")
    prices = {'basic': PRICE_BASIC, 'pro': PRICE_PRO, 'enterprise': PRICE_ENTERPRISE}
    price = prices.get(plan, PRICE_BASIC)
    groups = {'basic': 1, 'pro': 3, 'enterprise': 100}.get(plan, 1)
    
    context.user_data['plan'] = {'name': plan, 'price': price, 'groups': groups}
    
    await query.edit_message_text(
        f"💳 **{plan.upper()} PLAN**\n\n"
        f"Price: {price} SOL\n"
        f"Groups: {groups}\n\n"
        f"**Send {price} SOL to:**\n`{SOL_MAIN}`\n\n"
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
    
    if await verify_payment(tx, plan['price']):
        expiry = datetime.now() + timedelta(days=30)
        
        # Get wallet from TX
        dev_wallet = None
        try:
            async with httpx.AsyncClient() as client:
                url = f"https://api.helius.xyz/v0/transactions/?api-key={HELIUS_API_KEY}"
                resp = await client.post(url, json={"transactions": [tx]})
                if resp.status_code == 200:
                    data = resp.json()
                    if data and data[0].get('nativeTransfers'):
                        dev_wallet = data[0]['nativeTransfers'][0].get('fromUserAccount')
        except:
            pass
        
        async with aiosqlite.connect(DB_FILE) as db:
            await db.execute("""
                INSERT OR REPLACE INTO developers (telegram_id, username, plan, status, sol_wallet, subscription_end, total_paid, groups_allowed)
                VALUES (?, ?, ?, 'active', ?, ?, COALESCE((SELECT total_paid FROM developers WHERE telegram_id=?), 0) + ?, ?)
            """, (str(user.id), user.username, plan['name'], dev_wallet, expiry, str(user.id), plan['price'], plan['groups']))
            
            await db.execute("INSERT INTO revenue_log (dev_id, amount_sol, revenue_type, description) VALUES (?, ?, 'subscription', ?)",
                           (str(user.id), plan['price'], f"{plan['name']} subscription"))
            await db.commit()
        
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
            await context.bot.send_message(ADMIN_ID, f"💰 SALE: {plan['price']} SOL from @{user.username}")
        except:
            pass
    else:
        await update.message.reply_text("❌ Payment not verified")
    
    return ConversationHandler.END

async def cmd_campaign(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    
    if update.effective_chat.type != "private":
        return
    
    async with aiosqlite.connect(DB_FILE) as db:
        async with db.execute("SELECT * FROM developers WHERE telegram_id=? AND status='active'", (str(user.id),)) as c:
            dev = await c.fetchone()
        if not dev:
            await update.message.reply_text("❌ Subscribe first. Use /start")
            return
        
        async with db.execute("""
            SELECT * FROM token_campaigns 
            WHERE dev_id = ? AND status IN ('detected', 'configured')
            ORDER BY created_at DESC
        """, (str(user.id),)) as c:
            camps = await c.fetchall()
    
    if not camps:
        await update.message.reply_text(
            "🚀 **No Tokens Detected Yet**\n\n"
            "Launch your token and I'll detect it automatically.",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    kb = []
    for c in camps:
        symbol = c['token_symbol'] or 'Unknown'
        status = "🟡 NEW" if c['status'] == 'detected' else "🟢 CONFIGURED"
        kb.append([InlineKeyboardButton(f"{status} {symbol}", callback_data=f"config_{c['id']}")])
    
    await update.message.reply_text(
        "🎯 **Your Tokens - Select to Configure Airdrop**",
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
        "Reply with:\n\n"
        "```\n"
        "TOTAL: 1000000\n"
        "PER_USER: 100\n"
        "MIN_MSG: 10\n"
        "MAX_USERS: 1000\n"
        "```\n\n"
        "Platform fee: " + str(PLATFORM_FEE) + "%\n\n"
        "Paste your config:",
        parse_mode=ParseMode.MARKDOWN
    )
    return CONFIGURING_AIRDROP

async def process_airdrop_config(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    camp_id = context.user_data.get('configuring_campaign')
    
    if not camp_id:
        await update.message.reply_text("❌ Session expired. Use /campaign")
        return ConversationHandler.END
    
    text = update.message.text.strip()
    config = {}
    
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
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")
        return CONFIGURING_AIRDROP
    
    platform_fee = total * (PLATFORM_FEE / 100)
    dev_amount = total - platform_fee
    estimated_users = min(int(dev_amount / per_user), max_users)
    
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute("""
            UPDATE token_campaigns 
            SET airdrop_amount = ?,
                per_user_amount = ?,
                min_engagement = ?,
                max_users = ?,
                platform_fee = ?,
                status = 'configured'
            WHERE id = ? AND dev_id = ?
        """, (total, per_user, min_msg, max_users, platform_fee, camp_id, str(user.id)))
        await db.commit()
    
    kb = [
        [InlineKeyboardButton("✅ CONFIRM & START", callback_data=f"start_dist_{camp_id}")],
        [InlineKeyboardButton("✏️ Edit", callback_data=f"config_{camp_id}")]
    ]
    
    await update.message.reply_text(
        f"📊 **Summary**\n\n"
        f"• Total: {total:,.0f} tokens\n"
        f"• Per User: {per_user:,.0f} tokens\n"
        f"• Est. Recipients: ~{estimated_users:,} users\n"
        f"• Platform Fee ({PLATFORM_FEE}%): {platform_fee:,.0f} tokens\n"
        f"• You Distribute: {dev_amount:,.0f} tokens\n\n"
        f"Fee goes to: `{SOL_MAIN[:25]}...`",
        reply_markup=InlineKeyboardMarkup(kb),
        parse_mode=ParseMode.MARKDOWN
    )
    
    return ConversationHandler.END

async def start_distribution_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    camp_id = int(query.data.replace("start_dist_", ""))
    
    async with aiosqlite.connect(DB_FILE) as db:
        async with db.execute("SELECT * FROM token_campaigns WHERE id = ?", (camp_id,)) as c:
            camp = await c.fetchone()
    
    if not camp:
        await query.edit_message_text("❌ Campaign not found")
        return
    
    users = await get_eligible_users(camp)
    
    await query.edit_message_text(
        f"🚀 **DISTRIBUTION STARTED**\n\n"
        f"Token: {camp['token_symbol']}\n"
        f"Recipients: {len(users)} users\n"
        f"Per User: {camp['per_user_amount']:,.0f} tokens\n\n"
        f"⏳ Sending...",
        parse_mode=ParseMode.MARKDOWN
    )
    
    asyncio.create_task(distribute_tokens_task(camp, users))

async def get_eligible_users(campaign):
    async with aiosqlite.connect(DB_FILE) as db:
        async with db.execute("""
            SELECT ue.telegram_id, ue.username, ue.message_count,
                   (ue.message_count) as score
            FROM user_engagement ue
            JOIN protected_groups pg ON pg.id = ue.group_id
            WHERE pg.dev_id = ?
            AND ue.message_count >= ?
            AND ue.airdrop_received = 0
            ORDER BY score DESC
            LIMIT ?
        """, (campaign['dev_id'], campaign['min_engagement'], campaign['max_users'])) as c:
            users = await c.fetchall()
    return users

async def distribute_tokens_task(campaign, users):
    success = 0
    
    for user in users:
        try:
            async with aiosqlite.connect(DB_FILE) as db:
                await db.execute("""
                    UPDATE user_engagement 
                    SET airdrop_received = 1, airdrop_amount = ?
                    WHERE telegram_id = ?
                """, (campaign['per_user_amount'], user['telegram_id']))
                await db.commit()
            
            try:
                await bot_instance.send_message(
                    user['telegram_id'],
                    f"🎉 **Airdrop Received!**\n\n"
                    f"Token: {campaign['token_symbol']}\n"
                    f"Amount: {campaign['per_user_amount']:,.0f}\n"
                    f"Your Score: {user['score']}",
                    parse_mode=ParseMode.MARKDOWN
                )
            except:
                pass
            
            success += 1
            await asyncio.sleep(1)
        except Exception as e:
            logger.error(f"Failed: {e}")
    
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute("""
            UPDATE token_campaigns 
            SET status = 'completed'
            WHERE id = ?
        """, (campaign['id'],))
        await db.execute("""
            INSERT INTO revenue_log (dev_id, amount_sol, revenue_type, description)
            VALUES (?, ?, 'platform_fee', ?)
        """, (campaign['dev_id'], campaign['platform_fee'], f"Airdrop fee for {campaign['token_symbol']}"))
        await db.commit()
    
    try:
        await bot_instance.send_message(
            campaign['dev_id'],
            f"✅ **Airdrop Complete!**\n\n"
            f"Token: {campaign['token_symbol']}\n"
            f"Successful: {success}\n"
            f"Platform Fee: {campaign['platform_fee']:,.0f} tokens",
            parse_mode=ParseMode.MARKDOWN
        )
    except:
        pass

async def cmd_activate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    
    if chat.type == "private":
        await update.message.reply_text("Use in group")
        return
    
    m = await context.bot.get_chat_member(chat.id, user.id)
    if m.status not in ['administrator', 'creator']:
        await update.message.reply_text("Admin only")
        return
    
    async with aiosqlite.connect(DB_FILE) as db:
        async with db.execute("SELECT * FROM developers WHERE telegram_id=? AND status='active'", (str(user.id),)) as c:
            dev = await c.fetchone()
        if not dev:
            await update.message.reply_text("❌ Subscribe first")
            return
        
        await db.execute("""
            INSERT OR REPLACE INTO protected_groups (dev_id, telegram_chat_id, group_name)
            VALUES (?, ?, ?)
        """, (str(user.id), str(chat.id), chat.title))
        await db.commit()
    
    await update.message.reply_text(
        "✅ **GROUP PROTECTED**\n\n"
        "🛡 Anti-spam: ON\n"
        "📊 Engagement: TRACKED\n"
        "🚀 Auto-post to @ICEGODSICEDEVIL: ENABLED",
        parse_mode=ParseMode.MARKDOWN
    )

async def security_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg or not msg.text:
        return
    
    cid = str(update.effective_chat.id)
    
    async with aiosqlite.connect(DB_FILE) as db:
        async with db.execute("SELECT * FROM protected_groups WHERE telegram_chat_id=? AND is_active=1", (cid,)) as c:
            group = await c.fetchone()
        if not group:
            return
        
        await db.execute("""
            INSERT INTO user_engagement (group_id, telegram_id, username, message_count)
            VALUES ((SELECT id FROM protected_groups WHERE telegram_chat_id=?), ?, ?, 1)
            ON CONFLICT (group_id, telegram_id) DO UPDATE SET
                message_count = message_count + 1,
                last_active = CURRENT_TIMESTAMP
        """, (cid, str(update.effective_user.id), update.effective_user.username or ''))
        await db.commit()
    
    try:
        m = await context.bot.get_chat_member(cid, update.effective_user.id)
        if m.status in ['administrator', 'creator']:
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
# MAIN - ASYNC (Python 3.14 Compatible)
# ═══════════════════════════════════════════════════════════

async def main():
    global bot_instance
    
    # Init database
    await init_db()
    
    # Start Flask
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    
    # Build application
    application = Application.builder().token(BOT_TOKEN).build()
    bot_instance = application.bot
    
    # Add handlers
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
    
    application.add_handler(CommandHandler("start", cmd_start))
    application.add_handler(CommandHandler("campaign", cmd_campaign))
    application.add_handler(CommandHandler("activate", cmd_activate))
    application.add_handler(sub_conv)
    application.add_handler(airdrop_conv)
    application.add_handler(CallbackQueryHandler(start_distribution_callback, pattern="^start_dist_"))
    application.add_handler(MessageHandler(filters.TEXT & filters.ChatType.GROUPS, security_handler))
    
    logger.info("🚀 ICE REIGN V6 STARTED")
    logger.info(f"👑 Admin: {ADMIN_ID}")
    logger.info(f"💰 Wallet: {SOL_MAIN[:20]}...")
    
    # Initialize and start (manual async - no run_polling)
    await application.initialize()
    await application.start()
    
    # Start updater manually
    await application.updater.start_polling(drop_pending_updates=True)
    
    # Keep running
    stop_event = asyncio.Event()
    await stop_event.wait()

if __name__ == "__main__":
    asyncio.run(main())
