import logging
from contextlib import suppress
from datetime import datetime, timezone
from pathlib import Path

from aiogram import F, Router, types
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import CommandStart
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup

from ..domain import ManualReview, NotFound

MENU = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="💎 Купить подписку")],
        [KeyboardButton(text="🚀 Пробная подписка"), KeyboardButton(text="👤 Мой профиль")],
        [KeyboardButton(text="📱 Как подключить"), KeyboardButton(text="⚙️ Техподдержка")],
        [KeyboardButton(text="📋 Пользовательское соглашение")],
    ],
    resize_keyboard=True,
)


def keyboard(rows):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=text, callback_data=data) for text, data in row] for row in rows
        ]
    )


def profile_text(subscription, public_url, now_ms):
    if not subscription:
        return "Подписки пока нет. Выберите пробную подписку или платный тариф."
    active = subscription.enabled and subscription.expiry_ms > now_ms
    status = "Активна" if active else "Истекла или отключена"
    if not subscription.synced:
        status = "Ожидает настройки в панели"
    expiry = datetime.fromtimestamp(subscription.expiry_ms / 1000, timezone.utc).strftime(
        "%d.%m.%Y %H:%M UTC"
    )
    text = f"Подписка: {status}\nДействует до: {expiry}\nУстройств: {subscription.devices}"
    if active and subscription.synced:
        text += f"\n\nСсылка подключения:\n{public_url}/sub/{subscription.short_id}"
    return text


async def safe_edit_text(message, text, **kwargs):
    try:
        return await message.edit_text(text, **kwargs)
    except TelegramBadRequest as exc:
        if "message is not modified" in str(exc).lower():
            return None
        raise


def router(service, public_url):
    result = Router()
    result.message.filter(F.chat.type == "private")
    result.callback_query.filter(F.message.chat.type == "private")

    def devices_keyboard():
        return keyboard(
            [
                [(f"{devices} устройств", f"devices_{devices}")]
                for devices in sorted({dev for _, dev in service.tariffs})
            ]
        )

    @result.message(CommandStart())
    async def start(message: types.Message):
        await message.answer("Выберите действие для управления VPN подпиской.", reply_markup=MENU)

    @result.message(F.text == "💎 Купить подписку")
    async def buy(message: types.Message):
        await message.answer("Выберите количество устройств:", reply_markup=devices_keyboard())

    @result.callback_query(F.data.startswith("devices_"))
    async def choose_devices(callback: types.CallbackQuery):
        try:
            devices = int(callback.data.removeprefix("devices_"))
        except ValueError:
            await callback.answer("Неверный тариф")
            return
        rows = [
            [(f"{months} мес. — {tariff['price']} ₽", f"month_{months}m_{devices}d")]
            for (months, dev), tariff in sorted(service.tariffs.items())
            if dev == devices
        ]
        if not rows:
            await callback.answer("Неверный тариф")
            return
        rows.append([("Закрыть", "cancel_buy")])
        await callback.answer()
        await safe_edit_text(callback.message, "Выберите срок:", reply_markup=keyboard(rows))

    @result.callback_query(F.data.startswith("month_"))
    async def purchase(callback: types.CallbackQuery):
        try:
            month, device = callback.data.removeprefix("month_").split("_")
            months, devices = int(month.removesuffix("m")), int(device.removesuffix("d"))
            if (months, devices) not in service.tariffs:
                raise ValueError
        except ValueError:
            await callback.answer("Неверный тариф")
            return
        await callback.answer("Создаю платёж…")
        request_key = f"buy:{callback.from_user.id}:{callback.message.chat.id}:{callback.message.message_id}:{months}:{devices}"
        order = await service.purchase(callback.from_user.id, months, devices, request_key)
        rows = [
            [InlineKeyboardButton(text="Закрыть", callback_data="cancel_payment")],
        ]
        if order.confirmation_url and order.status == "pending":
            rows.insert(0, [InlineKeyboardButton(text="Оплатить картой", url=order.confirmation_url)])
        await safe_edit_text(
            callback.message,
            f"Подписка: {order.days} дней, {order.devices} устройств.\n"
            f"К оплате: {order.amount // 100}.{order.amount % 100:02d} ₽.\n"
            "После оплаты подписка придёт автоматически и появится в профиле.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
        )

    @result.callback_query(F.data.startswith("check_"))
    async def check(callback: types.CallbackQuery):
        await callback.answer("Проверяю оплату…")
        if callback.data.startswith("check_payment_"):
            legacy = await service.store.by_payment(callback.data.removeprefix("check_payment_"))
            if not legacy:
                raise NotFound("Order not found")
            order_id = legacy.id
        else:
            order_id = callback.data.removeprefix("check_")
        order = await service.confirm(order_id, callback.from_user.id, mark_notified=True)
        if order.applied:
            subscription = await service.store.subscription(callback.from_user.id)
            await safe_edit_text(
                callback.message,
                "Оплата получена.\n" + profile_text(subscription, public_url, service.clock()),
            )
        elif order.status == "canceled":
            await safe_edit_text(callback.message, "Платёж отменён. Вы можете выбрать тариф снова.")
        else:
            # Keep the original message/buttons, so another check remains possible.
            await callback.message.answer("Оплата пока не подтверждена. Повторите проверку позже.")

    @result.callback_query(F.data.startswith("cancel_"))
    async def close(callback: types.CallbackQuery):
        await callback.answer()
        await safe_edit_text(callback.message, "Меню закрыто. Уже созданный платёж остаётся действительным.")

    @result.message(F.text == "🚀 Пробная подписка")
    async def trial(message: types.Message):
        subscription = await service.trial(message.from_user.id)
        await message.answer(profile_text(subscription, public_url, service.clock()))

    @result.message(F.text == "👤 Мой профиль")
    async def profile(message: types.Message):
        subscription = await service.store.subscription(message.from_user.id)
        await message.answer(profile_text(subscription, public_url, service.clock()))

    @result.message(F.text == "📱 Как подключить")
    async def instructions(message: types.Message):
        await message.answer(
            "Установите VPN-клиент с поддержкой VLESS Reality, например Hiddify. "
            "Скопируйте ссылку из «Мой профиль» и импортируйте её в клиент как подписку."
        )

    @result.message(F.text == "⚙️ Техподдержка")
    async def support(message: types.Message):
        await message.answer(
            "Свяжитесь с владельцем бота через контакт в его описании. "
            "При проблеме с оплатой укажите время платежа; не отправляйте данные карты."
        )

    @result.message(F.text == "📋 Пользовательское соглашение")
    async def agreement(message: types.Message):
        path = Path(__file__).resolve().parents[2] / "user_agreement.txt"
        await message.answer_document(types.FSInputFile(path), caption="Пользовательское соглашение")

    @result.message()
    async def fallback(message: types.Message):
        await message.answer("Выберите действие в меню.", reply_markup=MENU)

    @result.errors()
    async def error(event: types.ErrorEvent):
        logging.getLogger(__name__).warning("Telegram action failed (%s)", type(event.exception).__name__)
        if isinstance(event.exception, NotFound):
            text = "Платёж не найден. Откройте меню покупки."
        elif isinstance(event.exception, ManualReview):
            text = "Платёж требует сверки. Обратитесь в поддержку."
        else:
            text = (
                "Не удалось завершить действие. Если вы уже оплатили, не оплачивайте повторно: "
                "проверка продолжится автоматически. Проверьте профиль позже."
            )
        message = event.update.message or (
            event.update.callback_query and event.update.callback_query.message
        )
        if message:
            with suppress(Exception):
                await message.answer(text)
        return True

    return result
