"""Конфигурация бота - загрузка переменных окружения из .env"""
import os
from dotenv import load_dotenv

# Загружаем переменные из .env файла
load_dotenv()

# Telegram Bot Configuration
API_TOKEN = os.getenv("API_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
WEBAPP_HOST = os.getenv("WEBAPP_HOST", "127.0.0.1")
WEBAPP_PORT = int(os.getenv("WEBAPP_PORT", "8443"))

# XUI Panel Configuration
XUI_API = os.getenv("XUI_API")
XUI_USER = os.getenv("XUI_USER")
XUI_PASS = os.getenv("XUI_PASS")

# VPN Server Configuration
VPN_DOMAIN = os.getenv("VPN_DOMAIN")

# Frontend Domain (для коротких ссылок без IP)
FRONT_DOMAIN = os.getenv("FRONT_DOMAIN", "proxima-test.duckdns.org")

# Database Configuration
DB_PATH = os.getenv("DB_PATH", "vpn_bot.db")

# Проверка обязательных переменных
required_vars = {
    "API_TOKEN": API_TOKEN,
    "WEBHOOK_URL": WEBHOOK_URL,
    "XUI_API": XUI_API,
    "XUI_USER": XUI_USER,
    "XUI_PASS": XUI_PASS,
    "VPN_DOMAIN": VPN_DOMAIN,
}

missing_vars = [var for var, value in required_vars.items() if not value]
if missing_vars:
    raise ValueError(f"Отсутствуют обязательные переменные окружения: {', '.join(missing_vars)}")

