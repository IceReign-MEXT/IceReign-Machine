#!/usr/bin/env python3
"""
ICE REIGN MACHINE V5
"""

import os
import asyncio
import logging
import threading
import aiosqlite
from datetime import datetime, timedelta

from flask import Flask, jsonify
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode, ChatMemberStatus
from telegram.ext import (
    Application, CommandHandler, ContextTypes, MessageHandler, 
    filters, CallbackQueryHandler, ConversationHandler
)
import aiohttp
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = os.getenv("ADMIN_ID")
SOL_MAIN = os.getenv("SOL_MAIN")
PORT = int(os.getenv("PORT", 8080))
SUBSCRIPTION_PRICE = float(os.getenv("SUBSCRIPTION_PRICE", 100))
HELIUS_API_KEY = os.getenv("SOLANA_RPC", "").split("api-key=")[1] if "api-key=" in os.getenv("SOLANA_RPC", "") else ""

DB_FILE = "ice_reign.db"
AWAITING_PAYMENT = 1

flask_app = Flask(__name__)

@flask_app.route("/")
def health():
    return jsonify({"status": "ICE REIGN ONLINE", "wallet": SOL_MAIN, "time": datetime.utcnow().isoformat()}), 200

def run_flask():
    flask_app.run(host='0.0.0.0', port=PORT, threaded=True)

async def init_db():
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute("CREATE TABLE IF NOT EXISTS dev_subscriptions (id INTEGER PRIMARY KEY, telegram_id TEXT UNIQUE, username TEXT, tier TEXT, status TEXT, subscription_end TIMESTAMP)")
        await db.execute("CREATE TABLE IF NOT EXISTS platform_payments (id INTEGER PRIMARY KEY, dev_telegram_id TEXT, amount_sol REAL, tx_signature TEXT)")
        await db.execute("CREATE TABLE IF NOT EXISTS protected_groups (id INTEGER PRIMARY KEY, dev_telegram_id TEXT, telegram_chat_id TEXT UNIQUE, group_name TEXT, is_active INTEGER DEFAULT 1)")
        await db.commit()

async def verify_payment(tx, amount):
    try:
        async with aiohttp.ClientSession() as s:
            url = f"https://api.helius.xyz/v0/transactions/?api-key={HELIUS_API_KEY}"
            async with s.post(url, json={"transactions": [tx]}) as r:
                if r.status != 200: return False
                data = await r.json()
                if not data or data[0].get('err'): return False
                for t in data[0].get('nativeTransfers', []):
                    if t['toUserAccount'] == SOL_MAIN and float(t['amount'])/1e9 >= amount*0.95:
                        return True
        return False
    except: return False

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if update.effective_chat.type != "private": return
    if str(user.id) == ADMIN_ID:
        async with aiosqlite.connect(DB_FILE) as db:
            async with db.execute("SELECT SUM(amount_sol) FROM platform_payments") as c: 
                total = (await c.fetchone())[0] or 0
        await update.message.reply_text(f"👑 ADMIN\nRevenue: {total:.4f} SOL\n`{SOL_MAIN}`", parse_mode=ParseMode.MARKDOWN)
        return
    async with aiosqlite.connect(DB_FILE) as db:
        async with db.execute("SELECT * FROM dev_subscriptions WHERE telegram_id=?", (str(user.id),)) as c:
            dev = await c.fetchone()
    if dev and dev[4] == 'active':
        await update.message.reply_text(f"👨‍💻 DASHBOARD\nTier: {dev[3]}\nExpires: {dev[5]}\n/activate - Add to group", parse_mode=ParseMode.MARKDOWN)
    else:
        kb = [[InlineKeyboardButton(f"💎 Basic - {SUBSCRIPTION_PRICE} SOL", callback_data="sub_basic")], [InlineKeyboardButton("👑 Pro - 3 SOL", callback_data="sub_pro")]]
        await update.message.reply_text(f"🚀 ICE REIGN\nAuto-detect + Anti-spam\n\nPay: `{SOL_MAIN}`", reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.MARKDOWN)

async def sub_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    tier = q.data.replace("sub_", "")
    amt = SUBSCRIPTION_PRICE if tier == "basic" else 3.0
    context.user_data['pay'] = {'tier': tier, 'amt': amt}
    await q.edit_message_text(f"💳 {tier.upper()}\nSend {amt} SOL to:\n`{SOL_MAIN}`\n\nReply with TX:", parse_mode=ParseMode.MARKDOWN)
    return AWAITING_PAYMENT

async def proc_pay(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tx = update.message.text.strip()
    user = update.effective_user
    pay = context.user_data.get('pay')
    if not pay: 
        await update.message.reply_text("Use /start")
        return ConversationHandler.END
    await update.message.reply_text("⏳ Verifying...")
    if await verify_payment(tx, pay['amt']):
        exp = datetime.now() + timedelta(days=30)
        async with aiosqlite.connect(DB_FILE) as db:
            await db.execute("INSERT OR REPLACE INTO dev_subscriptions (telegram_id,username,tier,status,subscription_end) VALUES (?,?,?, 'active',?)", (str(user.id), user.username, pay['tier'], exp))
            await db.execute("INSERT INTO platform_payments (dev_telegram_id,amount_sol,tx_signature) VALUES (?,?,?)", (str(user.id), pay['amt'], tx))
            await db.commit()
        await update.message.reply_text(f"✅ ACTIVATED!\nTier: {pay['tier']}\nExpires: {exp.strftime('%Y-%m-%d')}\n\nAdd to group: /activate", parse_mode=ParseMode.MARKDOWN)
        await context.bot.send_message(ADMIN_ID, f"💰 {pay['amt']} SOL from @{user.username}")
    else:
        await update.message.reply_text("❌ Payment not found")
    return ConversationHandler.END

async def activate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    if chat.type == "private": return await update.message.reply_text("Use in group")
    m = await context.bot.get_chat_member(chat.id, user.id)
    if m.status not in [ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER]: return await update.message.reply_text("Admin only")
    async with aiosqlite.connect(DB_FILE) as db:
        async with db.execute("SELECT * FROM dev_subscriptions WHERE telegram_id=? AND status='active'", (str(user.id),)) as c:
            if not await c.fetchone(): return await update.message.reply_text("❌ Subscribe first")
        await db.execute("INSERT OR REPLACE INTO protected_groups (dev_telegram_id,telegram_chat_id,group_name) VALUES (?,?,?)", (str(user.id), str(chat.id), chat.title))
        await db.commit()
    await update.message.reply_text("✅ GROUP PROTECTED\n🛡 Anti-spam: ON\n🚀 Auto-detect: READY", parse_mode=ParseMode.MARKDOWN)

async def security(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg or not msg.text: return
    cid = str(update.effective_chat.id)
    async with aiosqlite.connect(DB_FILE) as db:
        async with db.execute("SELECT * FROM protected_groups WHERE telegram_chat_id=? AND is_active=1", (cid,)) as c:
            if not await c.fetchone(): return
    try:
        m = await context.bot.get_chat_member(cid, update.effective_user.id)
        if m.status in [ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER]: return
    except: return
    if sum(1 for s in ['dm me','http','t.me/','investment'] if s in msg.text.lower()) >= 2:
        try: 
            await msg.delete()
            w = await context.bot.send_message(cid, "🛡 Spam removed", parse_mode=ParseMode.MARKDOWN)
            await asyncio.sleep(5)
            await w.delete()
        except: pass

async def main():
    await init_db()
    
    # Start Flask in background
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    logger.info(f"🌐 Web server on port {PORT}")
    
    # Build application
    app = Application.builder().token(BOT_TOKEN).build()
    
    # Add handlers
    conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(sub_cb, pattern="^sub_")],
        states={AWAITING_PAYMENT: [MessageHandler(filters.TEXT & ~filters.COMMAND, proc_pay)]},
        fallbacks=[],
        per_message=False
    )
    app.add_handler(CommandHandler("start", start))
    app.add_handler(conv)
    app.add_handler(CommandHandler("activate", activate))
    app.add_handler(MessageHandler(filters.TEXT & filters.ChatType.GROUPS, security))
    
    logger.info("🚀 BOT STARTED")
    logger.info(f"💰 Revenue wallet: {SOL_MAIN}")
    
    # Start bot with proper signal handling disabled for Render
    await app.initialize()
    await app.start()
    
    # Start polling without stop signals (Render handles this)
    await app.updater.start_polling(drop_pending_updates=True)
    
    # Keep running
    stop_event = asyncio.Event()
    await stop_event.wait()

if __name__ == "__main__":
    asyncio.run(main())
