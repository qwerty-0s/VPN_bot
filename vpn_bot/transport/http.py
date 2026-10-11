import logging
import re
from urllib.parse import quote

from aiohttp import ClientError, ClientTimeout, web

from ..domain import InvalidPayment, ManualReview, RetryLater


def register_routes(app, service, subscription_session, panel_sub_url):
    async def payment_webhook(request):
        try:
            data = await request.json()
            if not isinstance(data, dict) or data.get("type") != "notification":
                raise ValueError
            if data.get("event") not in (
                "payment.succeeded",
                "payment.canceled",
                "payment.waiting_for_capture",
            ):
                return web.Response(status=200)
            payment_id = data["object"]["id"]
            if not isinstance(payment_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", payment_id):
                raise ValueError
        except (ValueError, TypeError, KeyError):
            return web.Response(status=400)
        try:
            # Only ID is trusted enough to query; status/amount/owner come from API.
            await service.webhook(payment_id)
        except InvalidPayment:
            return web.Response(status=400)
        except ManualReview:
            return web.Response(status=200)  # Quarantined locally; don't retry forever.
        except Exception as exc:
            logging.getLogger(__name__).warning("Webhook deferred (%s)", type(exc).__name__)
            return web.Response(status=503)
        return web.Response(status=200)

    async def short_subscription(request):
        subscription = await service.store.by_short_id(request.match_info["short_id"])
        if not subscription:
            return web.Response(status=404)
        if not subscription.enabled or subscription.expiry_ms <= service.clock():
            return web.Response(status=403)
        if not subscription.synced:
            return web.Response(status=503)
        try:
            async with subscription_session.get(
                panel_sub_url + "/" + quote(subscription.sub_id, safe=""),
                timeout=ClientTimeout(total=5),
                allow_redirects=False,
            ) as response:
                if response.status != 200:
                    raise RetryLater("Subscription endpoint unavailable")
                # Avoid unbounded buffering of an upstream response.
                body = bytearray()
                async for chunk in response.content.iter_chunked(65536):
                    body.extend(chunk)
                    if len(body) > 1024 * 1024:
                        raise RetryLater("Subscription response too large")
                return web.Response(
                    body=bytes(body),
                    content_type="text/plain",
                    headers={
                        "Cache-Control": "no-store",
                        "Profile-Update-Interval": "1",
                        "Subscription-Userinfo": response.headers.get("Subscription-Userinfo", ""),
                    },
                )
        except (ClientError, TimeoutError, RetryLater):
            return web.Response(status=502)

    app.router.add_post("/payments/yookassa", payment_webhook)
    app.router.add_get("/sub/{short_id}", short_subscription)
    return app
