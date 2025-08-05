from dotenv import load_dotenv
import os

load_dotenv()  # Make sure this is at the top of your script

PRIVATE_KEY = os.getenv("PRIVATE_KEY")
SAFE_ADDRESS = os.getenv("SAFE_ADDRESS")
WATCH_ADDRESS = os.getenv("WATCH_ADDRESS")
RPC_URL = os.getenv("RPC_URL")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
