"""Модуль для работы с платежной системой ЮKassa"""
import logging
from yookassa import Configuration, Payment
from uuid import uuid4
from config import YOO_SHOP_ID, YOO_SECRET_KEY


# Конфигурация ЮKassa
Configuration.account_id = YOO_SHOP_ID
Configuration.secret_key = YOO_SECRET_KEY


async def create_payment_link(amount: int, description: str, metadata: dict) -> tuple:
    """
    Создает платеж в системе ЮKassa и возвращает ссылку на оплату.
    
    Args:
        amount: Сумма платежа в копейках (целое число)
        description: Описание платежа (например, "1 месяц / 1 устройство")
        metadata: dict с доп. данными (например, {"telegram_id": 123456, "tariff": "1m_1d"})
    
    Returns:
        tuple: (payment_url, payment_id) или (None, None) в случае ошибки
    
    Example:
        >>> url, payment_id = await create_payment_link(15000, "1 мес / 1 устр", {"telegram_id": 123})
        >>> # url: https://yookassa.ru/checkout/....
        >>> # payment_id: "abc123def456"
    """
    try:
        # Генерируем уникальный ID для идемпотентности
        idempotence_key = str(uuid4())
        
        # Создаем платеж через SDK ЮKassa
        payment = Payment.create({
            "amount": {
                "value": amount / 100,  # Конвертируем копейки в рубли
                "currency": "RUB"
            },
            "payment_method_data": {
                "type": "bank_card"
            },
            "confirmation": {
                "type": "redirect",
                "return_url": "https://example.com"  # Будет отправлен пользователю
            },
            "description": description,
            "metadata": metadata,
            "save_payment_method": False
        }, idempotence_key)
        
        payment_id = payment.id
        payment_url = payment.confirmation.confirmation_url
        
        logging.info(f"✅ Платеж создан: {payment_id}, сумма: {amount} коп., ссылка: {payment_url}")
        
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
        dict с информацией о платеже:
        {
            "status": "succeeded" | "pending" | "canceled",
            "amount": 15000,
            "metadata": {...}
        }
        или None в случае ошибки
    """
    try:
        payment = Payment.find_one(payment_id)
        
        status = payment.status
        amount = int(payment.amount.value * 100)  # Конвертируем в копейки
        metadata = payment.metadata if hasattr(payment, 'metadata') else {}
        
        logging.info(f"✅ Статус платежа {payment_id}: {status}")
        
        return {
            "status": status,
            "amount": amount,
            "metadata": metadata,
            "payment_method": payment.payment_method.type if hasattr(payment, 'payment_method') else None
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
        dict с информацией о платеже
    """
    try:
        payment = Payment.find_one(payment_id)
        
        return {
            "id": payment.id,
            "status": payment.status,
            "amount": {
                "value": payment.amount.value,
                "currency": payment.amount.currency
            },
            "description": payment.description if hasattr(payment, 'description') else None,
            "metadata": payment.metadata if hasattr(payment, 'metadata') else {},
            "created_at": str(payment.created_at) if hasattr(payment, 'created_at') else None,
            "payment_method": {
                "type": payment.payment_method.type if hasattr(payment, 'payment_method') else None
            }
        }
        
    except Exception as e:
        logging.error(f"❌ Ошибка при получении информации о платеже: {e}")
        return None
