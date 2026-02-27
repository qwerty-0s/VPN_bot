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
                set_cookie = resp.headers.get("Set-Cookie")
                if set_cookie:
                    cookie_value = set_cookie.split(";")[0]
                    xui_cookie = cookie_value
                    logging.info("✅ Cookie обновлена")
                else:
                    logging.error("❌ Сервер не вернул Set-Cookie!")
                    xui_cookie = None
    except Exception as e:
        logging.error(f"❌ Ошибка при логине: {e}")
        xui_cookie = None


async def _xui_request(method: str, path: str, **kwargs):
    """
    Выполняет запрос к XUI API с автоматической переавторизацией при 401.
    Возвращает распарсенный JSON или None при ошибке.
    """
    global xui_cookie

    if not xui_cookie:
        await get_xui_cookie()

    for attempt in range(2):  # Одна попытка + одна после re-auth при 401
        headers = {"Content-Type": "application/json", "Cookie": xui_cookie or ""}
        try:
            async with aiohttp.ClientSession() as session:
                req = getattr(session, method)
                async with req(
                    f"{XUI_API}{path}",
                    headers=headers,
                    ssl=False,
                    **kwargs
                ) as resp:
                    if resp.status == 401 and attempt == 0:
                        logging.warning("⚠️ XUI вернул 401 — переавторизуемся...")
                        await get_xui_cookie()
                        continue
                    if resp.status not in (200, 201):
                        text = await resp.text()
                        logging.error(
                            f"❌ XUI вернул HTTP {resp.status} для {path}: {text[:300]}"
                        )
                        return None
                    try:
                        return await resp.json(content_type=None)
                    except Exception:
                        text = await resp.text()
                        logging.error(
                            f"❌ Ошибка парсинга JSON от XUI [{resp.status}] {path}: {text[:300]}"
                        )
                        return None
        except Exception as e:
            logging.error(f"❌ Ошибка запроса к XUI {path}: {e}")
            return None

    return None


async def get_new_reality_keys():
    """Получение новых ключей для Reality"""
    data = await _xui_request("get", "/panel/api/server/getNewX25519Cert")
    if not data or "obj" not in data:
        logging.error(f"❌ Не удалось получить Reality ключи. Ответ: {data}")
        return None
    return data


async def get_free_port():
    """Получение свободного порта"""
    data = await _xui_request("get", "/panel/api/inbounds/list")
    if not data:
        logging.error("❌ Не удалось получить список inbound для поиска свободного порта")
        return None
    try:
        used_ports = {int(i["port"]) for i in data.get("obj", []) if "port" in i}
        for _ in range(1000):
            port = random.randint(10000, 65000)
            if port not in used_ports:
                return port
        logging.error("❌ Не удалось найти свободный порт после 1000 попыток")
        return None
    except Exception as e:
        logging.error(f"❌ Ошибка при поиске свободного порта: {e}")
        return None


async def find_and_sync_user_from_xui(telegram_id: int) -> dict | None:
    """
    Ищет пользователя в XUI панели по email (telegram_id) и синхронизирует в БД.
    Используется для восстановления при расхождении XUI↔БД.

    Returns:
        dict с данными пользователя (как create_client_inbound) или None
    """
    email = str(telegram_id)
    logging.info(f"🔍 Ищу пользователя {email} в XUI панели для синхронизации...")

    data = await _xui_request("get", "/panel/api/inbounds/list")
    if not data or not data.get("success"):
        logging.error("❌ Не удалось получить список inbound для синхронизации")
        return None

    inbounds = data.get("obj", [])
    for inbound in inbounds:
        try:
            raw_settings = inbound.get("settings")
            if not raw_settings:
                continue
            settings = json.loads(raw_settings) if isinstance(raw_settings, str) else raw_settings
            clients = settings.get("clients", [])

            for client in clients:
                if str(client.get("email", "")) != email:
                    continue

                # Нашли клиента! Извлекаем все данные
                client_uuid = client.get("id")
                short_id = client.get("subId", "")
                expiry_time = client.get("expiryTime", 0)
                ip_limit = client.get("limitIp", 1)
                inbound_id = inbound.get("id")
                port = inbound.get("port")

                # Извлекаем publicKey из streamSettings для полноты
                raw_stream = inbound.get("streamSettings", {})
                stream = json.loads(raw_stream) if isinstance(raw_stream, str) else raw_stream
                public_key = (
                    stream.get("realitySettings", {})
                    .get("settings", {})
                    .get("publicKey", "")
                )

                logging.info(
                    f"✅ Найден пользователь {email} в XUI: "
                    f"inbound_id={inbound_id}, uuid={client_uuid}, port={port}"
                )

                # Сохраняем в БД
                await save_user(
                    telegram_id=telegram_id,
                    uuid=client_uuid,
                    email=email,
                    port=port,
                    expiry_time=expiry_time if expiry_time else 0,
                    short_id=short_id,
                    ip_limit=ip_limit,
                    is_active=True,
                    inbound_id=inbound_id,
                )

                return {
                    "uuid": client_uuid,
                    "publicKey": public_key,
                    "port": port,
                    "short_id": short_id,
                    "inbound_id": inbound_id,
                    "recovered": True,  # Флаг что это восстановление, а не новое создание
                }
        except Exception as e:
            logging.warning(f"⚠️ Ошибка при разборе inbound {inbound.get('id')}: {e}")
            continue

    logging.warning(f"⚠️ Пользователь {email} не найден ни в одном inbound XUI")
    return None


async def create_client_inbound(telegram_id: int):
    """Создает подписку (клиента) в панели (used for trial and new paid users)"""
    if await user_exists(telegram_id):
        return {"error": "already_exists"}

    keys = await get_new_reality_keys()
    if not keys:
        # get_new_reality_keys уже залогировал ошибку
        return None

    private_key = keys["obj"]["privateKey"]
    public_key = keys["obj"]["publicKey"]

    # По умолчанию создаем на 3 дня (триал)
    expiry = int((datetime.now() + timedelta(days=3)).timestamp() * 1000)
    client_uuid = str(uuid.uuid4())
    email = str(telegram_id)
    short_id = secrets.token_hex(8)
    port = await get_free_port()

    if not port:
        # get_free_port уже залогировал ошибку
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
        "expiryTime": 0,  # Inbound сам по себе бессрочен; expiry управляется клиентом
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

    try:
        data = await _xui_request("post", "/panel/api/inbounds/add", json=payload)

        if data is None:
            # _xui_request уже залогировал ошибку
            logging.error(f"❌ create_client_inbound: запрос к XUI вернул None для {telegram_id}")
            return None

        if not data.get("success"):
            msg = data.get("msg", "неизвестная ошибка")
            logging.error(f"❌ XUI отказал при создании inbound для {telegram_id}: {msg}")

            # Если XUI говорит что email уже существует — синхронизируем из панели
            if "email" in msg.lower() or "exist" in msg.lower() or "already" in msg.lower():
                logging.warning(
                    f"⚠️ Email {email} уже существует в XUI, но не в БД. "
                    f"Пробую синхронизировать..."
                )
                return await find_and_sync_user_from_xui(telegram_id)

            return None

        inbound_id = None
        if data.get("obj") and isinstance(data["obj"], dict):
            inbound_id = data["obj"].get("id")

        if not inbound_id:
            logging.error(f"❌ XUI не вернул inbound_id после создания для {telegram_id}. Ответ: {data}")
            return None

        await save_user(
            telegram_id=telegram_id,
            uuid=client_uuid,
            email=email,
            port=port,
            expiry_time=expiry,
            short_id=short_id,
            ip_limit=1,
            is_active=True,
            inbound_id=inbound_id,
        )

        logging.info(f"✅ Inbound создан для {telegram_id}: inbound_id={inbound_id}, port={port}")
        return {
            "uuid": client_uuid,
            "publicKey": public_key,
            "port": port,
            "short_id": short_id,
            "inbound_id": inbound_id,
            "server": data.get("obj", {}).get("listen", ""),
        }

    except Exception as e:
        logging.error(f"❌ Исключение при создании inbound для {telegram_id}: {e}", exc_info=True)
        return None


async def get_inbound(inbound_id: int):
    """Получает полные данные inbound по ID для обновления"""
    data = await _xui_request("get", f"/panel/api/inbounds/get/{inbound_id}")
    if data and data.get("success") and data.get("obj"):
        return data["obj"]
    logging.error(f"❌ Ошибка при получении inbound {inbound_id}: {data}")
    return None


async def get_client_stats(email: str):
    """Получает данные клиента по email"""
    data = await _xui_request("get", f"/panel/api/inbounds/getClientTraffics/{email}")
    if data and data.get("success") and data.get("obj"):
        return data["obj"]
    return None


async def update_client_subscription(email: str, added_days: int, new_ip_limit: int) -> bool:
    """
    Продлевает подписку клиента.

    Шаг A: обновляет клиента через /updateClient/{uuid} (expiryTime + limitIp).
           Это главный эндпоинт — именно он управляет тем, что видно в колонке
           Duration у клиента в панели.
    Шаг B: обновляет inbound-level expiryTime через /update/{inbound_id},
           чтобы строка inbound в панели тоже отображала актуальный срок.
           Некритичен — если упадёт, клиент всё равно работает.

    Args:
        email:        telegram_id пользователя в строковом виде (так хранится в XUI)
        added_days:   количество дней, добавляемых к текущему expiry (если активен)
                      или от сегодня (если уже истёк)
        new_ip_limit: лимит одновременных устройств
    """
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

        # 3. Парсим settings — находим объект клиента по uuid
        raw_settings = inbound_data.get("settings")
        try:
            settings = json.loads(raw_settings) if isinstance(raw_settings, str) else (raw_settings or {})
        except Exception as ex:
            logging.error(f"❌ Ошибка при разборе settings inbound {inbound_id}: {ex}")
            return False

        clients = settings.get("clients", [])
        client_obj = next((c for c in clients if c.get("id") == client_uuid), None)

        if not client_obj:
            # Клиент не найден в настройках — создаём минимальный объект из БД
            logging.warning(
                f"⚠️ Клиент {client_uuid} не найден в settings inbound {inbound_id}, "
                f"создаю минимальный объект"
            )
            client_obj = {
                "id": client_uuid,
                "flow": "xtls-rprx-vision",
                "email": email,
                "enable": True,
                "tgId": email,
                "subId": user_data.get("short_id", ""),
                "totalGB": 0,
            }

        # 4. Вычисляем новое время истечения.
        #    Если подписка ещё активна — добавляем дни к текущему expiry (остаток сохраняется).
        #    Если уже истекла или отсутствует — отсчитываем от сегодня.
        now = int(time.time() * 1000)
        current_expiry = client_obj.get("expiryTime") or 0
        base = current_expiry if current_expiry > now else now
        new_expiry = base + (added_days * 86400000)

        logging.info(
            f"📝 Обновляю подписку: inbound_id={inbound_id}, uuid={client_uuid}, email={email}, "
            f"current_expiry={datetime.fromtimestamp(current_expiry / 1000) if current_expiry else 'нет'}, "
            f"new_expiry={datetime.fromtimestamp(new_expiry / 1000)}, "
            f"added_days={added_days}, new_ip_limit={new_ip_limit}"
        )

        # Обновляем поля клиента
        client_obj["expiryTime"] = new_expiry
        client_obj["limitIp"] = int(new_ip_limit)
        client_obj["enable"] = True

        # Собираем обновлённый список клиентов для full-inbound payload
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

        # ── ШАГ A: пробуем /updateClient/{uuid} ───────────────────────────────
        # Этот эндпоинт обновляет клиента точечно и есть в новых версиях XUI.
        client_payload = {
            "id": inbound_id,
            "settings": json.dumps({"clients": [client_obj]})
        }

        result_a = await _xui_request(
            "post",
            f"/panel/api/inbounds/{inbound_id}/updateClient/{client_uuid}",
            json=client_payload
        )

        if isinstance(result_a, dict) and result_a.get("success"):
            logging.info(f"✅ Клиент {client_uuid} обновлён через /updateClient (шаг A)")
            # Шаг A успешен — дополнительно обновляем inbound для актуальности UI
            result_b = await _xui_request(
                "post",
                f"/panel/api/inbounds/update/{inbound_id}",
                json=inbound_payload
            )
            if not (isinstance(result_b, dict) and result_b.get("success")):
                logging.warning(f"⚠️ /update inbound (шаг B) вернул ошибку: {repr(result_b)} — некритично")
            logging.info(
                f"✅ Подписка продлена для {email}. "
                f"Новая дата: {datetime.fromtimestamp(new_expiry / 1000)}"
            )
            return True

        # ── ШАГ B (fallback): /updateClient недоступен — используем полный /update ──
        logging.warning(
            f"⚠️ /updateClient недоступен или вернул ошибку ({repr(result_a)}), "
            f"используем fallback /update/{inbound_id}"
        )

        result_b = await _xui_request(
            "post",
            f"/panel/api/inbounds/update/{inbound_id}",
            json=inbound_payload
        )

        if isinstance(result_b, dict) and result_b.get("success"):
            logging.info(
                f"✅ Подписка продлена через fallback /update для {email}. "
                f"Новая дата: {datetime.fromtimestamp(new_expiry / 1000)}"
            )
            return True

        logging.error(f"❌ Оба метода обновления не сработали для {email}. "
                      f"updateClient={repr(result_a)}, update={repr(result_b)}")
        return False

    except Exception as e:
        logging.error(f"❌ Критическая ошибка update_client_subscription: {e}", exc_info=True)
        return False


async def enable_client(email: str) -> bool:
    """
    Включает клиента (enable: true), не меняя дату истечения и лимит устройств.
    """
    try:
        user_data = await get_user_by_telegram_id(int(email))
        if not user_data:
            return False

        inbound_id = user_data.get("inbound_id")
        client_uuid = user_data.get("uuid")
        if not inbound_id or not client_uuid:
            return False

        inbound_data = await get_inbound(inbound_id)
        if not inbound_data:
            return False

        raw_settings = inbound_data.get("settings")
        settings = json.loads(raw_settings) if isinstance(raw_settings, str) else (raw_settings or {})
        clients = settings.get("clients", [])
        client_obj = next((c for c in clients if c.get("id") == client_uuid), None)

        if not client_obj:
            logging.error(f"❌ enable_client: клиент {client_uuid} не найден в inbound {inbound_id}")
            return False

        client_obj["enable"] = True

        result = await _xui_request(
            "post",
            f"/panel/api/inbounds/{inbound_id}/updateClient/{client_uuid}",
            json={"id": inbound_id, "settings": json.dumps({"clients": [client_obj]})}
        )
        success = isinstance(result, dict) and result.get("success", False)
        if success:
            logging.info(f"✅ Клиент {email} включён")
        else:
            logging.error(f"❌ Ошибка при включении клиента {email}: {repr(result)}")
        return success

    except Exception as e:
        logging.error(f"❌ enable_client error: {e}")
        return False


async def disable_client(email: str) -> bool:
    """
    Отключает клиента (enable: false), не меняя дату истечения и лимит устройств.
    """
    try:
        user_data = await get_user_by_telegram_id(int(email))
        if not user_data:
            return False

        inbound_id = user_data.get("inbound_id")
        client_uuid = user_data.get("uuid")
        if not inbound_id or not client_uuid:
            logging.error(f"❌ disable_client: inbound_id или uuid не найден для {email}")
            return False

        inbound_data = await get_inbound(inbound_id)
        if not inbound_data:
            return False

        raw_settings = inbound_data.get("settings")
        settings = json.loads(raw_settings) if isinstance(raw_settings, str) else (raw_settings or {})
        clients = settings.get("clients", [])
        client_obj = next((c for c in clients if c.get("id") == client_uuid), None)

        if not client_obj:
            logging.error(f"❌ disable_client: клиент {client_uuid} не найден в inbound {inbound_id}")
            return False

        client_obj["enable"] = False

        result = await _xui_request(
            "post",
            f"/panel/api/inbounds/{inbound_id}/updateClient/{client_uuid}",
            json={"id": inbound_id, "settings": json.dumps({"clients": [client_obj]})}
        )
        success = isinstance(result, dict) and result.get("success", False)
        if success:
            logging.info(f"✅ Клиент {email} отключён")
        else:
            logging.error(f"❌ Ошибка при отключении клиента {email}: {repr(result)}")
        return success

    except Exception as e:
        logging.error(f"❌ disable_client error: {e}")
        return False