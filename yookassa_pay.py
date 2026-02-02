"""Модуль для работы с платежной системой ЮKassa"""
import logging
from yookassa import Configuration, Payment
from uuid import uuid4
from config import YOO_SHOP_ID, YOO_SECRET_KEY
import asyncio
from concurrent.futures import ThreadPoolExecutor

# Конфигурация ЮKassa
Configuration.account_id = YOO_SHOP_ID
Configuration.secret_key = YOO_SECRET_KEY

# Пул потоков для синхронных операций ЮKassa
executor = ThreadPoolExecutor(max_workers=3)


async def create_payment_link(amount: int, description: str, metadata: dict) -> tuple:
    """
    Создает платеж в системе ЮKassa и возвращает ссылку на оплату.
    
    Args:
        amount: Сумма платежа в копейках (целое число)
        description: Описание платежа (например, "1 месяц / 1 устройство")
        metadata: dict с доп. данными (например, {"telegram_id": 123456, "tariff": "1m_1d"})
    
    Returns:
        tuple: (payment_url, payment_id) или (None, None) в случае ошибки
    """
    try:
        idempotence_key = str(uuid4())
        
        # Синхронный вызов SDK в отдельном потоке
        loop = asyncio.get_event_loop()
        payment = await loop.run_in_executor(
            executor,
            lambda: Payment.create({
                "amount": {
                    "value": amount / 100,
                    "currency": "RUB"
                },
                "confirmation": {
                    "type": "redirect",
                    "return_url": "https://example.com"
                },
                "description": description,
                "metadata": metadata,
                "capture": True
            }, idempotence_key)
        )
        
        payment_id = payment.id
        payment_url = payment.confirmation.confirmation_url
        
        logging.info(f"✅ Платеж создан: {payment_id}, сумма: {amount} коп.")
        return payment_url, payment_id
        
    except Exception as e:
        logging.error(f"❌ Ошибка при создании платежа: {e}")
        return None, None


async def check_payment_status(payment_id: str) -> dict:
    """
    Проверяет статус платежа в системе ЮKassa.
    
    Args:
        payment_id: ID платежа в системе ЮKassa
    
    Returns:
        dict с информацией о платеже или None при ошибке
    """
    try:
        loop = asyncio.get_event_loop()
        payment = await loop.run_in_executor(
            executor,
            lambda: Payment.find_one(payment_id)
        )
        
        status = payment.status
        amount = payment.amount
        metadata = payment.metadata if hasattr(payment, 'metadata') else {}
        
        logging.info(f"✅ Статус платежа {payment_id}: {status}")
        
        return {
            "status": status,
            "amount": int(float(amount.value) * 100) if hasattr(amount, 'value') else 0,
            "metadata": metadata,
            "payment_method": payment.payment_method.type if hasattr(payment, 'payment_method') and hasattr(payment.payment_method, 'type') else None
        }
        
    except Exception as e:
        logging.error(f"❌ Ошибка при проверке статуса платежа: {e}")
        return None


async def get_payment_info(payment_id: str):
    """
    Получает полную информацию о платеже.
    
    Args:
        payment_id: ID платежа в системе ЮKassa
    
    Returns:
        dict с информацией о платеже или None при ошибке
    """
    try:
        loop = asyncio.get_event_loop()
        payment = await loop.run_in_executor(
            executor,
            lambda: Payment.find_one(payment_id)
        )
        
        return {
            "id": payment.id,
            "status": payment.status,
            "amount": {
                "value": payment.amount.value if hasattr(payment.amount, 'value') else 0,
                "currency": payment.amount.currency if hasattr(payment.amount, 'currency') else "RUB"
            },
            "description": payment.description if hasattr(payment, 'description') else None,
            "metadata": payment.metadata if hasattr(payment, 'metadata') else {},
            "created_at": str(payment.created_at) if hasattr(payment, 'created_at') else None,
            "payment_method": {
                "type": payment.payment_method.type if hasattr(payment, 'payment_method') and hasattr(payment.payment_method, 'type') else None
            }
        }
        
    except Exception as e:
        logging.error(f"❌ Ошибка при получении информации о платеже: {e}")
        return None
