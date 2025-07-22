import os
import time
import requests
from web3 import Web3
from dotenv import load_dotenv

load_dotenv("config.env")

SAFE_ADDRESS = os.getenv("SAFE_ADDRESS")
WATCH_ADDRESS = os.getenv("WATCH_ADDRESS")
PRIVATE_KEY = os.getenv("PRIVATE_KEY")
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

w3 = Web3(Web3.HTTPProvider("https://rpc.ankr.com/eth"))

def send_telegram_alert(msg):
    requests.post(
        f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
        json={"chat_id": CHAT_ID, "text": msg}
    )

def get_balance(address):
    return w3.eth.get_balance(address)

def sweep_eth():
    bal = get_balance(WATCH_ADDRESS)
    if bal > 0:
        nonce = w3.eth.get_transaction_count(WATCH_ADDRESS)
        tx = {
            "to": SAFE_ADDRESS,
            "value": bal - w3.to_wei(0.0002, "ether"),
            "gas": 21000,
            "gasPrice": w3.to_wei("20", "gwei"),
            "nonce": nonce,
            "chainId": 1
        }
        signed = w3.eth.account.sign_transaction(tx, PRIVATE_KEY)
        tx_hash = w3.eth.send_raw_transaction(signed.rawTransaction)
        send_telegram_alert("✅ ETH swept! TX=" + w3.to_hex(tx_hash))
    else:
        print("🕵️ No ETH to sweep.")

while True:
    sweep_eth()
    time.sleep(10)
