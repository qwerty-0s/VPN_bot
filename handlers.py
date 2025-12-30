"""Обработчики сообщений для Telegram бота"""
from aiogram import F, types
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from xui_api import get_users, create_trial_inbound
from config import FRONT_DOMAIN

# Главное меню
main_menu = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="📋 Список пользователей")],
        [KeyboardButton(text="ℹ️ Помощь"), KeyboardButton(text="🚀 Пробная подписка")]
    ],
    resize_keyboard=True
)


def register_handlers(dp):
    """Регистрация всех обработчиков"""
    
    @dp.message(F.text == "/start")
    async def start_handler(message: types.Message):
        await message.answer(
            "👋 Привет! Я помогу тебе управлять VPN.\n\nВыбери действие ниже:",
            reply_markup=main_menu
        )
    
    @dp.message(F.text == "/users")
    async def users_handler(message: types.Message):
        users = await get_users()
        if not users:
            await message.answer("❌ Не удалось получить список пользователей.")
            return

        if "raw" in users:
            await message.answer("⚠️ Ответ не JSON:\n" + users["raw"][:3000])
            return

        reply_text = "📋 Список пользователей:\n\n"
        if "obj" in users:
            for user in users["obj"]:
                remark = user.get("remark", "—")
                enable = "✅" if user.get("enable") else "❌"
                reply_text += f"{enable} {remark}\n"
        else:
            reply_text += str(users)

        await message.answer(reply_text)
    
    @dp.message(F.text == "📋 Список пользователей")
    async def show_users_button(message: types.Message):
        await message.answer("Загружаю список пользователей...")
        users = await get_users()
        if not users:
            await message.answer("❌ Не удалось получить список пользователей.")
            return

        if "raw" in users:
            await message.answer("⚠️ Ответ не JSON:\n" + users["raw"][:3000])
            return

        reply_text = "📋 Список пользователей:\n\n"
        if "obj" in users:
            for user in users["obj"]:
                remark = user.get("remark", "—")
                enable = "✅" if user.get("enable") else "❌"
                reply_text += f"{enable} {remark}\n"
        else:
            reply_text += str(users)

        await message.answer(reply_text)

    @dp.message(F.text == "ℹ️ Помощь")
    async def help_button(message: types.Message):
        await message.answer("ℹ️ Здесь будет помощь и инструкции.")

    @dp.message(F.text == "🚀 Пробная подписка")
    async def trial_button(message: types.Message):
        telegram_id = message.from_user.id
        
        result = await create_trial_inbound(telegram_id)
        
        if not result:
            await message.answer("❌ Не удалось создать пробную подписку.")
            return
        
        if result.get("error") == "already_exists":
            await message.answer(
                "⚠️ У вас уже есть пробная подписка!\n\n"
                "Один пользователь может создать только одну пробную подписку."
            )
            return

        # ✅ Собираем короткую ссылку для подписки (без IP, HTTP вместо HTTPS из-за невалидного сертификата)
        short_id = result["short_id"]
        link = f"https://{FRONT_DOMAIN}/sub/{short_id}"

        await message.answer(
            "✅ Пробная подписка создана!\n\n"
            "Срок действия: *3 дня*\n\n"
            "🔗 Ваша короткая ссылка на подписку (без IP):\n"
            f"`{link}`\n\n"
            "Эту ссылку можно сохранить и использовать позже. "
            "Если IP сервера изменится, ссылка останется рабочей.",
            parse_mode="Markdown"
        )

