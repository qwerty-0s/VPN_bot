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

# YooKassa Payment Configuration
YOO_SHOP_ID = os.getenv("YOO_SHOP_ID")
YOO_SECRET_KEY = os.getenv("YOO_SECRET_KEY")

# Tariff Matrix: (months, devices) -> price_in_rubles
# Сетка тарифов: (месяцы, количество устройств) -> цена в рублях
TARIFFS = {
    # 1 месяц
    (1, 1): {"price": 150, "days": 30, "devices": 1},
    (1, 3): {"price": 200, "days": 30, "devices": 3},
    (1, 5): {"price": 250, "days": 30, "devices": 5},
    
    # 3 месяца
    (3, 1): {"price": 400, "days": 90, "devices": 1},
    (3, 3): {"price": 500, "days": 90, "devices": 3},
    (3, 5): {"price": 600, "days": 90, "devices": 5},
    
    # 6 месяцев
    (6, 1): {"price": 700, "days": 180, "devices": 1},
    (6, 3): {"price": 850, "days": 180, "devices": 3},
    (6, 5): {"price": 1000, "days": 180, "devices": 5},
}

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

