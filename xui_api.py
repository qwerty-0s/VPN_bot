"""Модуль для работы с XUI API"""
import logging
import aiohttp
import json
import uuid
import random
import secrets
import time
from datetime import datetime, timedelta
from config import XUI_API, XUI_USER, XUI_PASS
from database import user_exists, save_user, get_user_by_telegram_id

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
                # text = await resp.text() # Лог можно убрать для чистоты
                
                set_cookie = resp.headers.get("Set-Cookie")
                if set_cookie:
                    cookie_value = set_cookie.split(";")[0]
                    xui_cookie = cookie_value
                    logging.info(f"✅ Cookie обновлена")
                else:
                    logging.error("❌ Сервер не вернул Set-Cookie!")
                    xui_cookie = None
    except Exception as e:
        logging.error(f"❌ Ошибка при логине: {e}")
        xui_cookie = None


async def get_new_reality_keys():
    """Получение новых ключей для Reality"""
    global xui_cookie
    if not xui_cookie:
        await get_xui_cookie()

    headers = {"Content-Type": "application/json", "Cookie": xui_cookie}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{XUI_API}/panel/api/server/getNewX25519Cert",
                headers=headers, ssl=False
            ) as resp:
                return await resp.json(content_type=None)
    except Exception as e:
        logging.error(f"❌ Ошибка ключей: {e}")
        return None


async def get_free_port():
    """Получение свободного порта"""
    global xui_cookie
    if not xui_cookie:
        await get_xui_cookie()

    headers = {"Content-Type": "application/json", "Cookie": xui_cookie}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{XUI_API}/panel/api/inbounds/list",
                headers=headers, ssl=False
            ) as resp:
                data = await resp.json(content_type=None)
                used_ports = {int(i["port"]) for i in data.get("obj", []) if "port" in i}
                for _ in range(1000):
                    port = random.randint(10000, 65000)
                    if port not in used_ports:
                        return port
                return None
    except Exception:
        return None


async def create_trial_inbound(telegram_id: int):
    """Создает подписку (клиента) в панели"""
    global xui_cookie
    
    if await user_exists(telegram_id):
        return {"error": "already_exists"}
    
    if not xui_cookie:
        await get_xui_cookie()

    keys = await get_new_reality_keys()
    if not keys or "obj" not in keys:
        return None

    private_key = keys["obj"]["privateKey"]
    public_key = keys["obj"]["publicKey"]

    # По умолчанию создаем на 3 дня (триал)
    expiry = int((datetime.now() + timedelta(days=3)).timestamp() * 1000)
    client_uuid = str(uuid.uuid4())
    email = str(telegram_id)
    short_id = secrets.token_hex(3)
    port = await get_free_port()
    
    if not port:
        return None
    
    # Настройки JSON для inbound
    settings = {
        "clients": [{
            "id": client_uuid,
            "flow": "xtls-rprx-vision",
            "email": email,
            "limitIp": 1,
            "totalGB": 0,
            "expiryTime": expiry,
            "enable": True,
            "tgId": str(telegram_id),
            "subId": short_id
        }],
        "decryption": "none",
        "encryption": "none"
    }

    payload = {
        "up": 0, "down": 0, "total": 0,
        "remark": email,
        "enable": True,
        "expiryTime": expiry,
        "listen": "",
        "port": port,  
        "protocol": "vless",
        "settings": json.dumps(settings),
        "streamSettings": json.dumps({
            "network": "tcp",
            "security": "reality",
            "externalProxy": [],
            "realitySettings": {
                "show": False, "xver": 0,
                "target": "google.com:443",
                "serverNames": ["google.com", "www.google.com"],
                "privateKey": private_key,
                "shortIds": [short_id],
                "settings": {"publicKey": public_key, "fingerprint": "firefox", "spiderX": "/"}
            },
            "tcpSettings": {"header": {"type": "none"}}
        }),
        "sniffing": json.dumps({"enabled": True, "destOverride": ["http", "tls"]})
    }

    headers = {"Content-Type": "application/json", "Cookie": xui_cookie}

    async with aiohttp.ClientSession() as session:
        async with session.post(
            f"{XUI_API}/panel/api/inbounds/add",
            headers=headers, json=payload, ssl=False
        ) as resp:
            data = await resp.json(content_type=None)
            if data.get("success"):
                # Получаем inbound_id из ответа API (обычно в obj.id)
                inbound_id = None
                if data.get("obj") and isinstance(data["obj"], dict):
                    inbound_id = data["obj"].get("id")
                
                await save_user(
                    telegram_id=telegram_id,
                    uuid=client_uuid,
                    email=email,
                    port=port,
                    expiry_time=expiry,
                    short_id=short_id,
                    ip_limit=1,
                    is_active=True,
                    inbound_id=inbound_id
                )
                return {
                    "uuid": client_uuid,
                    "publicKey": public_key,
                    "port": port,
                    "short_id": short_id,
                    "inbound_id": inbound_id,
                    "server": data.get("obj", {}).get("listen", "") # Если сервер вернет IP
                }
            return None


async def get_client_stats(email: str):
    """Получает данные клиента по email"""
    global xui_cookie
    if not xui_cookie:
        await get_xui_cookie()
    
    headers = {"Content-Type": "application/json", "Cookie": xui_cookie}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{XUI_API}/panel/api/inbounds/getClientTraffics/{email}",
                headers=headers, ssl=False
            ) as resp:
                data = await resp.json(content_type=None)
                if data.get("success") and data.get("obj"):
                    return data["obj"]
                return None
    except Exception as e:
        logging.error(f"Error getting stats: {e}")
        return None


async def update_client_subscription(email: str, added_days: int, new_ip_limit: int) -> bool:
    """
    Продлевает подписку клиента.
    Для корректной работы нам нужен UUID клиента. 
    Мы можем взять его из базы данных или найти через API, если метод getClientTraffics его не вернет.
    """
    global xui_cookie
    if not xui_cookie:
        await get_xui_cookie()

    headers = {"Content-Type": "application/json", "Cookie": xui_cookie}

    try:
        # 1. Получаем текущие данные (прежде всего expiryTime)
        stats = await get_client_stats(email)
        logging.debug(f"update_client_subscription: stats for {email}: {repr(stats)} (type={type(stats)})")
        current_expiry = 0
        
        if stats:
             # stats может быть списком или словарем в зависимости от версии панели
             try:
                 if isinstance(stats, list) and len(stats) > 0:
                     current_expiry = stats[0].get("expiryTime", 0) if stats[0] else 0
                 elif isinstance(stats, dict):
                     current_expiry = stats.get("expiryTime", 0)
             except (IndexError, AttributeError, TypeError) as e:
                 logging.warning(f"⚠️ Ошибка при разборе stats для {email}: {e}")
                 current_expiry = 0
        
        # 2. Считаем новое время
        now = int(time.time() * 1000)
        
        # Если подписка активна (время в будущем) -> добавляем к текущему сроку
        if current_expiry > now:
            new_expiry = current_expiry + (added_days * 86400000)
        else:
            # Если истекла или никогда не была активна -> добавляем к "сейчас"
            new_expiry = now + (added_days * 86400000)

        # 3. Получаем inbound_id из базы данных по email (который равен telegram_id)
        user_data = await get_user_by_telegram_id(int(email))
        logging.debug(f"update_client_subscription: user_data for {email}: {repr(user_data)} (type={type(user_data)})")
        if not user_data:
            logging.error(f"❌ Пользователь {email} не найден в БД при обновлении")
            return False

        # Защита от None и неожиданных типов
        if user_data is None:
            logging.error(f"❌ user_data is None для {email}")
            return False

        try:
            inbound_id = user_data.get("inbound_id") if hasattr(user_data, 'get') else user_data['inbound_id'] if 'inbound_id' in user_data else None
            client_uuid = user_data.get("uuid") if hasattr(user_data, 'get') else user_data['uuid'] if 'uuid' in user_data else None
        except Exception as ex:
            logging.error(f"❌ Ошибка извлечения полей user_data для {email}: {ex}; user_data={repr(user_data)}", exc_info=True)
            return False

        if not inbound_id:
            logging.error(f"❌ inbound_id не найден для пользователя {email}; user_data={repr(user_data)}")
            return False

        # 4. Отправляем запрос на обновление
        # API ожидает id как integer (ID inbound'а), а не UUID
        payload = {
            "id": inbound_id,
            "expiryTime": new_expiry,
            "limitIp": int(new_ip_limit),
            "enable": True,
            "email": email
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{XUI_API}/panel/api/inbounds/update/{inbound_id}",
                headers=headers,
                json=payload,
                ssl=False
            ) as resp:
                status = resp.status
                try:
                    data = await resp.json(content_type=None)
                except Exception:
                    text = await resp.text()
                    logging.error(f"❌ Ошибка парсинга JSON от XUI (status={status}) для {email}: {text}")
                    return False

                logging.debug(f"update_client_subscription: response status={status}, data={repr(data)}")

                if isinstance(data, dict) and data.get("success"):
                    logging.info(f"✅ Подписка продлена для {email}. Новая дата: {datetime.fromtimestamp(new_expiry/1000)}")
                    return True
                else:
                    logging.error(f"❌ Ошибка API при обновлении (status={status}): {repr(data)}")
                    return False

    except Exception as e:
        logging.error(f"❌ Критическая ошибка update_client_subscription: {e}")
        return False


async def enable_client(email: str) -> bool:
    """Включает клиента (enable: true)"""
    # Логика упрощена: делаем update с текущим временем, просто меняя флаг
    # Но проще всего передать те же параметры, что есть, но enable=true
    # Здесь мы используем трюк: вызываем update с 0 дней добавления, но жестко ставим enable=True внутри update
    return await update_client_subscription(email, 0, 0) # 0 дней не меняют дату, если она в будущем


async def disable_client(email: str) -> bool:
    """Отключает клиента (enable: false)"""
    global xui_cookie
    if not xui_cookie:
        await get_xui_cookie()
        
    user_data = await get_user_by_telegram_id(int(email))
    if not user_data:
        return False
    
    inbound_id = user_data.get("inbound_id")
    headers = {"Content-Type": "application/json", "Cookie": xui_cookie}
    
    if not inbound_id:
        logging.error(f"❌ inbound_id не найден для отключения клиента {email}")
        return False
    
    payload = {
        "id": inbound_id,
        "email": email,
        "enable": False
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{XUI_API}/panel/api/inbounds/update/{inbound_id}",
                headers=headers, json=payload, ssl=False
            ) as resp:
                status = resp.status
                try:
                    data = await resp.json(content_type=None)
                except Exception:
                    text = await resp.text()
                    logging.error(f"❌ Ошибка парсинга JSON от XUI при disable (status={status}) для {email}: {text}")
                    return False

                logging.debug(f"disable_client: response status={status}, data={repr(data)}")
                return data.get("success", False)
    except Exception as e:
        logging.error(f"Disable error: {e}")
        return False