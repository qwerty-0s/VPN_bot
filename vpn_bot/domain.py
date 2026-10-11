"""Domain values; no framework, database or network imports."""

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

DAY_MS = 86_400_000


class InvalidPayment(ValueError):
    pass


class NotFound(LookupError):
    pass


class RetryLater(RuntimeError):
    pass


class ManualReview(RuntimeError):
    pass


def kopecks(value: str) -> int:
    try:
        number = Decimal(str(value)) * 100
        if not number.is_finite() or number <= 0 or number != number.to_integral_value():
            raise InvalidPayment("Invalid amount")
        return int(number)
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise InvalidPayment("Invalid amount") from exc


@dataclass(frozen=True)
class Order:
    id: str
    request_key: str
    telegram_id: int
    amount: int
    days: int
    devices: int
    created_ms: int
    return_url: str
    payment_id: str | None = None
    confirmation_url: str | None = None
    status: str = "creating"
    applied: bool = False
    legacy: bool = False
    notified: bool = False


@dataclass(frozen=True)
class Subscription:
    telegram_id: int
    uuid: str
    email: str
    short_id: str
    sub_id: str
    expiry_ms: int
    devices: int
    port: int | None = None
    synced: bool = False
    enabled: bool = True


@dataclass(frozen=True)
class RemotePayment:
    id: str
    status: str
    amount: int
    currency: str
    paid: bool
    test: bool
    shop_id: str
    metadata: dict
    confirmation_url: str | None = None
