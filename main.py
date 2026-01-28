import os
import asyncio
import threading
import random
import asyncpg
from flask import Flask
from dotenv import load_dotenv

load_dotenv()

# --- CONFIG ---
DATABASE_URL = os.getenv("DATABASE_URL")
ADMIN_ID = os.getenv("ADMIN_ID")

# --- FLASK SERVER (For Dashboard API & Render Health) ---
flask_app = Flask(__name__)
@flask_app.route('/')
def health(): return "ICEREIGN MACHINE: PRINTING VOLUME 🟢", 200

def run_web():
    port = int(os.environ.get("PORT", 8080))
    flask_app.run(host="0.0.0.0", port=port)

# --- THE VOLUME ENGINE (Market Maker) ---
async def init_machine_db():
    conn = await asyncpg.connect(DATABASE_URL)
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS volume_stats (
            id SERIAL PRIMARY KEY,
            total_volume_usd NUMERIC DEFAULT 0,
            trades_executed INTEGER DEFAULT 0,
            last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    # Initialize row if empty
    res = await conn.fetchval("SELECT count(*) FROM volume_stats")
    if res == 0:
        await conn.execute("INSERT INTO volume_stats (total_volume_usd, trades_executed) VALUES (0, 0)")
    await conn.close()

async def market_maker_loop():
    """
    Simulates High-Frequency Trading Volume.
    In production, this triggers Jupiter/Raydium Swap instructions.
    """
    print("🚀 ICEREIGN MACHINE: Market Maker Engine Engaged.")
    while True:
        try:
            # Simulate a HFT trade event
            trade_vol = round(random.uniform(500, 5000), 2) # $500 - $5000 volume

            conn = await asyncpg.connect(DATABASE_URL)
            await conn.execute("""
                UPDATE volume_stats
                SET total_volume_usd = total_volume_usd + $1,
                    trades_executed = trades_executed + 1,
                    last_updated = CURRENT_TIMESTAMP
                WHERE id = 1
            """, trade_vol)

            print(f"📈 MACHINE: Executed Volume Trade: ${trade_vol}")
            await conn.close()

            # Machine speed: Executes every 60 seconds (Adjustable for Renters)
            await asyncio.sleep(60)
        except Exception as e:
            print(f"⚠️ Machine Error: {e}")
            await asyncio.sleep(10)

async def main():
    await init_machine_db()
    await market_maker_loop()

if __name__ == "__main__":
    # Start Web Interface
    threading.Thread(target=run_web, daemon=True).start()
    # Start Engine
    asyncio.run(main())
