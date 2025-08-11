
import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).parent
load_dotenv(BASE_DIR / ".env", override=True) 

class Config:
    TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
    ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")
    ADMIN_USERNAME = os.getenv("ADMIN_USERNAME")
    GIGACHAT_AUTH_KEY = os.getenv("GIGACHAT_AUTH_KEY")
    GIGACHAT_SCOPE = os.getenv("GIGACHAT_SCOPE", "GIGACHAT_API_PERS")
    SSL_CERT_PATH = BASE_DIR / "certs" / "russian_trusted_root_ca.cer"
    MEANINGS_PATH = BASE_DIR / "data" / "card_meanings.json"
    DB_PATH = BASE_DIR / "database" / "tarotbot.db"
    WELCOME_IMAGE_URL = "https://postimg.cc/SXqjBSWY"

    @classmethod
    def validate(cls):
        if not cls.TELEGRAM_TOKEN:
            raise ValueError("TELEGRAM_TOKEN не задан в .env файле")
        if not cls.ADMIN_CHAT_ID:
            raise ValueError("ADMIN_CHAT_ID не задан в .env файле")
        if not cls.GIGACHAT_AUTH_KEY:
            raise ValueError("GIGACHAT_AUTH_KEY не задан в .env файле")

Config.validate()