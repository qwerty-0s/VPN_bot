"""Обработчики сообщений для Telegram бота"""
import logging
import os

from aiogram import F, types
from aiogram.types import (
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    InputMediaPhoto,
)

from xui_api import create_client_inbound
from yookassa_pay import create_payment_link
from database import save_payment, get_user_by_telegram_id
from config import FRONT_DOMAIN, TARIFFS


# Главное меню
main_menu = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="💎 Купить подписку")],
        [KeyboardButton(text="🚀 Пробная подписка"), KeyboardButton(text="👤 Мой профиль")],
        [KeyboardButton(text="⚙️ Техподдержка")],
        [KeyboardButton(text="📋 Пользовательское соглашение")],
    ],
    resize_keyboard=True,
)


async def send_subscription_with_instructions(message_or_callback, link: str, short_id: str):
    """
    Отправляет ссылку на подписку с инструкциями.
    Принимает как types.Message, так и types.CallbackQuery.
    Используется для пробных подписок (активируются без оплаты).
    """
    subscription_text = (
        "✅ *Подписка активирована!*\n\n"
        "🔗 Ваша ссылка на подписку:\n"
        f"`{link}`\n\n"
        "1️⃣ Установите V2RayTun https://v2raytun.com/\n"
        "2️⃣ Скопируйте ссылку, кликнув по ней\n"
        "3️⃣ Вставьте ссылку в V2RayTun и подключитесь\n"
    )

    instr1_path = "Instruction1.jpg"
    instr2_path = "Instruction2.jpg"

    # Определяем объект для отправки сообщений
    target = (
        message_or_callback.message
        if hasattr(message_or_callback, "message")
        else message_or_callback
    )

    try:
        if os.path.exists(instr1_path) and os.path.exists(instr2_path):
            media_group = [
                InputMediaPhoto(
                    media=types.FSInputFile(instr1_path),
                    caption=subscription_text,
                    parse_mode="Markdown",
                ),
                InputMediaPhoto(media=types.FSInputFile(instr2_path)),
            ]
            await target.answer_media_group(media=media_group)
            logging.info(f"✅ Отправлены инструкции с ссылкой {short_id}")
        else:
            await target.answer(subscription_text, parse_mode="Markdown")
            logging.warning(
                f"⚠️ Файлы инструкций не найдены, отправлен только текст для {short_id}"
            )
    except Exception as e:
        logging.error(f"❌ Ошибка при отправке подписки с инструкциями: {e}")


def get_devices_keyboard():
    """Inline-клавиатура для выбора количества устройств."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="1 устройство", callback_data="devices_1")],
            [InlineKeyboardButton(text="3 устройства", callback_data="devices_3")],
            [InlineKeyboardButton(text="5 устройств", callback_data="devices_5")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_buy")],
        ]
    )


def get_months_keyboard(devices: int):
    """Inline-клавиатура для выбора срока подписки."""
    keyboard = []
    for (months, dev), tariff_info in sorted(TARIFFS.items()):
        if dev == devices:
            price = tariff_info["price"]
            keyboard.append(
                [
                    InlineKeyboardButton(
                        text=f"{months} месяц(-а/-ев) — {price}₽",
                        callback_data=f"month_{months}m_{devices}d",
                    )
                ]
            )
    keyboard.append(
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_devices")]
    )
    keyboard.append(
        [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_buy")]
    )
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def register_handlers(dp):
    """Регистрация всех обработчиков."""

    # ── /start ────────────────────────────────────────────────────────────────

    @dp.message(F.text == "/start")
    async def start_handler(message: types.Message):
        user_name = message.from_user.first_name or "пользователь"
        await message.answer(
            f"Здравствуйте, {user_name}!\n\n"
            "Здесь вы можете получить VPN\n\n"
            "Выберите действие ниже:",
            reply_markup=main_menu,
        )
        logging.info(f"👤 Пользователь {message.from_user.id} нажал /start")

    # ── Пробная подписка ──────────────────────────────────────────────────────

    @dp.message(F.text == "🚀 Пробная подписка")
    async def trial_button(message: types.Message):
        telegram_id = message.from_user.id

        user = await get_user_by_telegram_id(telegram_id)
        if user:
            await message.answer(
                "⚠️ У вас уже есть подписка!\n\n"
                "Для создания новой пробной подписки свяжитесь с техподдержкой."
            )
            logging.warning(
                f"⚠️ Пользователь {telegram_id} попытался создать вторую подписку"
            )
            return

        result = await create_client_inbound(telegram_id)
        if not result or result.get("error"):
            await message.answer("❌ Не удалось создать пробную подписку.")
            logging.error(f"❌ Ошибка создания пробной подписки для {telegram_id}")
            return

        short_id = result["short_id"]
        link = f"https://{FRONT_DOMAIN}/sub/{short_id}"
        await send_subscription_with_instructions(message, link, short_id)
        logging.info(f"✅ Пробная подписка создана для {telegram_id}")

    # ── Покупка подписки: выбор устройств ─────────────────────────────────────

    @dp.message(F.text == "💎 Купить подписку")
    async def buy_subscription(message: types.Message):
        await message.answer(
            "🛒 *Выберите кол-во устройств:*\n\n"
            "Это определит, сколько устройств смогут одновременно использовать вашу подписку.",
            reply_markup=get_devices_keyboard(),
            parse_mode="Markdown",
        )
        logging.info(f"👤 Пользователь {message.from_user.id} открыл меню покупки")

    @dp.callback_query(F.data.startswith("devices_"))
    async def devices_selected(callback: types.CallbackQuery):
        devices = int(callback.data.replace("devices_", ""))
        await callback.answer()
        await callback.message.edit_text(
            f"📱 *Вы выбрали: {devices} устройств*\n\n"
            "⏱️ Теперь выберите срок подписки:",
            reply_markup=get_months_keyboard(devices),
            parse_mode="Markdown",
        )
        logging.info(f"👤 Пользователь {callback.from_user.id} выбрал {devices} устройств")

    # ── Покупка подписки: выбор срока → создание платежа ─────────────────────

    @dp.callback_query(F.data.startswith("month_"))
    async def month_selected(callback: types.CallbackQuery):
        telegram_id = callback.from_user.id

        # Парсим callback data: "month_1m_1d" → months=1, devices=1
        parts = callback.data.replace("month_", "").split("_")
        months = int(parts[0][:-1])   # "1m" → 1
        devices = int(parts[1][:-1])  # "1d" → 1

        tariff = TARIFFS.get((months, devices))
        if not tariff:
            await callback.answer("❌ Неверный тариф")
            logging.error(
                f"❌ Неверный тариф {months}м/{devices}д для пользователя {telegram_id}"
            )
            return

        price = tariff["price"]
        days = tariff["days"]
        amount_kopecks = price * 100
        description = f"{months} мес. / {devices} устр."
        metadata = {
            "telegram_id": telegram_id,
            "tariff": f"{months}m_{devices}d",
            "days": days,
            "devices": devices,
        }

        await callback.answer()
        await callback.message.edit_text(
            f"⏳ Создаю платеж...\n\n"
            f"📦 Тариф: *{description}*\n"
            f"💰 Сумма: *{price}₽*",
            parse_mode="Markdown",
        )

        payment_url, payment_id = await create_payment_link(
            amount=amount_kopecks,
            description=description,
            metadata=metadata,
        )

        if not payment_url or not payment_id:
            await callback.message.edit_text(
                "❌ Не удалось создать платеж. Попробуйте позже или обратитесь в поддержку."
            )
            logging.error(f"❌ Ошибка создания платежа для {telegram_id}")
            return

        # Сохраняем платёж в БД — это также служит whitelist'ом для вебхука
        try:
            await save_payment(
                payment_id=payment_id,
                telegram_id=telegram_id,
                amount=amount_kopecks,
                tariff_data={"days": days, "devices": devices},
                status="pending",
            )
            logging.info(f"✅ Платёж {payment_id} сохранён для {telegram_id}")
        except Exception as e:
            logging.error(f"❌ Ошибка сохранения платежа в БД: {e}")

        # Клавиатура: только кнопка оплаты и отмена
        # (проверка статуса убрана — активация происходит автоматически через вебхук)
        payment_keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="💳 Перейти к оплате", url=payment_url)],
                [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_payment")],
            ]
        )

        await callback.message.edit_text(
            f"✅ *Платеж создан!*\n\n"
            f"📦 Тариф: *{description}*\n"
            f"💰 Сумма: *{price}₽*\n"
            f"🆔 ID платежа: `{payment_id}`\n\n"
            "👇 После оплаты вы автоматически получите ссылку на подписку в этом чате.",
            reply_markup=payment_keyboard,
            parse_mode="Markdown",
        )
        logging.info(f"✅ Платёж {payment_id} создан для {telegram_id}, сумма: {price}₽")

    # ── Навигация: назад к выбору устройств ──────────────────────────────────

    @dp.callback_query(F.data == "back_to_devices")
    async def back_to_devices(callback: types.CallbackQuery):
        await callback.answer()
        await callback.message.edit_text(
            "🛒 *Выберите кол-во устройств:*\n\n"
            "Это определит, сколько устройств смогут одновременно использовать вашу подписку.",
            reply_markup=get_devices_keyboard(),
            parse_mode="Markdown",
        )

    # ── Отмена ────────────────────────────────────────────────────────────────

    @dp.callback_query(F.data.startswith("cancel_"))
    async def cancel_action(callback: types.CallbackQuery):
        await callback.message.delete()
        await callback.answer("Действие отменено. Вернитесь в главное меню.")

    # ── Профиль ───────────────────────────────────────────────────────────────

    @dp.message(F.text == "👤 Мой профиль")
    async def profile_button(message: types.Message):
        await message.answer(
            "👤 *Ваш профиль*\n\n"
            "📊 Статус подписки: Активна ✅\n"
            "📅 Дата истечения: —\n"
            "📱 Лимит устройств: —\n\n"
            "⚠️ Функция профиля находится в разработке.",
            parse_mode="Markdown",
        )

    # ── Техподдержка ──────────────────────────────────────────────────────────

    @dp.message(F.text == "⚙️ Техподдержка")
    async def support_button(message: types.Message):
        await message.answer(
            "⚙️ *Техническая поддержка*\n\n"
            "❓ У вас есть вопрос или проблема?\n\n"
            "💬 Напишите в Telegram: @qwertyFall\n\n"
            "Мы ответим вам в кратчайшие сроки!",
            parse_mode="Markdown",
        )

    # ── Пользовательское соглашение ───────────────────────────────────────────

    @dp.message(F.text == "📋 Пользовательское соглашение")
    async def user_agreement(message: types.Message):
        agreement_path = "user_agreement.txt"
        if os.path.exists(agreement_path):
            try:
                await message.answer_document(
                    document=types.FSInputFile(agreement_path),
                    caption="📋 Пользовательское соглашение",
                )
                logging.info(f"📋 Пользователь {message.from_user.id} скачал соглашение")
            except Exception as e:
                logging.error(f"❌ Ошибка при отправке соглашения: {e}")
                await message.answer(
                    "❌ Не удалось загрузить файл соглашения. Обратитесь в техподдержку."
                )
        else:
            await message.answer(
                "📋 *Пользовательское соглашение*\n\n"
                "1️⃣ *Общие положения*\n"
                "Используя этот сервис, вы согласны с условиями настоящего соглашения.\n\n"
                "2️⃣ *Ответственность пользователя*\n"
                "Пользователь несет ответственность за свои действия в интернете.\n\n"
                "3️⃣ *Запрещенное использование*\n"
                "Запрещается использовать сервис для незаконной деятельности.\n\n"
                "4️⃣ *Ограничение ответственности*\n"
                "Мы не несем ответственность за доступ к запрещённому контенту.\n\n"
                "5️⃣ *Изменение условий*\n"
                "Мы оставляем право изменять условия без предварительного уведомления.\n\n"
                "✅ Спасибо за использование нашего сервиса!",
                parse_mode="Markdown",
            )
            logging.info(
                f"📋 Пользователь {message.from_user.id} просмотрел соглашение (текст)"
            )

    # ── Прочие сообщения ──────────────────────────────────────────────────────

    @dp.message()
    async def default_handler(message: types.Message):
        await message.answer(
            "Используйте кнопки меню ниже или напишите /start для перезагрузки меню.",
            reply_markup=main_menu,
        )
        logging.info(
            f"❓ Пользователь {message.from_user.id} отправил неизвестную команду: {message.text}"
        )