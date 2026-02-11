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


# Inline меню техподдержки
def get_support_keyboard():
    """Создает inline-клавиатуру для техподдержки"""
    keyboard = [
        [InlineKeyboardButton(text="💬 Telegram", url="https://t.me/qwertyFall")],
        [InlineKeyboardButton(text="📧 Email поддержки", url="mailto:vpn_proxima_support@protonmail.com")],
        [InlineKeyboardButton(text="⬅️ Вернуться в меню", callback_data="back_to_menu")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def get_back_to_menu_keyboard():
    """Создает inline-клавиатуру для возврата в меню"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Вернуться в меню", callback_data="back_to_menu")]
    ])


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
            button_text = f"{months} месяца - {price}₽"
            callback_data = f"month_{months}m_{devices}d"
            keyboard.append([InlineKeyboardButton(text=button_text, callback_data=callback_data)])
    
    keyboard.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_devices")])
    keyboard.append([InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_buy")])
    
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


async def send_instruction_with_images(callback, user_short_id: str):
    """
    Отправляет две инструкции-изображения, текст подключения и ссылку на подписку
    """
    try:
        # Отправляем первое изображение инструкции
        instr1_path = 'Instruction1.jpg'
        if os.path.exists(instr1_path):
            await callback.message.answer_photo(
                types.FSInputFile(instr1_path),
                caption="📱 Инструкция подключения - Часть 1"
            )
            logging.info("✅ Первое изображение инструкции отправлено")
        else:
            logging.warning(f"⚠️ Файл {instr1_path} не найден")
        
        # Отправляем второе изображение инструкции
        instr2_path = 'Instruction2.jpg'
        if os.path.exists(instr2_path):
            await callback.message.answer_photo(
                types.FSInputFile(instr2_path),
                caption="📱 Инструкция подключения - Часть 2"
            )
            logging.info("✅ Второе изображение инструкции отправлено")
        else:
            logging.warning(f"⚠️ Файл {instr2_path} не найден")
        
        # Отправляем ссылку на подписку и текст инструкции
        if user_short_id:
            link = f"https://{FRONT_DOMAIN}/sub/{user_short_id}"
            subscription_text = (
                "✅ *Подписка активирована!*\n\n"
                "🔗 Ваша ссылка на подписку:\n"
                f"`{link}`\n\n"
                "📌 *Шаги подключения:*\n"
                "1️⃣ Нажмите на ссылку и она скопируется в буффер обмена\n"
                "2️⃣ Вставьте ссылку в HAPP или любой другой VPN клиент, нажав импорт из буфера\n"
                "3️⃣ Подключитесь к VPN и готово! 🎉"
            )
            await callback.message.answer(subscription_text, parse_mode="Markdown")
            logging.info(f"✅ Инструкция и ссылка отправлены для пользователя с short_id={user_short_id}")
        else:
            logging.error("⚠️ short_id не найден, ссылка не отправлена")
            
    except Exception as e:
        logging.error(f"❌ Ошибка при отправке инструкций: {e}")


async def send_instruction_with_images_message(message, user_short_id: str):
    """
    Отправляет две инструкции-изображения, текст подключения и ссылку на подписку
    Версия для message (для пробной подписки)
    """
    try:
        # Отправляем первое изображение инструкции
        instr1_path = 'Instruction1.jpg'
        if os.path.exists(instr1_path):
            await message.answer_photo(
                types.FSInputFile(instr1_path),
                caption="📱 Инструкция подключения - Часть 1"
            )
            logging.info("✅ Первое изображение инструкции отправлено")
        else:
            logging.warning(f"⚠️ Файл {instr1_path} не найден")
        
        # Отправляем второе изображение инструкции
        instr2_path = 'Instruction2.jpg'
        if os.path.exists(instr2_path):
            await message.answer_photo(
                types.FSInputFile(instr2_path),
                caption="📱 Инструкция подключения - Часть 2"
            )
            logging.info("✅ Второе изображение инструкции отправлено")
        else:
            logging.warning(f"⚠️ Файл {instr2_path} не найден")
        
        # Отправляем ссылку на подписку и текст инструкции
        if user_short_id:
            link = f"https://{FRONT_DOMAIN}/sub/{user_short_id}"
            subscription_text = (
                "✅ *Пробная подписка активирована!*\n\n"
                "⏱️ Срок действия: *3 дня*\n"
                "📱 Лимит устройств: *1*\n\n"
                "🔗 Ваша ссылка на подписку:\n"
                f"`{link}`\n\n"
                "📌 *Шаги подключения:*\n"
                "1️⃣ Нажмите на ссылку и она скопируется в буффер обмена\n"
                "2️⃣ Вставьте ссылку в HAPP или любой другой VPN клиент, нажав импорт из буфера\n"
                "3️⃣ Подключитесь к VPN и готово! 🎉"
            )
            await message.answer(subscription_text, parse_mode="Markdown")
            logging.info(f"✅ Инструкция и ссылка пробной подписки отправлены для пользователя с short_id={user_short_id}")
        else:
            logging.error("⚠️ short_id не найден, ссылка не отправлена")
            
    except Exception as e:
        logging.error(f"❌ Ошибка при отправке инструкций: {e}")


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
        
        # Проверяем, есть ли уже подписка
        user = await get_user_by_telegram_id(telegram_id)
        
        if user:
            await message.answer(
                "⚠️ У вас уже есть подписка!\n\n"
                "Для создания новой пробной подписки свяжитесь с техподдержкой."
            )
            logging.warning(f"⚠️ Пользователь {telegram_id} попытался создать подписку, но она уже существует")
            return
        
        # Создаем пробную подписку (3 дня)
        result = await create_trial_inbound(telegram_id)
        
        if not result or result.get("error"):
            await message.answer("❌ Не удалось создать пробную подписку.")
            logging.error(f"❌ Ошибка создания пробной подписки для {telegram_id}")
            return

        short_id = result["short_id"]
        link = f"https://{FRONT_DOMAIN}/sub/{short_id}"

        # Отправляем две инструкции-изображения, текст и ссылку
        await send_instruction_with_images_message(message, short_id)
        
        logging.info(f"✅ Пробная подписка создана для пользователя {telegram_id}")
    
    # ======================== ПОКУПКА ПОДПИСКИ (ДВУХУРОВНЕВОЕ МЕНЮ) ========================
    
    @dp.message(F.text == "💎 Купить подписку")
    async def buy_subscription(message: types.Message):
        telegram_id = message.from_user.id
        
        await message.answer(
            "🛒 *Выберите кол-во устройств:*\n\n",
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
            "🛒 *Выберите кол-во устройств:*\n\n",
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

            # Получаем пользователя из БД по telegram_id
            try:
                user = await get_user_by_telegram_id(telegram_id)
            except Exception as e:
                user = None
                logging.error(f"❌ Ошибка при получении пользователя {telegram_id} из БД: {e}")

            # ВАЖНО: Если это первая покупка (пользователя нет в БД), создаем подписку
            if not user:
                # Первая покупка — создаем подписку + бонус 3 дня
                total_days = added_days + 3
                
                await callback.message.edit_text(
                    "⏳ Создаю вашу подписку..."
                )
                
                trial_result = await create_trial_inbound(telegram_id)
                
                if not trial_result or trial_result.get("error"):
                    await callback.message.edit_text(
                        "❌ Платеж принят, но не удалось создать подписку.\n\n"
                        "Пожалуйста, свяжитесь с техподдержкой для ручной активации."
                    )
                    logging.error(f"❌ Не удалось создать подписку для {telegram_id}, результат: {trial_result}")
                    return
                
                logging.info(f"✅ Подписка создана для {telegram_id}, inbound_id: {trial_result.get('inbound_id')}")
                
                # Получаем свежие данные пользователя из БД
                import asyncio
                await asyncio.sleep(0.5)  # Небольшая задержка для синхронизации БД
                
                user = await get_user_by_telegram_id(telegram_id)
                if not user:
                    logging.error(f"❌ Не удалось получить данные пользователя {telegram_id} после создания. Проверьте БД.")
                    await callback.message.edit_text(
                        "❌ Ошибка при получении данных из базы. Свяжитесь с техподдержкой."
                    )
                    return
                
                logging.info(f"✅ Данные пользователя получены: telegram_id={telegram_id}, email={user.get('email')}, inbound_id={user.get('inbound_id')}")
                
                # Обновляем подписку с купленными днями + 3 дня бонуса
                email = user.get('email')
                try:
                    logging.info(f"📝 Обновляю подписку: email={email}, added_days={total_days}, devices={devices}")
                    success = await update_client_subscription(email=email, added_days=total_days, new_ip_limit=devices)
                except Exception as e:
                    success = False
                    logging.error(f"❌ Ошибка при вызове update_client_subscription: {e}", exc_info=True)
                
                if not success:
                    await callback.message.edit_text(
                        "⚠️ Подписка создана, но не удалось применить купленные дни.\n\n"
                        "Свяжитесь с техподдержкой."
                    )
                    logging.error(f"❌ Не удалось обновить подписку для {telegram_id}")
                    return
                
                logging.info(f"✅ Первая покупка обработана для {telegram_id}: создана подписка на {total_days} дней (+ 3 дня бонуса)")
            
            else:
                # Это повторная покупка — просто продлеваем подписку
                email = user.get('email')
                
                try:
                    success = await update_client_subscription(email=email, added_days=added_days, new_ip_limit=devices)
                except Exception as e:
                    success = False
                    logging.error(f"❌ Ошибка при вызове update_client_subscription: {e}")
                
                if not success:
                    await callback.message.edit_text(
                        "❌ Платеж принят, но не удалось продлить подписку.\n\n"
                        "Пожалуйста, свяжитесь с техподдержкой."
                    )
                    logging.error(f"❌ Ошибка обновления подписки для {telegram_id}")
                    return
                
                logging.info(f"✅ Подписка продлена для {telegram_id} на {added_days} дней")

            # Отправляем финальное сообщение, инструкцию и ссылку подписки
            await callback.message.edit_text(
                "✅ Оплата прошла успешно! Подписка активирована/продлена.",
                parse_mode="Markdown"
            )

            # Отправляем две инструкции-изображения, текст и ссылку на подписку
            short_id = user.get('short_id')
            await send_instruction_with_images(callback, short_id)

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

            logging.info(f"✅ Платеж {payment_id} успешно принят и подписка обновлена для {telegram_id}")

            
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
            reply_markup=get_back_to_menu_keyboard(),
            parse_mode="Markdown"
        )
        logging.info(f"👤 Пользователь {message.from_user.id} открыл профиль")
    
    # NOTE: instruction button removed — instructions are sent together with subscription after successful payment
    
    # ======================== ТЕХПОДДЕРЖКА ========================
    
    @dp.message(F.text == "⚙️ Техподдержка")
    async def support_button(message: types.Message):
        await message.answer(
            "⚙️ *Техническая поддержка*\n\n"
            "❓ У вас есть вопрос или проблема?\n\n"
            "Свяжитесь с нами одним из способов:",
            reply_markup=get_support_keyboard(),
            parse_mode="Markdown"
        )
        logging.info(f"⚙️ Пользователь {message.from_user.id} открыл раздел техподдержки")
    
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
                        caption="📋 Пользовательское соглашение",
                        reply_markup=get_back_to_menu_keyboard()
                    )
                logging.info(f"📋 Пользователь {message.from_user.id} скачал соглашение")
            except Exception as e:
                logging.error(f"❌ Ошибка при отправке соглашения: {e}")
                await message.answer(
                    "❌ Не удалось загрузить файл соглашения. "
                    "Обратитесь в техподдержку.",
                    reply_markup=get_back_to_menu_keyboard()
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
                reply_markup=get_back_to_menu_keyboard(),
                parse_mode="Markdown"
            )
            logging.info(f"📋 Пользователь {message.from_user.id} просмотрел соглашение (текст)")
    
    # ======================== CALLBACK ОБРАБОТЧИКИ МЕНЮ ========================
    
    @dp.callback_query(F.data == "back_to_menu")
    async def back_to_menu_callback(callback: types.CallbackQuery):
        """Обработчик для возврата в главное меню"""
        await callback.answer()
        await callback.message.edit_text(
            "👋 Главное меню\n\n"
            "✨ Выбери действие ниже:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="💎 Купить подписку", callback_data="buy_subscription")],
                [InlineKeyboardButton(text="🚀 Пробная подписка", callback_data="trial_subscription")],
                [InlineKeyboardButton(text="👤 Мой профиль", callback_data="profile_callback")],
                [InlineKeyboardButton(text="⚙️ Техподдержка", callback_data="support_callback")],
                [InlineKeyboardButton(text="📋 Пользовательское соглашение", callback_data="agreement_callback")]
            ]),
            parse_mode="Markdown"
        )
        logging.info(f"📌 Пользователь {callback.from_user.id} вернулся в главное меню")
    
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

