import os
import time
import json
import requests
from web3 import Web3
from dotenv import load_dotenv

load_dotenv("config.env")

# Load env variables
PRIVATE_KEY = os.getenv("PRIVATE_KEY")
SAFE_ADDRESS = os.getenv("SAFE_ADDRESS")
WATCH_ADDRESS = os.getenv("WATCH_ADDRESS")
RPC_URL = os.getenv("RPC_URL")
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

w3 = Web3(Web3.HTTPProvider(RPC_URL))
account = w3.eth.account.from_key(PRIVATE_KEY)

def send_telegram(message):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": message
    }
    try:
        requests.post(url, data=payload)
    except:
        pass

def sweep_funds():
    try:
        balance = w3.eth.get_balance(WATCH_ADDRESS)
        if balance > 0:
            gas_price = w3.eth.gas_price
            nonce = w3.eth.get_transaction_count(account.address)

            tx = {
                'to': SAFE_ADDRESS,
                'value': balance - (gas_price * 21000),
                'gas': 21000,
                'gasPrice': gas_price,
                'nonce': nonce,
                'chainId': w3.eth.chain_id
            }

            signed_tx = w3.eth.account.sign_transaction(tx, PRIVATE_KEY)
            tx_hash = w3.eth.send_raw_transaction(signed_tx.rawTransaction)
            send_telegram(f"[✅] Funds swept!\nHash: {tx_hash.hex()}")
        else:
            print("No balance yet.")
    except Exception as e:
        send_telegram(f"[⚠️] Error: {str(e)}")

if __name__ == "__main__":
    send_telegram("🛡️ Mex Auto-Sweeper Started.")
    while True:
        sweep_funds()
        time.sleep(5)
