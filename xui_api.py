"""Модуль для работы с XUI API"""
import logging
import aiohttp
import json
import uuid
import random
import secrets
from datetime import datetime, timedelta
from config import XUI_API, XUI_USER, XUI_PASS
from database import user_exists, save_user

# Глобальная переменная для cookie
xui_cookie = None


async def get_xui_cookie():
    """Авторизация в XUI панели и получение cookie"""
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


async def get_users():
    """Получение списка пользователей из XUI панели"""
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


async def get_new_reality_keys():
    """Получение новых ключей для Reality"""
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


async def get_free_port():
    """Получение свободного порта"""
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


async def create_trial_inbound(telegram_id: int):
    """
    Создает пробную подписку для пользователя.
    Проверяет, не существует ли уже подписка для этого telegram_id.
    """
    global xui_cookie
    
    # Проверяем, существует ли уже пользователь
    if await user_exists(telegram_id):
        logging.warning(f"⚠️ Пользователь {telegram_id} уже имеет пробную подписку")
        return {"error": "already_exists"}
    
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
    email = str(telegram_id)
    # Короткий идентификатор для пользователя/подписки
    short_id = secrets.token_hex(3)
    port = await get_free_port()
    
    if not port:
        logging.error("❌ Не удалось найти свободный порт")
        return None
    
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
                "shortIds": [short_id],
                "settings": {
                    "publicKey": public_key,
                    "fingerprint": "firefox",
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
                # Сохраняем пользователя в базу данных
                await save_user(
                    telegram_id=telegram_id,
                    uuid=client_uuid,
                    email=email,
                    port=payload["port"],
                    public_key=public_key,
                    expiry_time=expiry,
                    short_id=short_id,
                )
                return {
                    "uuid": client_uuid,
                    "publicKey": public_key,
                    "port": payload["port"],
                    "short_id": short_id,
                }
            return None
