"""
Логика активации/продления подписки после успешного платежа.
Вызывается исключительно из вебхука ЮKassa (web_routes.py).
"""
import asyncio
import logging
import os

from aiogram import Bot
from aiogram.types import FSInputFile, InputMediaPhoto

from config import FRONT_DOMAIN
from database import (
    get_payment_by_id,
    get_user_by_telegram_id,
    mark_payment_as_processed,
)
from xui_api import create_client_inbound, update_client_subscription


async def _send_subscription_via_bot(bot: Bot, telegram_id: int, short_id: str) -> None:
    """Отправляет ссылку на подписку и инструкции через bot.send_*."""
    link = f"https://{FRONT_DOMAIN}/sub/{short_id}"
    subscription_text = (
        "✅ *Подписка активирована!*\n\n"
        "🔗 Ваша ссылка на подписку:\n"
        f"`{link}`\n\n"
        "1️⃣ Установите V2RayTun https://v2raytun.com/ ,Happ https://www.happ.su/main/ru или другой клиент\n"
        "2️⃣ Скопируйте ссылку, просто кликнув по ней\n"
        "3️⃣ Вставьте ссылку в V2RayTun, нажав на \"+\", затем \" вставить из буффера\" и подключитесь\n"
    )

    instr1_path = "Instruction1.jpg"
    instr2_path = "Instruction2.jpg"

    if os.path.exists(instr1_path) and os.path.exists(instr2_path):
        media_group = [
            InputMediaPhoto(
                media=FSInputFile(instr1_path),
                caption=subscription_text,
                parse_mode="Markdown",
            ),
            InputMediaPhoto(media=FSInputFile(instr2_path)),
        ]
        await bot.send_media_group(chat_id=telegram_id, media=media_group)
    else:
        await bot.send_message(
            chat_id=telegram_id,
            text=subscription_text,
            parse_mode="Markdown",
        )


async def activate_subscription(
    payment_id: str,
    telegram_id: int,
    added_days: int,
    devices: int,
    bot: Bot,
) -> None:
    """
    Активирует или продлевает подписку после успешного платежа.

    Идемпотентна: повторный вызов с тем же payment_id ничего не делает.
    Уведомляет пользователя через bot.send_message при любом исходе.
    """

    # ── 1. Защита от двойной обработки ──────────────────────────────────────
    try:
        local_payment = await get_payment_by_id(payment_id)
    except Exception as e:
        logging.error(f"❌ [webhook] Ошибка чтения платежа {payment_id} из БД: {e}")
        return

    if local_payment and local_payment.get("status") == "completed":
        logging.warning(f"⚠️ [webhook] Платёж {payment_id} уже обработан — пропускаем")
        return

    # ── 2. Получаем запись пользователя ─────────────────────────────────────
    try:
        user = await get_user_by_telegram_id(telegram_id)
    except Exception as e:
        logging.error(f"❌ [webhook] Ошибка чтения пользователя {telegram_id}: {e}")
        await bot.send_message(
            telegram_id,
            "❌ Платёж принят, но произошла ошибка базы данных.\n"
            "Свяжитесь с техподдержкой.",
        )
        return

    # ── 3. Первая покупка: пользователя ещё нет в БД ────────────────────────
    if not user:
        total_days = added_days + 3  # +3 дня бонуса за первую покупку

        await bot.send_message(telegram_id, "⏳ Создаю вашу подписку...")

        try:
            trial_result = await create_client_inbound(telegram_id)
        except Exception as e:
            logging.error(
                f"❌ [webhook] create_client_inbound упал для {telegram_id}: {e}",
                exc_info=True,
            )
            trial_result = None

        if not trial_result or trial_result.get("error"):
            logging.error(
                f"❌ [webhook] Не удалось создать inbound для {telegram_id}: {trial_result}"
            )
            await bot.send_message(
                telegram_id,
                "❌ Платёж принят, но не удалось создать подписку.\n"
                "Пожалуйста, свяжитесь с техподдержкой для ручной активации.",
            )
            return

        logging.info(
            f"✅ [webhook] Inbound создан для {telegram_id}, "
            f"inbound_id={trial_result.get('inbound_id')}"
        )

        # Пауза для синхронизации записи в SQLite
        await asyncio.sleep(0.5)

        try:
            user = await get_user_by_telegram_id(telegram_id)
        except Exception as e:
            logging.error(
                f"❌ [webhook] Ошибка повторного чтения пользователя {telegram_id}: {e}"
            )
            user = None

        if not user:
            logging.error(
                f"❌ [webhook] Пользователь {telegram_id} не найден в БД после создания inbound"
            )
            await bot.send_message(
                telegram_id,
                "❌ Ошибка синхронизации базы данных.\nСвяжитесь с техподдержкой.",
            )
            return

        email = user.get("email")

        try:
            success = await update_client_subscription(
                email=email, added_days=total_days, new_ip_limit=devices
            )
        except Exception as e:
            success = False
            logging.error(
                f"❌ [webhook] update_client_subscription упал для {telegram_id}: {e}",
                exc_info=True,
            )

        if not success:
            logging.error(f"❌ [webhook] Не удалось применить дни для {telegram_id}")
            await bot.send_message(
                telegram_id,
                "⚠️ Подписка создана, но не удалось применить купленные дни.\n"
                "Свяжитесь с техподдержкой.",
            )
            return

        logging.info(
            f"✅ [webhook] Первая покупка: {telegram_id}, {total_days} дней "
            f"(+3 бонусных), {devices} устр."
        )

    # ── 4. Повторная покупка: продлеваем существующую подписку ──────────────
    else:
        email = user.get("email")

        try:
            success = await update_client_subscription(
                email=email, added_days=added_days, new_ip_limit=devices
            )
        except Exception as e:
            success = False
            logging.error(
                f"❌ [webhook] update_client_subscription упал для {telegram_id}: {e}",
                exc_info=True,
            )

        if not success:
            logging.error(f"❌ [webhook] Не удалось продлить подписку для {telegram_id}")
            await bot.send_message(
                telegram_id,
                "❌ Платёж принят, но не удалось продлить подписку.\n"
                "Пожалуйста, свяжитесь с техподдержкой.",
            )
            return

        logging.info(
            f"✅ [webhook] Продление: {telegram_id}, {added_days} дней, {devices} устр."
        )

    # ── 5. Фиксируем платёж как обработанный ────────────────────────────────
    try:
        await mark_payment_as_processed(payment_id)
    except Exception as e:
        logging.error(
            f"❌ [webhook] Не удалось пометить платёж {payment_id} как completed: {e}"
        )

    # ── 6. Уведомляем пользователя ───────────────────────────────────────────
    await bot.send_message(
        telegram_id,
        "✅ Оплата прошла успешно! Подписка активирована/продлена.",
    )

    # Инструкция (если есть файл)
    if os.path.exists("instruction.jpg"):
        try:
            await bot.send_photo(
                chat_id=telegram_id,
                photo=FSInputFile("instruction.jpg"),
                caption="Инструкция по подключению",
            )
        except Exception as e:
            logging.warning(f"⚠️ [webhook] Не удалось отправить instruction.jpg: {e}")

    # Пользовательское соглашение (pdf → txt → ничего)
    for agreement_path in ("user_agreement.pdf", "user_agreement.txt"):
        if os.path.exists(agreement_path):
            try:
                await bot.send_document(
                    chat_id=telegram_id,
                    document=FSInputFile(agreement_path),
                    caption="Пользовательское соглашение",
                )
            except Exception as e:
                logging.warning(f"⚠️ [webhook] Не удалось отправить соглашение: {e}")
            break

    # Ссылка на подписку с инструкциями
    short_id = user.get("short_id")
    if short_id:
        try:
            await _send_subscription_via_bot(bot, telegram_id, short_id)
        except Exception as e:
            logging.error(
                f"❌ [webhook] Ошибка при отправке ссылки подписки {telegram_id}: {e}"
            )
    else:
        logging.error(
            f"⚠️ [webhook] short_id не найден для пользователя {telegram_id}"
        )

    logging.info(
        f"✅ [webhook] Платёж {payment_id} полностью обработан для {telegram_id}"
    )