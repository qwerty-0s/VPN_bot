from urllib.parse import quote, urlparse

from aiohttp import ClientError, ClientSession, ClientTimeout, encode_basic_auth

from ..domain import InvalidPayment, RemotePayment, RetryLater, kopecks


class YooKassa:
    def __init__(
        self, session: ClientSession, shop_id: str, secret: str, base_url="https://api.yookassa.ru/v3"
    ):
        self.session, self.base_url = session, base_url.rstrip("/")
        self.authorization = encode_basic_auth(shop_id, secret)

    async def _request(self, method, path, **kwargs):
        try:
            headers = {**kwargs.pop("headers", {}), "Authorization": self.authorization}
            async with self.session.request(
                method,
                self.base_url + path,
                headers=headers,
                timeout=ClientTimeout(total=15),
                allow_redirects=False,
                **kwargs,
            ) as response:
                if response.status not in (200, 201):
                    raise RetryLater(f"YooKassa HTTP {response.status}")
                data = await response.json()
            confirmation_url = (data.get("confirmation") or {}).get("confirmation_url")
            if confirmation_url:
                parsed = urlparse(confirmation_url)
                if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
                    raise InvalidPayment("Invalid payment confirmation URL")
            if type(data["paid"]) is not bool or type(data["test"]) is not bool:
                raise InvalidPayment("Invalid payment flags")
            if (
                not isinstance(data["id"], str)
                or not data["id"]
                or not isinstance(data.get("metadata"), dict)
            ):
                raise InvalidPayment("Invalid payment identity")
            return RemotePayment(
                data["id"],
                data["status"],
                kopecks(data["amount"]["value"]),
                data["amount"]["currency"],
                data["paid"],
                data["test"],
                str(data["recipient"]["account_id"]),
                data["metadata"],
                confirmation_url,
            )
        except (ClientError, TimeoutError) as exc:
            raise RetryLater("YooKassa unavailable") from exc
        except (KeyError, TypeError, ValueError) as exc:
            raise InvalidPayment("Malformed YooKassa response") from exc

    async def create(self, order):
        payload = {
            "amount": {"value": f"{order.amount // 100}.{order.amount % 100:02d}", "currency": "RUB"},
            "capture": True,
            "payment_method_data": {"type": "bank_card"},
            "confirmation": {"type": "redirect", "return_url": order.return_url},
            "description": f"VPN: {order.days} days / {order.devices} devices",
            "metadata": {"order_id": order.id, "telegram_id": str(order.telegram_id)},
        }
        return await self._request("POST", "/payments", json=payload, headers={"Idempotence-Key": order.id})

    async def fetch(self, payment_id):
        return await self._request("GET", "/payments/" + quote(payment_id, safe=""))
