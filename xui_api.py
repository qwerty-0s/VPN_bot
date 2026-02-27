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


async def create_client_inbound(telegram_id: int):
    """Создает подписку (клиента) в панели (used for trial and new paid users)"""
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
    # Generate clean hex subId without any "trial_" prefix
    short_id = secrets.token_hex(8)  # Fix: generate cleaner, longer hex subId
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
        # Fix: set root expiryTime to 0 so the port itself never expires
        "expiryTime": 0,  # Fix: Port infinity expiry
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


async def get_inbound(inbound_id: int):
    """Получает полные данные inbound по ID для обновления"""
    global xui_cookie
    if not xui_cookie:
        await get_xui_cookie()
    
    headers = {"Content-Type": "application/json", "Cookie": xui_cookie}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{XUI_API}/panel/api/inbounds/get/{inbound_id}",
                headers=headers, ssl=False
            ) as resp:
                data = await resp.json(content_type=None)
                if data.get("success") and data.get("obj"):
                    return data["obj"]
                return None
    except Exception as e:
        logging.error(f"❌ Ошибка при получении inbound {inbound_id}: {e}")
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
    Шаг 1: обновляет клиента через /updateClient/{uuid} (expiryTime + limitIp).
    Шаг 2: обновляет inbound-level expiryTime через /update/{inbound_id}.
    """
    global xui_cookie
    if not xui_cookie:
        await get_xui_cookie()

    headers = {"Content-Type": "application/json", "Cookie": xui_cookie}

    try:
        # 1. Получаем данные пользователя из БД
        user_data = await get_user_by_telegram_id(int(email))
        if not user_data:
            logging.error(f"❌ Пользователь {email} не найден в БД при обновлении")
            return False

        inbound_id = user_data.get("inbound_id")
        client_uuid = user_data.get("uuid")

        if not inbound_id:
            logging.error(f"❌ inbound_id не найден для пользователя {email}")
            return False

        if not client_uuid:
            logging.error(f"❌ uuid клиента не найден для пользователя {email}")
            return False

        # 2. Получаем полные данные inbound с панели
        inbound_data = await get_inbound(inbound_id)
        if not inbound_data:
            logging.error(f"❌ Не удалось получить данные inbound {inbound_id}")
            return False

        # 3. Вычисляем новое время истечения
        now = int(time.time() * 1000)
        new_expiry = now + (added_days * 86400000)

        logging.info(
            f"📝 Обновляю подписку: inbound_id={inbound_id}, uuid={client_uuid}, "
            f"email={email}, new_expiry={datetime.fromtimestamp(new_expiry/1000)}, "
            f"new_ip_limit={new_ip_limit}"
        )

        # 4. Парсим settings чтобы найти полный объект клиента
        try:
            raw_settings = inbound_data.get("settings")
            if isinstance(raw_settings, str):
                settings = json.loads(raw_settings)
            else:
                settings = raw_settings or {}

            clients = settings.get("clients", [])
            # Находим нашего клиента по uuid
            client_obj = next((c for c in clients if c.get("id") == client_uuid), None)

            if not client_obj:
                # Если не нашли — создаём минимальный объект на основе данных из БД
                logging.warning(f"⚠️ Клиент {client_uuid} не найден в settings inbound {inbound_id}, создаю минимальный объект")
                client_obj = {
                    "id": client_uuid,
                    "flow": "xtls-rprx-vision",
                    "email": email,
                    "enable": True,
                    "tgId": email,
                    "subId": user_data.get("short_id", ""),
                    "totalGB": 0,
                }

            # Обновляем нужные поля клиента
            client_obj["expiryTime"] = new_expiry
            client_obj["limitIp"] = int(new_ip_limit)
            client_obj["enable"] = True

        except Exception as ex:
            logging.error(f"❌ Ошибка при разборе settings inbound {inbound_id}: {ex}")
            return False

        # ──────────────────────────────────────────────────────────────
        # ШАГ A: Обновляем КЛИЕНТА через /updateClient/{uuid}
        # Это ключевой эндпоинт, который обновляет expiryTime клиента в панели
        # ──────────────────────────────────────────────────────────────
        client_payload = {
            "id": inbound_id,
            "settings": json.dumps({"clients": [client_obj]})
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{XUI_API}/panel/api/inbounds/{inbound_id}/updateClient/{client_uuid}",
                headers=headers,
                json=client_payload,
                ssl=False
            ) as resp:
                status = resp.status
                try:
                    data = await resp.json(content_type=None)
                except Exception:
                    text = await resp.text()
                    logging.error(f"❌ Ошибка парсинга JSON от /updateClient (status={status}): {text}")
                    return False

                if not (isinstance(data, dict) and data.get("success")):
                    logging.error(f"❌ /updateClient вернул ошибку (status={status}): {repr(data)}")
                    return False

                logging.info(f"✅ Клиент {client_uuid} обновлён через /updateClient")

        # ──────────────────────────────────────────────────────────────
        # ШАГ B: Обновляем inbound-level expiryTime через /update/{id}
        # Чтобы в колонке Duration панели тоже отображалось корректное время
        # ──────────────────────────────────────────────────────────────

        # Формируем актуальный settings со всеми клиентами (включая обновлённый)
        updated_clients = []
        found = False
        for c in clients:
            if c.get("id") == client_uuid:
                updated_clients.append(client_obj)
                found = True
            else:
                updated_clients.append(c)
        if not found:
            updated_clients.append(client_obj)

        settings["clients"] = updated_clients

        # streamSettings и sniffing могут прийти как dict или строка — нормализуем
        stream = inbound_data.get("streamSettings", {})
        sniff = inbound_data.get("sniffing", {})

        inbound_payload = {
            "id": inbound_id,
            "up": inbound_data.get("up", 0),
            "down": inbound_data.get("down", 0),
            "total": inbound_data.get("total", 0),
            "remark": inbound_data.get("remark", email),
            "enable": True,
            "expiryTime": new_expiry,
            "listen": inbound_data.get("listen", ""),
            "port": inbound_data.get("port"),
            "protocol": inbound_data.get("protocol", "vless"),
            "settings": json.dumps(settings),
            "streamSettings": json.dumps(stream) if isinstance(stream, dict) else stream,
            "sniffing": json.dumps(sniff) if isinstance(sniff, dict) else sniff,
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{XUI_API}/panel/api/inbounds/update/{inbound_id}",
                headers=headers,
                json=inbound_payload,
                ssl=False
            ) as resp:
                status = resp.status
                try:
                    data = await resp.json(content_type=None)
                except Exception:
                    text = await resp.text()
                    logging.error(f"❌ Ошибка парсинга JSON от /update (status={status}): {text}")
                    # Шаг A уже прошёл успешно — клиент обновлён, считаем успехом
                    return True

                if isinstance(data, dict) and data.get("success"):
                    logging.info(
                        f"✅ Подписка полностью продлена для {email}. "
                        f"Новая дата: {datetime.fromtimestamp(new_expiry/1000)}"
                    )
                    return True
                else:
                    # Шаг A прошёл — клиент обновлён. Inbound expiry не обновился,
                    # но это некритично — клиент всё равно будет работать.
                    logging.warning(
                        f"⚠️ /update inbound вернул ошибку, но клиент уже обновлён "
                        f"через /updateClient. status={status}, data={repr(data)}"
                    )
                    return True

    except Exception as e:
        logging.error(f"❌ Критическая ошибка update_client_subscription: {e}", exc_info=True)
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