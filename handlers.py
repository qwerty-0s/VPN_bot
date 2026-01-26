"""Обработчики сообщений для Telegram бота"""
import logging
from aiogram import F, types
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from xui_api import get_users, create_trial_inbound
from yookassa_pay import create_payment_link, check_payment_status
from database import save_payment, update_payment, get_payment_by_id
from config import FRONT_DOMAIN, TARIFFS


# Главное меню
main_menu = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="💎 Купить подписку")],
        [KeyboardButton(text="🚀 Пробная подписка"), KeyboardButton(text="👤 Мой профиль")],
        [KeyboardButton(text="📋 Список пользователей")],
        [KeyboardButton(text="ℹ️ Помощь")]
    ],
    resize_keyboard=True
)


def get_tariffs_keyboard():
    """Создает inline-клавиатуру со списком тарифов"""
    keyboard = []
    
    for (months, devices), tariff_info in TARIFFS.items():
        price = tariff_info['price']
        button_text = f"{months} м. / {devices} уст. - {price}₽"
        callback_data = f"tariff_{months}m_{devices}d"
        
        keyboard.append([InlineKeyboardButton(
            text=button_text,
            callback_data=callback_data
        )])
    
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def register_handlers(dp):
    """Регистрация всех обработчиков"""
    
    @dp.message(F.text == "/start")
    async def start_handler(message: types.Message):
        user_id = message.from_user.id
        user_name = message.from_user.first_name or "пользователь"
        
        await message.answer(
            f"👋 Привет, {user_name}! Я помогу тебе управлять VPN подписками.\n\n"
            "💎 Купи подписку или попробуй бесплатно на 3 дня!",
            reply_markup=main_menu
        )
        logging.info(f"👤 Пользователь {user_id} нажал /start")
    
    # ======================== ПРОБНАЯ ПОДПИСКА ========================
    
    @dp.message(F.text == "🚀 Пробная подписка")
    async def trial_button(message: types.Message):
        telegram_id = message.from_user.id
        
        result = await create_trial_inbound(telegram_id)
        
        if not result:
            await message.answer("❌ Не удалось создать пробную подписку.")
            logging.error(f"❌ Ошибка создания пробной подписки для {telegram_id}")
            return
        
        if result.get("error") == "already_exists":
            await message.answer(
                "⚠️ У вас уже есть пробная подписка!\n\n"
                "Один пользователь может создать только одну пробную подписку."
            )
            logging.warning(f"⚠️ Пользователь {telegram_id} попытался создать вторую пробную подписку")
            return

        short_id = result["short_id"]
        link = f"https://{FRONT_DOMAIN}/sub/{short_id}"

        await message.answer(
            "✅ Пробная подписка создана!\n\n"
            "Срок действия: *3 дня*\n"
            "Лимит устройств: *1*\n\n"
            "🔗 Ваша ссылка на подписку:\n"
            f"`{link}`\n\n"
            "Эту ссылку можно сохранить и использовать позже. "
            "Если IP сервера изменится, ссылка останется рабочей.",
            parse_mode="Markdown"
        )
        logging.info(f"✅ Пробная подписка создана для пользователя {telegram_id}")
    
    # ======================== ПОКУПКА ПОДПИСКИ ========================
    
    @dp.message(F.text == "💎 Купить подписку")
    async def buy_subscription(message: types.Message):
        telegram_id = message.from_user.id
        
        await message.answer(
            "Выберите нужный тариф:\n\n"
            "🔹 *Сетка тарифов:*\n"
            "• 1 месяц: 150₽ (1 устр.), 200₽ (3 устр.), 250₽ (5 устр.)\n"
            "• 3 месяца: 400₽ (1 устр.), 500₽ (3 устр.), 600₽ (5 устр.)\n"
            "• 6 месяцев: 700₽ (1 устр.), 850₽ (3 устр.), 1000₽ (5 устр.)",
            reply_markup=get_tariffs_keyboard(),
            parse_mode="Markdown"
        )
        logging.info(f"👤 Пользователь {telegram_id} открыл меню тарифов")
    
    @dp.callback_query(F.data.startswith("tariff_"))
    async def tariff_selected(callback: types.CallbackQuery):
        telegram_id = callback.from_user.id
        
        # Парсим callback data: "tariff_1m_1d" -> months=1, devices=1
        data_parts = callback.data.replace("tariff_", "").split("_")
        months = int(data_parts[0][:-1])  # "1m" -> 1
        devices = int(data_parts[1][:-1])  # "1d" -> 1
        
        # Получаем информацию о тарифе
        tariff = TARIFFS.get((months, devices))
        if not tariff:
            await callback.answer("❌ Неверный тариф")
            logging.error(f"❌ Неверный тариф: {months}м_{devices}d для пользователя {telegram_id}")
            return
        
        price = tariff['price']
        days = tariff['days']
        amount_in_kopecks = price * 100  # Конвертируем в копейки
        
        # Описание платежа
        description = f"{months} мес. / {devices} устр."
        
        # Метаданные для платежа
        metadata = {
            "telegram_id": telegram_id,
            "tariff": f"{months}m_{devices}d",
            "days": days,
            "devices": devices
        }
        
        await callback.answer()
        
        # Отправляем сообщение о создании платежа
        await callback.message.edit_text(
            f"⏳ Создаю платеж...\n\n"
            f"Тариф: *{description}*\n"
            f"Сумма: *{price}₽*",
            parse_mode="Markdown"
        )
        
        # Создаем платеж через ЮKassa
        payment_url, payment_id = await create_payment_link(
            amount=amount_in_kopecks,
            description=description,
            metadata=metadata
        )
        
        if not payment_url or not payment_id:
            await callback.message.edit_text(
                "❌ Не удалось создать платеж. Попробуйте позже или обратитесь в поддержку."
            )
            logging.error(f"❌ Ошибка создания платежа для пользователя {telegram_id}")
            return
        
        # Сохраняем платеж в БД
        try:
            await save_payment(
                payment_id=payment_id,
                telegram_id=telegram_id,
                amount=amount_in_kopecks,
                tariff_data={"days": days, "devices": devices},
                status="pending"
            )
            logging.info(f"✅ Платеж {payment_id} сохранен в БД для пользователя {telegram_id}")
        except Exception as e:
            logging.error(f"❌ Ошибка при сохранении платежа в БД: {e}")
        
        # Создаем inline-клавиатуру с кнопками
        payment_keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text="💳 Перейти к оплате",
                url=payment_url
            )],
            [InlineKeyboardButton(
                text="✅ Проверить оплату",
                callback_data=f"check_payment_{payment_id}"
            )],
            [InlineKeyboardButton(
                text="❌ Отмена",
                callback_data="cancel_payment"
            )]
        ])
        
        await callback.message.edit_text(
            f"✅ Платеж создан!\n\n"
            f"Тариф: *{description}*\n"
            f"Сумма: *{price}₽*\n"
            f"ID платежа: `{payment_id}`\n\n"
            "Нажмите кнопку ниже для оплаты:",
            reply_markup=payment_keyboard,
            parse_mode="Markdown"
        )
        
        logging.info(f"✅ Платеж {payment_id} создан для пользователя {telegram_id}, сумма: {price}₽")
    
    @dp.callback_query(F.data.startswith("check_payment_"))
    async def check_payment(callback: types.CallbackQuery):
        telegram_id = callback.from_user.id
        payment_id = callback.data.replace("check_payment_", "")
        
        await callback.answer("⏳ Проверяю статус платежа...")
        
        # Проверяем статус в ЮKassa
        payment_info = await check_payment_status(payment_id)
        
        if not payment_info:
            await callback.message.edit_text(
                "❌ Не удалось проверить статус платежа. Попробуйте позже."
            )
            logging.error(f"❌ Ошибка при проверке статуса платежа {payment_id}")
            return
        
        status = payment_info.get('status')
        
        if status == 'succeeded':
            # Платеж успешен! Обновляем статус в БД
            await update_payment(payment_id, status='succeeded')
            
            await callback.message.edit_text(
                "✅ *Платеж успешно принят!*\n\n"
                "Ваша подписка активирована. "
                "Проверьте команду /profile для просмотра деталей.",
                parse_mode="Markdown"
            )
            
            logging.info(f"✅ Платеж {payment_id} успешно принят для пользователя {telegram_id}")
            
        elif status == 'pending':
            await callback.message.edit_text(
                "⏳ Платеж еще в процессе обработки.\n\n"
                "Попробуйте проверить позже.",
                parse_mode="Markdown"
            )
            
        elif status == 'canceled':
            await callback.message.edit_text(
                "❌ Платеж отменен или истек срок действия.\n\n"
                "Вернитесь в меню и попробуйте снова.",
                parse_mode="Markdown"
            )
            logging.warning(f"⚠️ Платеж {payment_id} отменен для пользователя {telegram_id}")
    
    @dp.callback_query(F.data == "cancel_payment")
    async def cancel_payment(callback: types.CallbackQuery):
        await callback.message.delete()
        await callback.answer("Платеж отменен. Вернитесь в главное меню.")
    
    # ======================== ПРОФИЛЬ ========================
    
    @dp.message(F.text == "👤 Мой профиль")
    async def profile_button(message: types.Message):
        await message.answer(
            "👤 Профиль (функция в разработке)\n\n"
            "Здесь будет информация о вашей подписке:\n"
            "• Статус\n"
            "• Дата истечения\n"
            "• Лимит устройств",
            reply_markup=main_menu
        )
    
    # ======================== СПИСОК ПОЛЬЗОВАТЕЛЕЙ ========================
    
    @dp.message(F.text == "📋 Список пользователей")
    async def show_users_button(message: types.Message):
        await message.answer("⏳ Загружаю список пользователей...")
        users = await get_users()
        
        if not users:
            await message.answer("❌ Не удалось получить список пользователей.")
            return

        if "raw" in users:
            await message.answer("⚠️ Ответ не JSON:\n" + users["raw"][:3000])
            return

        reply_text = "📋 Список пользователей в XUI:\n\n"
        if "obj" in users:
            for user in users["obj"]:
                remark = user.get("remark", "—")
                enable = "✅" if user.get("enable") else "❌"
                reply_text += f"{enable} {remark}\n"
        else:
            reply_text += str(users)

        await message.answer(reply_text)
        logging.info(f"📋 Пользователь {message.from_user.id} просмотрел список пользователей")
    
    # ======================== ПОМОЩЬ ========================
    
    @dp.message(F.text == "ℹ️ Помощь")
    async def help_button(message: types.Message):
        await message.answer(
            "ℹ️ *Справка*\n\n"
            "🚀 *Пробная подписка*\n"
            "• Бесплатно на 3 дня\n"
            "• Лимит: 1 устройство\n\n"
            "💎 *Купить подписку*\n"
            "• Выберите нужный тариф\n"
            "• Оплатите через ЮKassa\n"
            "• Используйте подписку сразу\n\n"
            "📱 *Подключение*\n"
            "1. Скачайте Hiddify, v2rayNG или V2Box\n"
            "2. Импортируйте конфиг со своей ссылки\n"
            "3. Подключитесь и наслаждайтесь VPN!\n\n"
            "Если у вас есть вопросы, напишите боту /help",
            parse_mode="Markdown"
        )

