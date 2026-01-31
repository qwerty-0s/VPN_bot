"""Обработчики сообщений для Telegram бота"""
import logging
from aiogram import F, types
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from xui_api import create_trial_inbound, update_client_subscription
from yookassa_pay import create_payment_link, check_payment_status
from database import save_payment, update_payment, get_user_by_telegram_id
from config import FRONT_DOMAIN, TARIFFS
import os


# Главное меню (для обычных пользователей)
main_menu = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="💎 Купить подписку")],
        [KeyboardButton(text="🚀 Пробная подписка"), KeyboardButton(text="👤 Мой профиль")],
        [KeyboardButton(text="⚙️ Техподдержка")],
        [KeyboardButton(text="📋 Пользовательское соглашение")]
    ],
    resize_keyboard=True
)


def get_devices_keyboard():
    """Создает inline-клавиатуру для выбора кол-ва устройств"""
    keyboard = [
        [InlineKeyboardButton(text="1 устройство", callback_data="devices_1")],
        [InlineKeyboardButton(text="3 устройства", callback_data="devices_3")],
        [InlineKeyboardButton(text="5 устройств", callback_data="devices_5")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_buy")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def get_months_keyboard(devices: int):
    """Создает inline-клавиатуру для выбора срока на основе выбранных устройств"""
    keyboard = []
    
    # Ищем все тарифы для выбранного кол-ва устройств
    for (months, dev), tariff_info in sorted(TARIFFS.items()):
        if dev == devices:
            price = tariff_info['price']
            button_text = f"{months} месяц(-а/-ев) - {price}₽"
            callback_data = f"month_{months}m_{devices}d"
            keyboard.append([InlineKeyboardButton(text=button_text, callback_data=callback_data)])
    
    keyboard.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_devices")])
    keyboard.append([InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_buy")])
    
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def register_handlers(dp):
    """Регистрация всех обработчиков"""
    
    @dp.message(F.text == "/start")
    async def start_handler(message: types.Message):
        user_id = message.from_user.id
        user_name = message.from_user.first_name or "пользователь"
        
        await message.answer(
            f"👋 Привет, {user_name}! 🎉\n\n"
            "Я помогу тебе управлять VPN подписками.\n\n"
            "✨ Выбери действие ниже:",
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
                "Один пользователь может создать только одну пробную подписку.\n\n"
                "Для продления подписки выберите платный тариф в меню 💎 Купить подписку"
            )
            logging.warning(f"⚠️ Пользователь {telegram_id} попытался создать вторую пробную подписку")
            return

        short_id = result["short_id"]
        link = f"https://{FRONT_DOMAIN}/sub/{short_id}"

        await message.answer(
            "✅ *Пробная подписка создана!*\n\n"
            "⏱️ Срок действия: *3 дня*\n"
            "📱 Лимит устройств: *1*\n\n"
            "🔗 Ваша ссылка на подписку:\n"
            f"`{link}`\n\n"
            "💡 Эту ссылку можно сохранить и использовать позже. "
            "Если IP сервера изменится, ссылка останется рабочей.",
            parse_mode="Markdown"
        )
        logging.info(f"✅ Пробная подписка создана для пользователя {telegram_id}")
    
    # ======================== ПОКУПКА ПОДПИСКИ (ДВУХУРОВНЕВОЕ МЕНЮ) ========================
    
    @dp.message(F.text == "💎 Купить подписку")
    async def buy_subscription(message: types.Message):
        telegram_id = message.from_user.id
        
        await message.answer(
            "🛒 *Выберите кол-во устройств:*\n\n"
            "Это определит, сколько девайсов смогут одновременно использовать вашу подписку.",
            reply_markup=get_devices_keyboard(),
            parse_mode="Markdown"
        )
        logging.info(f"👤 Пользователь {telegram_id} открыл меню покупки подписки")
    
    # Уровень 1: Выбор кол-ва устройств
    @dp.callback_query(F.data.startswith("devices_"))
    async def devices_selected(callback: types.CallbackQuery):
        telegram_id = callback.from_user.id
        devices = int(callback.data.replace("devices_", ""))
        
        await callback.answer()
        await callback.message.edit_text(
            f"📱 *Вы выбрали: {devices} устройств*\n\n"
            "⏱️ Теперь выберите срок подписки:",
            reply_markup=get_months_keyboard(devices),
            parse_mode="Markdown"
        )
        logging.info(f"👤 Пользователь {telegram_id} выбрал {devices} устройств")
    
    # Уровень 2: Выбор срока (месяцев)
    @dp.callback_query(F.data.startswith("month_"))
    async def month_selected(callback: types.CallbackQuery):
        telegram_id = callback.from_user.id
        
        # Парсим callback data: "month_1m_1d" -> months=1, devices=1
        data_parts = callback.data.replace("month_", "").split("_")
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
            f"📦 Тариф: *{description}*\n"
            f"💰 Сумма: *{price}₽*",
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
            f"✅ *Платеж создан!*\n\n"
            f"📦 Тариф: *{description}*\n"
            f"💰 Сумма: *{price}₽*\n"
            f"🆔 ID платежа: `{payment_id}`\n\n"
            "👇 Нажмите кнопку ниже для оплаты:",
            reply_markup=payment_keyboard,
            parse_mode="Markdown"
        )
        
        logging.info(f"✅ Платеж {payment_id} создан для пользователя {telegram_id}, сумма: {price}₽")
    
    # Кнопка "Назад" в меню месяцев
    @dp.callback_query(F.data == "back_to_devices")
    async def back_to_devices(callback: types.CallbackQuery):
        await callback.answer()
        await callback.message.edit_text(
            "🛒 *Выберите кол-во устройств:*\n\n"
            "Это определит, сколько девайсов смогут одновременно использовать вашу подписку.",
            reply_markup=get_devices_keyboard(),
            parse_mode="Markdown"
        )
    
    # Проверка статуса платежа
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

            # Извлекаем метаданные тарифа
            metadata = payment_info.get('metadata') or {}
            added_days = int(metadata.get('days', 0))
            devices = int(metadata.get('devices', 1))

            # Получаем email пользователя из БД по telegram_id
            try:
                user = await get_user_by_telegram_id(telegram_id)
            except Exception as e:
                user = None
                logging.error(f"❌ Ошибка при получении пользователя {telegram_id} из БД: {e}")

            if not user:
                # Платеж принят, но нет записи пользователя для обновления XUI
                await callback.message.edit_text(
                    "✅ Платеж принят, но не удалось найти вашу запись в базе для активации подписки.\n\n"
                    "Пожалуйста, свяжитесь с техподдержкой для ручной активации.",
                    parse_mode="Markdown"
                )
                logging.error(f"❌ Платеж {payment_id} получен, но отсутствует пользователь {telegram_id} в БД")
                return

            email = user.get('email')

            # Обновляем подписку в XUI
            try:
                success = await update_client_subscription(email=email, added_days=added_days, new_ip_limit=devices)
            except Exception as e:
                success = False
                logging.error(f"❌ Ошибка при вызове update_client_subscription: {e}")

            if success:
                # Отправляем финальное сообщение, инструкцию и ключ доступа
                await callback.message.edit_text(
                    "✅ Оплата прошла успешно! Подписка продлена/активирована.",
                    parse_mode="Markdown"
                )

                # Отправляем инструкцию в виде изображения, если есть
                try:
                    instr_path = 'instruction.jpg'
                    if os.path.exists(instr_path):
                        await callback.message.answer_photo(types.FSInputFile(instr_path), caption="Инструкция по подключению")
                except Exception as e:
                    logging.warning(f"⚠️ Не удалось отправить instruction.jpg: {e}")

                # Отправляем пользовательское соглашение в формате PDF если есть, иначе TXT
                try:
                    pdf_path = 'user_agreement.pdf'
                    txt_path = 'user_agreement.txt'
                    if os.path.exists(pdf_path):
                        await callback.message.answer_document(types.FSInputFile(pdf_path), caption="Пользовательское соглашение")
                    elif os.path.exists(txt_path):
                        await callback.message.answer_document(types.FSInputFile(txt_path), caption="Пользовательское соглашение")
                except Exception as e:
                    logging.warning(f"⚠️ Не удалось отправить пользовательское соглашение: {e}")

                # Отправляем ключ доступа и порт
                try:
                    key_text = f"🔑 Ваш ключ: {user.get('uuid')}\n🔌 Порт: {user.get('port')}"
                    await callback.message.answer(key_text)
                except Exception as e:
                    logging.error(f"❌ Ошибка при отправке ключа пользователю {telegram_id}: {e}")

                logging.info(f"✅ Платеж {payment_id} успешно принят и подписка обновлена для {telegram_id}")
            else:
                # Ошибка при обновлении в панели
                await callback.message.edit_text(
                    "✅ Платеж прошел, но не удалось автоматически активировать подписку в панели.\n\n"
                    "Мы уведомили техподдержку — свяжитесь с ней для активации.",
                    parse_mode="Markdown"
                )
                logging.error(f"❌ Не удалось обновить подписку в XUI для {email} после платежа {payment_id}")
            
        elif status == 'pending':
            await callback.message.edit_text(
                "⏳ *Платеж еще в процессе обработки.*\n\n"
                "Попробуйте проверить позже.",
                parse_mode="Markdown"
            )
            
        elif status == 'canceled':
            await callback.message.edit_text(
                "❌ *Платеж отменен или истек срок действия.*\n\n"
                "Вернитесь в меню и попробуйте снова.",
                parse_mode="Markdown"
            )
            logging.warning(f"⚠️ Платеж {payment_id} отменен для пользователя {telegram_id}")
    
    # Отмена платежа / покупки
    @dp.callback_query(F.data.startswith("cancel_"))
    async def cancel_action(callback: types.CallbackQuery):
        await callback.message.delete()
        await callback.answer("Действие отменено. Вернитесь в главное меню.")
    
    # ======================== ПРОФИЛЬ ========================
    
    @dp.message(F.text == "👤 Мой профиль")
    async def profile_button(message: types.Message):
        await message.answer(
            "👤 *Ваш профиль*\n\n"
            "📊 Статус подписки: Активна ✅\n"
            "📅 Дата истечения: -\n"
            "📱 Лимит устройств: -\n\n"
            "⚠️ Функция профиля находится в разработке.\n\n"
            "Проверьте вашу подписку через кнопку проверки платежа.",
            parse_mode="Markdown"
        )
    
    # NOTE: instruction button removed — instructions are sent together with subscription after successful payment
    
    # ======================== ТЕХПОДДЕРЖКА ========================
    
    @dp.message(F.text == "⚙️ Техподдержка")
    async def support_button(message: types.Message):
        support_keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text="💬 Написать в Telegram",
                url="https://t.me/your_support_username"  # Замени на реальный юзер
            )],
            [InlineKeyboardButton(
                text="📧 Email поддержки",
                url="mailto:support@example.com"  # Замени на реальный email
            )]
        ])
        
        await message.answer(
            "⚙️ *Техническая поддержка*\n\n"
            "❓ У вас есть вопрос или проблема?\n\n"
            "Свяжитесь с нами одним из способов:",
            reply_markup=support_keyboard,
            parse_mode="Markdown"
        )
    
    # ======================== ПОЛЬЗОВАТЕЛЬСКОЕ СОГЛАШЕНИЕ ========================
    
    @dp.message(F.text == "📋 Пользовательское соглашение")
    async def user_agreement(message: types.Message):
        # Проверяем, существует ли файл с соглашением
        agreement_path = "user_agreement.txt"
        
        if os.path.exists(agreement_path):
            try:
                with open(agreement_path, 'rb') as file:
                    await message.answer_document(
                        document=types.FSInputFile(agreement_path),
                        caption="📋 Пользовательское соглашение"
                    )
                logging.info(f"📋 Пользователь {message.from_user.id} скачал соглашение")
            except Exception as e:
                logging.error(f"❌ Ошибка при отправке соглашения: {e}")
                await message.answer(
                    "❌ Не удалось загрузить файл соглашения. "
                    "Обратитесь в техподдержку."
                )
        else:
            # Если файла нет, отправляем текст в сообщении
            await message.answer(
                "📋 *Пользовательское соглашение*\n\n"
                "1️⃣ *Общие положения*\n"
                "Используя этот сервис, вы согласны с условиями настоящего соглашения.\n\n"
                "2️⃣ *Ответственность пользователя*\n"
                "Пользователь несет ответственность за свои действия в интернете.\n\n"
                "3️⃣ *Запрещенное использование*\n"
                "Запрещается использовать сервис для незаконной деятельности.\n\n"
                "4️⃣ *Ограничение ответственности*\n"
                "Мы не несем ответственность за доступ к запрещенному контенту.\n\n"
                "5️⃣ *Изменение условий*\n"
                "Мы оставляем право изменять условия без предварительного уведомления.\n\n"
                "✅ Спасибо за использование нашего сервиса!",
                parse_mode="Markdown"
            )
            logging.info(f"📋 Пользователь {message.from_user.id} просмотрел соглашение (текст)")
    
    # ======================== ОБРАБОТКА ОСТАЛЬНЫХ СООБЩЕНИЙ ========================
    
    @dp.message()
    async def default_handler(message: types.Message):
        """Обработчик для остальных сообщений"""
        await message.answer(
            "😕 Я не понимаю эту команду.\n\n"
            "Используйте кнопки меню ниже или напишите /start для перезагрузки меню.",
            reply_markup=main_menu
        )
        logging.info(f"❓ Пользователь {message.from_user.id} отправил неизвестную команду: {message.text}")

