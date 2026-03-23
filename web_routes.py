import asyncio
import logging

import aiohttp
from aiohttp import web

from database import get_payment_by_id, get_user_by_short_id
from config import FRONT_DOMAIN, VPN_DOMAIN
from payment_processor import activate_subscription

# URL подписки на VPN-сервере
if VPN_DOMAIN:
    XUI_SUB_URL = f"http://{VPN_DOMAIN}:2096/sub/"
else:
    XUI_SUB_URL = f"http://{FRONT_DOMAIN}:2096/sub/"


# ── Подписка (прокси к 3x-ui) ────────────────────────────────────────────────

async def handle_short_sub(request: web.Request) -> web.Response:
    """
    Проксирует запрос конфига подписки с VPN-сервера клиенту.
    Пользователь обращается по /sub/{short_id}.
    """
    short_id = request.match_info.get("short_id")
    user_agent = request.headers.get("User-Agent", "unknown")

    if not short_id:
        logging.warning(
            f"⚠️ Запрос /sub/ без short_id от {request.remote} (UA: {user_agent})"
        )
        return web.Response(status=400, text="short_id is required")

    logging.info(
        f"📥 Запрос подписки: short_id={short_id}, IP={request.remote}, UA={user_agent}"
    )

    user = await get_user_by_short_id(short_id)
    if not user:
        logging.info(f"⚠️ Пользователь с short_id={short_id} не найден в БД")
        return web.Response(status=404, text="User not found")

    sub_id = user.get("short_id")
    if not sub_id:
        logging.error(
            f"❌ short_id не найден для telegram_id={user.get('telegram_id')}"
        )
        return web.Response(status=500, text="Internal error: short_id not found")

    target_url = f"{XUI_SUB_URL}{sub_id}"
    logging.debug(f"📝 Обращаюсь к VPN: {target_url}")

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(target_url, timeout=aiohttp.ClientTimeout(total=10), ssl=False) as resp:
                if resp.status == 200:
                    content = await resp.text()
                    if not content:
                        logging.warning(
                            f"⚠️ VPN вернул пустой ответ для short_id={short_id}"
                        )
                        return web.Response(status=502, text="Empty subscription config")

                    logging.info(
                        f"✅ Конфиг получен для short_id={short_id} ({len(content)} байт)"
                    )
                    return web.Response(
                        text=content,
                        content_type="text/plain",
                        charset="utf-8",
                        headers={
                            "Subscription-Userinfo": resp.headers.get(
                                "Subscription-Userinfo", ""
                            ),
                            "Profile-Update-Interval": "24",
                        },
                    )
                elif resp.status == 404:
                    error_text = await resp.text()
                    logging.warning(
                        f"⚠️ VPN вернул 404 для url={target_url}. Ответ: {error_text[:100]}"
                    )
                    return web.Response(status=404, text="Subscription not found on server")
                else:
                    error_text = await resp.text()
                    logging.error(
                        f"❌ VPN вернул {resp.status} для short_id={short_id}. "
                        f"URL: {target_url}. Ответ: {error_text[:200]}"
                    )
                    return web.Response(status=502, text=f"Server error: {resp.status}")

    except asyncio.TimeoutError:
        logging.error(f"⏱️ Timeout при обращении к VPN (url: {target_url})")
        return web.Response(status=504, text="Server timeout")
    except Exception as e:
        logging.error(
            f"❌ Критическая ошибка при запросе к VPN (url: {target_url}): {e}",
            exc_info=True,
        )
        return web.Response(status=500, text="Internal server error")


# ── Вебхук ЮKassa ────────────────────────────────────────────────────────────

async def handle_yookassa_webhook(request: web.Request) -> web.Response:
    """
    Принимает уведомления от ЮKassa.
    Всегда возвращает 200 — повторные попытки ЮKassa обрабатываются
    через идемпотентность activate_subscription (проверка статуса 'completed').

    Документация: https://yookassa.ru/developers/using-api/webhooks
    """

    # ── Парсим тело ──────────────────────────────────────────────────────────
    try:
        body = await request.json()
    except Exception as e:
        logging.error(f"❌ [webhook] Не удалось распарсить JSON: {e}")
        # Возвращаем 400 чтобы ЮKassa повторила запрос (тело может быть обрезано)
        return web.Response(status=400, text="Invalid JSON")

    event = body.get("event")
    payment_obj = body.get("object", {})

    logging.info(f"📩 [webhook] Получено событие: {event}")

    # ── Нас интересует только успешная оплата ────────────────────────────────
    if event != "payment.succeeded":
        return web.Response(status=200, text="OK")

    payment_id = payment_obj.get("id")
    if not payment_id:
        logging.error("❌ [webhook] Нет payment_id в теле события")
        return web.Response(status=200, text="OK")

    # ── Безопасность: платёж должен быть в нашей БД ─────────────────────────
    # Это предотвращает обработку фейковых вебхуков — злоумышленник не знает
    # реальные payment_id, которые мы создали через API ЮKassa.
    try:
        local_payment = await get_payment_by_id(payment_id)
    except Exception as e:
        logging.error(f"❌ [webhook] Ошибка чтения платежа {payment_id} из БД: {e}")
        return web.Response(status=200, text="OK")

    if not local_payment:
        logging.warning(
            f"⚠️ [webhook] Платёж {payment_id} не найден в нашей БД — игнорируем"
        )
        return web.Response(status=200, text="OK")

    # ── Извлекаем метаданные ─────────────────────────────────────────────────
    metadata = payment_obj.get("metadata") or {}
    telegram_id_raw = metadata.get("telegram_id")
    added_days_raw = metadata.get("days")
    devices_raw = metadata.get("devices")

    if not all([telegram_id_raw, added_days_raw, devices_raw]):
        logging.error(
            f"❌ [webhook] Неполные метаданные для платежа {payment_id}: {metadata}"
        )
        return web.Response(status=200, text="OK")

    try:
        telegram_id = int(telegram_id_raw)
        added_days = int(added_days_raw)
        devices = int(devices_raw)
    except (ValueError, TypeError) as e:
        logging.error(
            f"❌ [webhook] Ошибка парсинга метаданных платежа {payment_id}: {e}"
        )
        return web.Response(status=200, text="OK")

    # ── Дополнительная проверка: telegram_id совпадает с тем, что в БД ───────
    if local_payment.get("telegram_id") != telegram_id:
        logging.error(
            f"❌ [webhook] telegram_id не совпадает для платежа {payment_id}: "
            f"в БД={local_payment.get('telegram_id')}, в метаданных={telegram_id}"
        )
        return web.Response(status=200, text="OK")

    # ── Активируем подписку ──────────────────────────────────────────────────
    # Запускаем как фоновую задачу чтобы сразу вернуть 200 ЮKassa,
    # не дожидаясь завершения всех запросов к 3x-ui и Telegram Bot API.
    bot = request.app["bot"]
    asyncio.create_task(
        activate_subscription(
            payment_id=payment_id,
            telegram_id=telegram_id,
            added_days=added_days,
            devices=devices,
            bot=bot,
        )
    )

    logging.info(
        f"✅ [webhook] Задача активации запущена: payment_id={payment_id}, "
        f"telegram_id={telegram_id}"
    )
    return web.Response(status=200, text="OK")