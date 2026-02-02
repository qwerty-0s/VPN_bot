"""Модуль для работы с платежной системой ЮKassa"""
import logging
import aiohttp
import base64
import json
from uuid import uuid4
from config import YOO_SHOP_ID, YOO_SECRET_KEY


async def _get_auth_header() -> str:
    """Генерирует Basic Auth header для ЮKassa"""
    credentials = f"{YOO_SHOP_ID}:{YOO_SECRET_KEY}"
    encoded = base64.b64encode(credentials.encode()).decode()
    return f"Basic {encoded}"


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
        auth_header = await _get_auth_header()
        
        headers = {
            "Authorization": auth_header,
            "Content-Type": "application/json",
            "Idempotence-Key": idempotence_key
        }
        
        payload = {
            "amount": {
                "value": f"{amount / 100:.2f}",
                "currency": "RUB"
            },
            "confirmation": {
                "type": "redirect",
                "return_url": "https://example.com"
            },
            "description": description,
            "metadata": metadata,
            "capture": True
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://api.yookassa.ru/v3/payments",
                headers=headers,
                json=payload,
                ssl=True
            ) as resp:
                response_data = await resp.json()
                
                if resp.status == 200:
                    payment_id = response_data.get("id")
                    confirmation = response_data.get("confirmation", {})
                    payment_url = confirmation.get("confirmation_url")
                    
                    logging.info(f"✅ Платеж создан: {payment_id}, сумма: {amount} коп.")
                    return payment_url, payment_id
                else:
                    logging.error(f"❌ Ошибка при создании платежа: {response_data}")
                    return None, None
        
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
        auth_header = await _get_auth_header()
        
        headers = {
            "Authorization": auth_header,
            "Content-Type": "application/json"
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"https://api.yookassa.ru/v3/payments/{payment_id}",
                headers=headers,
                ssl=True
            ) as resp:
                response_data = await resp.json()
                
                if resp.status == 200:
                    status = response_data.get("status")
                    amount = response_data.get("amount", {})
                    metadata = response_data.get("metadata", {})
                    
                    logging.info(f"✅ Статус платежа {payment_id}: {status}")
                    
                    return {
                        "status": status,
                        "amount": int(float(amount.get("value", 0)) * 100),
                        "metadata": metadata,
                        "payment_method": response_data.get("payment_method", {}).get("type")
                    }
                else:
                    logging.error(f"❌ Не удалось получить статус платежа: {response_data}")
                    return None
        
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
        auth_header = await _get_auth_header()
        
        headers = {
            "Authorization": auth_header,
            "Content-Type": "application/json"
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"https://api.yookassa.ru/v3/payments/{payment_id}",
                headers=headers,
                ssl=True
            ) as resp:
                response_data = await resp.json()
                
                if resp.status == 200:
                    return {
                        "id": response_data.get("id"),
                        "status": response_data.get("status"),
                        "amount": response_data.get("amount"),
                        "description": response_data.get("description"),
                        "metadata": response_data.get("metadata"),
                        "created_at": response_data.get("created_at"),
                        "payment_method": response_data.get("payment_method")
                    }
                else:
                    logging.error(f"❌ Ошибка при получении информации о платеже: {response_data}")
                    return None
        
    except Exception as e:
        logging.error(f"❌ Ошибка при получении информации о платеже: {e}")
        return None
