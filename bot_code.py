import asyncio
import aiogram
import logging
from aiogram import Bot, Dispatcher, F, types
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web
import aiohttp
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
import json
import uuid
import base64
from io import BytesIO
from datetime import datetime, timedelta
import random

API_TOKEN = "8290944633:AAG9FTaFvpkJiTF89N9u-WhW_puypYIqf30"
WEBHOOK_URL = "https://v460023.hosted-by-vdsina.com/webhook"
WEBAPP_HOST = "127.0.0.1"
WEBAPP_PORT = 8443

XUI_API = "https://109.234.34.215:33465/7HWmi6anA3YCrCOtWf"
XUI_USER = "Gena"
XUI_PASS = "Tranzisto1"

bot = Bot(token=API_TOKEN)
dp = Dispatcher()

# глобальная переменная для cookie
xui_cookie = None


# 🔹 Авторизация
async def get_xui_cookie():
    global xui_cookie
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{XUI_API}/login",
                json={"username": XUI_USER, "password": XUI_PASS},
                ssl=False,
                headers={"Content-Type": "application/json"}
            ) as resp:
                text = await resp.text()
                logging.info(f"Ответ /login: {text}")

                # Получаем cookie вручную
                set_cookie = resp.headers.get("Set-Cookie")
                if set_cookie:
                    cookie_value = set_cookie.split(";")[0]  # только "3x-ui=...."
                    xui_cookie = cookie_value
                    logging.info(f"✅ Cookie сохранена: {xui_cookie}")
                else:
                    logging.error("❌ Сервер не вернул Set-Cookie!")
                    xui_cookie = None
    except Exception as e:
        logging.error(f"❌ Ошибка при логине: {e}")
        xui_cookie = None


# 🔹 Получение списка пользователей
async def get_users():
    global xui_cookie
    if not xui_cookie:
        logging.error("❌ Нет cookie для запроса")
        return None

    headers = {
        "Content-Type": "application/json",
        "Cookie": xui_cookie
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{XUI_API}/panel/api/inbounds/list",
                ssl=False,
                headers=headers
            ) as resp:
                text = await resp.text()
                logging.info(f"📥 Ответ /panel/api/inbounds/list: {text}")
                try:
                    data = await resp.json(content_type=None)
                    return data
                except Exception:
                    return {"raw": text}
    except Exception as e:
        logging.error(f"❌ Ошибка при получении пользователей: {e}")
        return None

# получение ключей для reality 

async def get_new_reality_keys():
    global xui_cookie
    if not xui_cookie:
        await get_xui_cookie()  # логинимся, если cookie нет

    headers = {
        "Content-Type": "application/json",
        "Cookie": xui_cookie
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{XUI_API}/panel/api/server/getNewX25519Cert",
                headers=headers,
                ssl=False
            ) as resp:
                text = await resp.text()
                logging.info(f"📥 Ответ getNewX25519Cert: {text}")
                try:
                    data = await resp.json(content_type=None)
                    return data
                except Exception:
                    return {"raw": text}
    except Exception as e:
        logging.error(f"❌ Ошибка при запросе Reality-ключей: {e}")
        return None


# 🔹 Получение свободного порта
async def get_free_port():
    global xui_cookie
    if not xui_cookie:
        await get_xui_cookie()

    headers = {
        "Content-Type": "application/json",
        "Cookie": xui_cookie
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{XUI_API}/panel/api/inbounds/list",
                headers=headers,
                ssl=False
            ) as resp:
                data = await resp.json(content_type=None)

                # собираем уже занятые порты
                used_ports = {int(i["port"]) for i in data.get("obj", []) if "port" in i}

                # ищем свободный порт в диапазоне
                for _ in range(1000):
                    port = random.randint(10000, 65000)
                    if port not in used_ports:
                        return port

                logging.error("❌ Не удалось найти свободный порт")
                return None
    except Exception as e:
        logging.error(f"❌ Ошибка при получении свободного порта: {e}")
        return None


# создание пробной подписки 

async def create_trial_inbound():
    global xui_cookie
    if not xui_cookie:
        await get_xui_cookie()

    # Генерируем Reality ключи
    keys = await get_new_reality_keys()
    if not keys or "obj" not in keys:
        logging.error("❌ Не удалось получить Reality ключи.")
        return None

    private_key = keys["obj"]["privateKey"]
    public_key = keys["obj"]["publicKey"]

    expiry = int((datetime.now() + timedelta(days=3)).timestamp() * 1000)
    client_uuid = str(uuid.uuid4())
    email = f"trial_{int(datetime.now().timestamp())}"
    port = get_free_port()
    
    payload = {
        "up": 0,
        "down": 0,
        "total": 0,
        "remark": email,
        "enable": True,
        "expiryTime": expiry,
        "listen": "",
        "port": port,  
        "protocol": "vless",
        "settings": json.dumps({
            "clients": [
                {
                    "id": client_uuid,
                    "flow": "",
                    "email": email,
                    "limitIp": 0,
                    "totalGB": 0,
                    "expiryTime": expiry,
                    "enable": True,
                    "tgId": "",
                    "subId": "trial_" + email[-6:],
                    "comment": "",
                    "reset": 0
                }
            ],
            "decryption": "none",
            "encryption": "none"
        }),
        "streamSettings": json.dumps({
            "network": "tcp",
            "security": "reality",
            "externalProxy": [],
            "realitySettings": {
                "show": False,
                "xver": 0,
                "target": "google.com:443",
                "serverNames": ["google.com", "www.google.com"],
                "privateKey": private_key,
                "shortIds": ["32a221", "2f835f2b62"],
                "settings": {
                    "publicKey": public_key,
                    "fingerprint": "chrome",
                    "spiderX": "/"
                }
            },
            "tcpSettings": {
                "acceptProxyProtocol": False,
                "header": {"type": "none"}
            }
        }),
        "sniffing": json.dumps({
            "enabled": False,
            "destOverride": ["http", "tls", "quic", "fakedns"],
            "metadataOnly": False,
            "routeOnly": False
        })
    }

    headers = {
        "Content-Type": "application/json",
        "Cookie": xui_cookie
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(
            f"{XUI_API}/panel/api/inbounds/add",
            headers=headers,
            json=payload,
            ssl=False
        ) as resp:
            text = await resp.text()
            logging.info(f"📤 Ответ /inbounds/add: {text}")
            data = await resp.json(content_type=None)
            if data.get("success"):
                return {
                    "uuid": client_uuid,
                    "publicKey": public_key,
                    "port": payload["port"]
                }
            return None



# 🔹 Команда /users
@dp.message(F.text == "/users")
async def users_handler(message: types.Message):
    users = await get_users()
    if not users:
        await message.answer("❌ Не удалось получить список пользователей.")
        return

    if "raw" in users:
        await message.answer("⚠️ Ответ не JSON:\n" + users["raw"][:3000])
        return

    reply_text = "📋 Список пользователей:\n\n"
    if "obj" in users:
        for user in users["obj"]:
            remark = user.get("remark", "—")
            enable = "✅" if user.get("enable") else "❌"
            reply_text += f"{enable} {remark}\n"
    else:
        reply_text += str(users)

    await message.answer(reply_text)


main_menu = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="📋 Список пользователей")],
        [KeyboardButton(text="ℹ️ Помощь"), KeyboardButton(text="🚀 Пробная подписка")]
    ],
    resize_keyboard=True  # подгоняет размер под экран
)

# 🔹 Команда /start с меню
@dp.message(F.text == "/start")
async def start_handler(message: types.Message):
    await message.answer(
        "👋 Привет! Я помогу тебе управлять VPN.\n\nВыбери действие ниже:",
        reply_markup=main_menu
    )
    
@dp.message(F.text == "📋 Список пользователей")
async def show_users_button(message: types.Message):
    await message.answer("Загружаю список пользователей...")
    users = await get_users()
    if not users:
        await message.answer("❌ Не удалось получить список пользователей.")
        return

    if "raw" in users:
        await message.answer("⚠️ Ответ не JSON:\n" + users["raw"][:3000])
        return

    reply_text = "📋 Список пользователей:\n\n"
    if "obj" in users:
        for user in users["obj"]:
            remark = user.get("remark", "—")
            enable = "✅" if user.get("enable") else "❌"
            reply_text += f"{enable} {remark}\n"
    else:
        reply_text += str(users)

    await message.answer(reply_text)

@dp.message(F.text == "ℹ️ Помощь")
async def help_button(message: types.Message):
    await message.answer("ℹ️ Здесь будет помощь и инструкции.")

@dp.message(F.text == "🚀 Пробная подписка")
async def trial_button(message: types.Message):

    result = await create_trial_inbound()
    if not result:
        await message.answer("❌ Не удалось создать пробную подписку.")
        return

    # ✅ Собираем ссылку для подключения
    domain = "109.234.34.215"  # или твой домен (например vpn.example.com)
    uuid = result["uuid"]
    pbk = result["publicKey"]
    port = result["port"]

    link = (
        f"vless://{uuid}@{domain}:{port}"
        f"?encryption=none&security=reality&fp=chrome"
        f"&pbk={pbk}&sid=32a221&sni=google.com#Trial"
    )

    await message.answer(
        "✅ Пробная подписка создана!\n\n"
        "Срок действия: *3 дня*\n\n"
        f"🔗 Ссылка для подключения:\n`{link}`",
        parse_mode="Markdown"
    )




# 🔹 Жизненный цикл
async def on_startup(app: web.Application):
    await bot.set_webhook(WEBHOOK_URL)
    await get_xui_cookie()  # логинимся при старте


async def on_shutdown(app: web.Application):
    await bot.delete_webhook()


def main():
    logging.basicConfig(level=logging.INFO)
    app = web.Application()
    SimpleRequestHandler(dp, bot).register(app, path="/webhook")
    app.on_startup.append(on_startup)
    app.on_shutdown.append(on_shutdown)
    setup_application(app, dp, bot=bot)
    web.run_app(app, host=WEBAPP_HOST, port=WEBAPP_PORT)


if __name__ == "__main__":
    main()
