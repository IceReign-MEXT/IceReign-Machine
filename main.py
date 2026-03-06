#!/usr/bin/env python3
"""
ICE REIGN MACHINE V6.1 - AIRDROP DISTRIBUTOR
Termux/Render Compatible (No Solders Dependency)
"""
import os, asyncio, logging, threading, aiosqlite, aiohttp
from datetime import datetime, timedelta
from typing import Optional, Dict
from flask import Flask, request, jsonify
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.constants import ParseMode, ChatMemberStatus
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters, CallbackQueryHandler, ConversationHandler
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# Config
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = os.getenv("ADMIN_ID")
SOL_MAIN = os.getenv("SOL_MAIN")
HELIUS_API_KEY = os.getenv("HELIUS_API_KEY")
PORT = int(os.getenv("PORT", 8080))
SUBSCRIPTION_PRICE = float(os.getenv("SUBSCRIPTION_PRICE", 0.5))
PRO_PRICE = float(os.getenv("PRO_PRICE", 3.0))
DB_FILE = "ice_reign.db"
AWAITING_PAYMENT = 1

# Flask App
flask_app = Flask(__name__)

@flask_app.route("/")
def health():
    return jsonify({"status": "ICE REIGN ONLINE", "version": "6.1.0", "wallet": SOL_MAIN, "time": datetime.utcnow().isoformat()}), 200

@flask_app.route("/webhook/helius", methods=["POST"])
def helius_webhook():
    logger.info(f"Webhook: {request.json}")
    return jsonify({"received": True}), 200

def run_flask():
    flask_app.run(host='0.0.0.0', port=PORT, threaded=True)

# Database
async def init_db():
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute("CREATE TABLE IF NOT EXISTS dev_subscriptions (id INTEGER PRIMARY KEY, telegram_id TEXT UNIQUE, username TEXT, tier TEXT DEFAULT 'none', status TEXT DEFAULT 'inactive', subscription_end TIMESTAMP)")
        await db.execute("CREATE TABLE IF NOT EXISTS platform_payments (id INTEGER PRIMARY KEY, dev_telegram_id TEXT, amount_sol REAL, tx_signature TEXT)")
        await db.execute("CREATE TABLE IF NOT EXISTS protected_groups (id INTEGER PRIMARY KEY, dev_telegram_id TEXT, telegram_chat_id TEXT UNIQUE, group_name TEXT, is_active INTEGER DEFAULT 1)")
        await db.execute("CREATE TABLE IF NOT EXISTS user_engagement (group_chat_id TEXT, telegram_id TEXT, message_count INTEGER DEFAULT 0, UNIQUE(group_chat_id, telegram_id))")
        await db.execute("CREATE TABLE IF NOT EXISTS user_wallets (telegram_id TEXT PRIMARY KEY, wallet_address TEXT)")
        await db.commit()
    logger.info("✅ Database ready")

# Solana Utils
async def verify_sol_payment(tx_sig: str, expected: float) -> bool:
    try:
        async with aiohttp.ClientSession() as s:
            url = f"https://api.helius.xyz/v0/transactions/?api-key={HELIUS_API_KEY}"
            async with s.post(url, json={"transactions": [tx_sig]}) as r:
                if r.status != 200: return False
                data = await r.json()
                if not data or data[0].get('err'): return False
                for t in data[0].get('nativeTransfers', []):
                    if t['toUserAccount'] == SOL_MAIN:
                        return float(t['amount'])/1e9 >= expected * 0.95
                return False
    except Exception as e:
        logger.error(f"Verify error: {e}")
        return False

# Helpers
async def get_dev_sub(telegram_id: int) -> Optional[Dict]:
    async with aiosqlite.connect(DB_FILE) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM dev_subscriptions WHERE telegram_id = ?", (str(telegram_id),)) as c:
            row = await c.fetchone()
            return dict(row) if row else None

async def get_wallet(telegram_id: int) -> Optional[str]:
    async with aiosqlite.connect(DB_FILE) as db:
        async with db.execute("SELECT wallet_address FROM user_wallets WHERE telegram_id = ?", (str(telegram_id),)) as c:
            row = await c.fetchone()
            return row[0] if row else None

async def get_revenue() -> float:
    async with aiosqlite.connect(DB_FILE) as db:
        async with db.execute("SELECT COALESCE(SUM(amount_sol), 0) FROM platform_payments") as c:
            return (await c.fetchone())[0]

# Handlers
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user, chat_type = update.effective_user, update.effective_chat.type
    if chat_type == "private":
        if str(user.id) == ADMIN_ID:
            await update.message.reply_text(f"👑 *ADMIN*\\nRevenue: `{await get_revenue():.4f}` SOL\\nWallet: `{SOL_MAIN}`", parse_mode=ParseMode.MARKDOWN)
            return
        dev = await get_dev_sub(user.id)
        if dev and dev['status'] == 'active':
            await update.message.reply_text(f"👨‍💻 *DASHBOARD*\\nTier: `{dev['tier'].upper()}`\\nExpires: `{dev['subscription_end']}`", parse_mode=ParseMode.MARKDOWN)
        else:
            keyboard = [[InlineKeyboardButton(f"💎 Basic - {SUBSCRIPTION_PRICE} SOL", callback_data="sub_basic")],
                        [InlineKeyboardButton(f"👑 Pro - {PRO_PRICE} SOL", callback_data="sub_pro")]]
            await update.message.reply_text("🚀 *ICE REIGN MACHINE*\\n\\nAuto-detect & distribute tokens", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)
    else:
        await update.message.reply_text("🛡 *Ice Reign Active*\\n/wallet - Register SOL\\n/airdrop - Check eligibility", parse_mode=ParseMode.MARKDOWN)

async def wallet_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) != 1: return await update.message.reply_text("💼 Usage: `/wallet ADDRESS`", parse_mode=ParseMode.MARKDOWN)
    wallet = context.args[0].strip()
    if len(wallet) < 32: return await update.message.reply_text("❌ Invalid address")
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute("INSERT INTO user_wallets VALUES (?, ?) ON CONFLICT(telegram_id) DO UPDATE SET wallet_address = excluded.wallet_address", (str(update.effective_user.id), wallet))
        await db.commit()
    await update.message.reply_text(f"✅ Wallet registered:\\n`{wallet}`", parse_mode=ParseMode.MARKDOWN)

async def airdrop_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    async with aiosqlite.connect(DB_FILE) as db:
        async with db.execute("SELECT message_count FROM user_engagement WHERE group_chat_id = ? AND telegram_id = ?", (chat_id, str(update.effective_user.id))) as c:
            row = await c.fetchone()
    await update.message.reply_text(f"📊 *Your Stats*\\nMessages: `{row[0] if row else 0}`\\n\\nKeep engaging!", parse_mode=ParseMode.MARKDOWN)

async def sub_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    tier = query.data.replace("sub_", "")
    amount = SUBSCRIPTION_PRICE if tier == "basic" else PRO_PRICE
    context.user_data['payment'] = {'tier': tier, 'amount': amount}
    await query.edit_message_text(f"💳 *{tier.upper()}*\\n\\nSend `{amount}` SOL to:\\n`{SOL_MAIN}`\\n\\nReply with TX:", parse_mode=ParseMode.MARKDOWN)
    return AWAITING_PAYMENT

async def process_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tx, user = update.message.text.strip(), update.effective_user
    payment = context.user_data.get('payment')
    if not payment: return await update.message.reply_text("Session expired") or ConversationHandler.END
    await update.message.reply_text("⏳ Verifying...")
    if await verify_sol_payment(tx, payment['amount']):
        expiry = datetime.now() + timedelta(days=30)
        async with aiosqlite.connect(DB_FILE) as db:
            await db.execute("INSERT INTO dev_subscriptions (telegram_id, username, tier, status, subscription_end) VALUES (?, ?, ?, 'active', ?) ON CONFLICT(telegram_id) DO UPDATE SET tier = excluded.tier, status = 'active', subscription_end = excluded.subscription_end", (str(user.id), user.username, payment['tier'], expiry))
            await db.execute("INSERT INTO platform_payments (dev_telegram_id, amount_sol, tx_signature) VALUES (?, ?, ?)", (str(user.id), payment['amount'], tx))
            await db.commit()
        await context.bot.send_message(ADMIN_ID, f"💰 {payment['amount']} SOL from @{user.username}")
        await update.message.reply_text(f"✅ *ACTIVATED!*\\nTier: `{payment['tier'].upper()}`\\nExpires: `{expiry.strftime('%Y-%m-%d')}`", parse_mode=ParseMode.MARKDOWN)
    else:
        await update.message.reply_text("❌ Payment not found")
    return ConversationHandler.END

async def activate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat, user = update.effective_chat, update.effective_user
    if chat.type == "private": return await update.message.reply_text("Use in group!")
    member = await context.bot.get_chat_member(chat.id, user.id)
    if member.status not in [ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER]: return await update.message.reply_text("❌ Admin only")
    dev = await get_dev_sub(user.id)
    if not dev or dev['status'] != 'active': return await update.message.reply_text("❌ Subscription required")
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute("INSERT INTO protected_groups (dev_telegram_id, telegram_chat_id, group_name, is_active) VALUES (?, ?, ?, 1) ON CONFLICT(telegram_chat_id) DO UPDATE SET is_active = 1", (str(user.id), str(chat.id), chat.title))
        await db.commit()
    await context.bot.set_my_commands([BotCommand("wallet", "Register SOL"), BotCommand("airdrop", "Check eligibility")], scope={"type": "chat", "chat_id": chat.id})
    await update.message.reply_text("✅ *GROUP PROTECTED*\\n🛡 Anti-spam: ON\\n🚀 Airdrop ready", parse_mode=ParseMode.MARKDOWN)

async def track_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg or not msg.text: return
    chat_id, user = str(update.effective_chat.id), update.effective_user
    try:
        if (await context.bot.get_chat_member(chat_id, user.id)).status in [ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER]: return
    except: return
    async with aiosqlite.connect(DB_FILE) as db:
        if not await (await db.execute("SELECT 1 FROM protected_groups WHERE telegram_chat_id = ? AND is_active = 1", (chat_id,))).fetchone(): return
        await db.execute("INSERT INTO user_engagement (group_chat_id, telegram_id, message_count) VALUES (?, ?, 1) ON CONFLICT(group_chat_id, telegram_id) DO UPDATE SET message_count = message_count + 1", (chat_id, str(user.id)))
        await db.commit()
    if sum(1 for k in ['dm me', 'http', 't.me/', 'investment'] if k in msg.text.lower()) >= 2:
        try: await msg.delete(); await (await context.bot.send_message(chat_id, "🛡 Spam removed")).delete()
        except: pass

# Main
def main():
    asyncio.run(init_db())
    threading.Thread(target=run_flask, daemon=True).start()
    logger.info(f"🌐 Web server on port {PORT}")
    app = Application.builder().token(BOT_TOKEN).build()
    conv = ConversationHandler(entry_points=[CallbackQueryHandler(sub_callback, pattern="^sub_")], states={AWAITING_PAYMENT: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_payment)]}, fallbacks=[])
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("wallet", wallet_cmd))
    app.add_handler(CommandHandler("airdrop", airdrop_cmd))
    app.add_handler(CommandHandler("activate", activate))
    app.add_handler(conv)
    app.add_handler(MessageHandler(filters.TEXT & filters.ChatType.GROUPS, track_msg))
    logger.info("🚀 BOT STARTED")
    app.run_polling()

if __name__ == "__main__":
    main()
