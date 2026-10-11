"""Configuration is loaded explicitly at startup, never at import time."""

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv

TARIFFS = {
    (1, 1): {"price": 99, "days": 30, "devices": 1},
    (1, 3): {"price": 149, "days": 30, "devices": 3},
    (1, 5): {"price": 199, "days": 30, "devices": 5},
    (3, 1): {"price": 269, "days": 90, "devices": 1},
    (3, 3): {"price": 399, "days": 90, "devices": 3},
    (3, 5): {"price": 539, "days": 90, "devices": 5},
    (6, 1): {"price": 469, "days": 180, "devices": 1},
    (6, 3): {"price": 699, "days": 180, "devices": 3},
    (6, 5): {"price": 939, "days": 180, "devices": 5},
}


def database_url() -> str:
    return os.getenv("DATABASE_URL") or "sqlite+aiosqlite:///" + str(
        Path(os.getenv("DB_PATH", "vpn_bot.db")).resolve()
    )


@dataclass(frozen=True)
class Settings:
    token: str
    webhook_url: str
    telegram_secret: str
    public_url: str
    database_url: str
    shop_id: str
    shop_secret: str
    return_url: str
    test_payments: bool
    panel_url: str
    panel_user: str
    panel_password: str
    panel_sub_url: str
    panel_verify_ssl: bool
    host: str
    port: int

    @classmethod
    def load(cls):
        load_dotenv()
        required = [
            "API_TOKEN",
            "WEBHOOK_URL",
            "TELEGRAM_WEBHOOK_SECRET",
            "PUBLIC_URL",
            "YOO_SHOP_ID",
            "YOO_SECRET_KEY",
            "YOO_RETURN_URL",
            "XUI_API",
            "XUI_USER",
            "XUI_PASS",
            "XUI_SUB_URL",
        ]
        missing = [key for key in required if not os.getenv(key)]
        if missing:
            raise ValueError("Missing settings: " + ", ".join(missing))
        for key in ("WEBHOOK_URL", "PUBLIC_URL", "YOO_RETURN_URL", "XUI_API", "XUI_SUB_URL"):
            parsed = urlparse(os.environ[key])
            if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
                raise ValueError(f"{key} must be an HTTPS URL without credentials")
        secret = os.environ["TELEGRAM_WEBHOOK_SECRET"]
        if not 1 <= len(secret) <= 256 or any(
            c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for c in secret
        ):
            raise ValueError("Invalid TELEGRAM_WEBHOOK_SECRET")
        for key in ("YOO_TEST_MODE", "XUI_VERIFY_SSL"):
            if os.getenv(key, "true").lower() not in ("true", "false"):
                raise ValueError(f"{key} must be true or false")
        return cls(
            os.environ["API_TOKEN"],
            os.environ["WEBHOOK_URL"],
            secret,
            os.environ["PUBLIC_URL"].rstrip("/"),
            database_url(),
            os.environ["YOO_SHOP_ID"],
            os.environ["YOO_SECRET_KEY"],
            os.environ["YOO_RETURN_URL"],
            os.getenv("YOO_TEST_MODE", "true").lower() == "true",
            os.environ["XUI_API"].rstrip("/"),
            os.environ["XUI_USER"],
            os.environ["XUI_PASS"],
            os.environ["XUI_SUB_URL"].rstrip("/"),
            os.getenv("XUI_VERIFY_SSL", "true").lower() == "true",
            os.getenv("WEBAPP_HOST", "127.0.0.1"),
            int(os.getenv("WEBAPP_PORT", "8443")),
        )
