from dataclasses import replace
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramNotFound

from vpn_bot.domain import UnreachableUser
from vpn_bot.transport.telegram import profile_text, router, safe_edit_text


async def test_safe_edit_text_success_and_ignore_not_modified():
    msg = MagicMock()
    msg.edit_text = AsyncMock(return_value="edited")
    assert await safe_edit_text(msg, "new") == "edited"

    msg.edit_text = AsyncMock(
        side_effect=TelegramBadRequest(
            method="editMessageText", message="Bad Request: message is not modified: ..."
        )
    )
    assert await safe_edit_text(msg, "same") is None

    msg.edit_text = AsyncMock(
        side_effect=TelegramBadRequest(method="editMessageText", message="Bad Request: chat not found")
    )
    with pytest.raises(TelegramBadRequest):
        await safe_edit_text(msg, "diff")


async def test_telegram_check_marks_notified_on_applied(service):
    order = await service.purchase(70, 1, 1, "tg-check-1")
    service.gateway.succeed(order)

    r = router(service, "https://bot.example")
    check_handler = next(h.callback for h in r.callback_query.handlers if h.callback.__name__ == "check")

    callback = MagicMock()
    callback.data = f"check_{order.id}"
    callback.from_user.id = 70
    callback.answer = AsyncMock()
    callback.message = MagicMock()
    callback.message.edit_text = AsyncMock()

    await check_handler(callback)

    assert callback.answer.await_count == 1
    assert callback.message.edit_text.await_count == 1
    updated_order = await service.store.order(order.id)
    assert updated_order.applied is True
    assert updated_order.notified is True


async def test_telegram_check_canceled_and_pending(service):
    order = await service.purchase(71, 1, 1, "tg-check-2")
    r = router(service, "https://bot.example")
    check_handler = next(h.callback for h in r.callback_query.handlers if h.callback.__name__ == "check")

    # Pending check
    callback = MagicMock()
    callback.data = f"check_{order.id}"
    callback.from_user.id = 71
    callback.answer = AsyncMock()
    callback.message = MagicMock()
    callback.message.answer = AsyncMock()
    callback.message.edit_text = AsyncMock()

    await check_handler(callback)
    assert callback.message.answer.await_count == 1
    assert "Оплата пока не подтверждена" in callback.message.answer.call_args[0][0]

    # Canceled check
    service.gateway.payments[order.id] = replace(service.gateway.payments[order.id], status="canceled")
    await check_handler(callback)
    assert callback.message.edit_text.await_count == 1
    assert "Платёж отменён" in callback.message.edit_text.call_args[0][0]


async def test_app_send_and_service_notify(service):
    o1 = await service.purchase(72, 1, 1, "tg-n-1")
    service.gateway.succeed(o1)
    await service.confirm(o1.id, mark_notified=False)

    o2 = await service.purchase(73, 1, 1, "tg-n-2")
    service.gateway.succeed(o2)
    await service.confirm(o2.id, mark_notified=False)

    bot = MagicMock()

    async def mock_send(chat_id, text):
        if chat_id == 72:
            return MagicMock()
        if chat_id == 73:
            raise TelegramForbiddenError(method="sendMessage", message="Bot blocked")

    bot.send_message = AsyncMock(side_effect=mock_send)

    async def send(subscription):
        try:
            await bot.send_message(
                subscription.telegram_id,
                "Оплата получена.\n" + profile_text(subscription, "https://bot.example", service.clock()),
            )
        except (TelegramForbiddenError, TelegramNotFound) as exc:
            raise UnreachableUser(str(exc)) from exc

    await service.notify(send)

    assert (await service.store.order(o1.id)).notified is True
    assert (await service.store.order(o2.id)).notified is True


async def test_telegram_error_handler_suppresses_answer_failure(service):
    r = router(service, "https://bot.example")
    error_handler = next(h.callback for h in r.errors.handlers if h.callback.__name__ == "error")

    msg = MagicMock()
    msg.answer = AsyncMock(side_effect=TelegramForbiddenError(method="sendMessage", message="bot blocked"))
    event = MagicMock()
    event.exception = RuntimeError("network issue")
    event.update = MagicMock()
    event.update.message = msg
    event.update.callback_query = None

    handled = await error_handler(event)
    assert handled is True


async def test_telegram_purchase_omits_manual_check_button(service):
    r = router(service, "https://bot.example")
    purchase_handler = next(
        h.callback for h in r.callback_query.handlers if h.callback.__name__ == "purchase"
    )

    callback = MagicMock()
    callback.data = "month_1m_1d"
    callback.from_user.id = 75
    callback.answer = AsyncMock()
    callback.message = MagicMock()
    callback.message.chat.id = 75
    callback.message.message_id = 10
    callback.message.edit_text = AsyncMock()

    await purchase_handler(callback)

    assert callback.message.edit_text.await_count == 1
    markup = callback.message.edit_text.call_args.kwargs["reply_markup"]
    button_texts = [btn.text for row in markup.inline_keyboard for btn in row]
    assert button_texts == ["Оплатить картой", "Закрыть"]
