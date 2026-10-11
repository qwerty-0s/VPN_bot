"""Adapter for the classic 3x-ui /panel/api/inbounds contract.

One dedicated VLESS Reality inbound per user, as in the original checkout.
Requires a staging smoke test against the installed panel version.
"""

import json
import secrets
from urllib.parse import quote

from aiohttp import ClientError, ClientSession, ClientTimeout

from ..domain import RetryLater


def decode(value):
    return json.loads(value) if isinstance(value, str) else value


class XUI:
    def __init__(self, session: ClientSession, url, username, password, verify_ssl=True):
        self.session, self.url = session, url.rstrip("/")
        self.username, self.password, self.verify_ssl = username, password, verify_ssl

    async def _request(self, method, path, **kwargs):
        try:
            async with self.session.request(
                method,
                self.url + path,
                ssl=self.verify_ssl,
                timeout=ClientTimeout(total=8),
                allow_redirects=False,
                **kwargs,
            ) as response:
                if response.status != 200:
                    raise RetryLater(f"Panel HTTP {response.status}")
                data = await response.json(content_type=None)
            if not isinstance(data, dict) or data.get("success") is not True:
                raise RetryLater("Panel operation failed")
            return data.get("obj")
        except (ClientError, TimeoutError, ValueError, TypeError) as exc:
            raise RetryLater("Panel unavailable or invalid response") from exc

    async def _list(self):
        rows = await self._request("GET", "/panel/api/inbounds/list")
        if not isinstance(rows, list):
            raise RetryLater("Invalid panel inbound list")
        return rows

    @staticmethod
    def _find(rows, subscription):
        matches = []
        for inbound in rows:
            settings = decode(inbound.get("settings", "{}"))
            clients = settings.get("clients", [])
            for client in clients:
                if client.get("id") == subscription.uuid:
                    if len(clients) != 1 or inbound.get("protocol") != "vless":
                        raise RetryLater("Expected dedicated VLESS inbound")
                    matches.append((inbound, client))
                elif client.get("email") == subscription.email:
                    raise RetryLater("Panel identity conflict; manual reconciliation required")
        if len(matches) > 1:
            raise RetryLater("Duplicate panel identity")
        return matches[0] if matches else (None, None)

    @staticmethod
    def _client(subscription):
        return {
            "id": subscription.uuid,
            "flow": "",
            "email": subscription.email,
            "limitIp": subscription.devices,
            "totalGB": 0,
            "expiryTime": subscription.expiry_ms,
            "enable": subscription.enabled,
            "tgId": str(subscription.telegram_id),
            "subId": subscription.sub_id,
            "reset": 0,
        }

    async def ensure(self, subscription):
        await self._request("POST", "/login", data={"username": self.username, "password": self.password})
        rows = await self._list()
        inbound, client = self._find(rows, subscription)
        desired = self._client(subscription)
        if inbound:
            # Preserve all unrelated Reality settings and client counters.
            payload = {
                k: inbound[k]
                for k in (
                    "up",
                    "down",
                    "total",
                    "remark",
                    "listen",
                    "port",
                    "protocol",
                    "settings",
                    "streamSettings",
                    "sniffing",
                )
                if k in inbound
            }
            payload.update(enable=True, expiryTime=0)
            await self._request("POST", f"/panel/api/inbounds/update/{inbound['id']}", json=payload)
            client = {
                **client,
                **{k: desired[k] for k in ("email", "limitIp", "expiryTime", "enable", "subId")},
            }
            await self._request(
                "POST",
                "/panel/api/inbounds/updateClient/" + quote(subscription.uuid, safe=""),
                json={"id": inbound["id"], "settings": json.dumps({"clients": [client]})},
            )
        else:
            used_ports = {int(row["port"]) for row in rows}
            if subscription.port is not None:
                if subscription.port in used_ports:
                    raise RetryLater("Stored port occupied by another inbound")
                port = subscription.port
            else:
                free = [p for p in range(10000, 65001) if p not in used_ports]
                if not free:
                    raise RetryLater("No free panel ports")
                port = secrets.choice(free)
            keys = await self._request("GET", "/panel/api/server/getNewX25519Cert")
            payload = {
                "up": 0,
                "down": 0,
                "total": 0,
                "remark": subscription.email,
                "enable": True,
                "expiryTime": 0,
                "listen": "",
                "port": port,
                "protocol": "vless",
                "settings": json.dumps({"clients": [desired], "decryption": "none"}),
                "streamSettings": json.dumps(
                    {
                        "network": "tcp",
                        "security": "reality",
                        "realitySettings": {
                            "show": False,
                            "xver": 0,
                            "target": "google.com:443",
                            "serverNames": ["google.com", "www.google.com"],
                            "privateKey": keys["privateKey"],
                            "shortIds": [secrets.token_hex(8)],
                            "settings": {
                                "publicKey": keys["publicKey"],
                                "fingerprint": "firefox",
                                "spiderX": "/",
                            },
                        },
                        "tcpSettings": {"acceptProxyProtocol": False, "header": {"type": "none"}},
                    }
                ),
                "sniffing": json.dumps({"enabled": False, "destOverride": ["http", "tls"]}),
            }
            await self._request("POST", "/panel/api/inbounds/add", json=payload)
        # Some panel versions return success without applying fields; read them back.
        inbound, client = self._find(await self._list(), subscription)
        if (
            not inbound
            or not inbound.get("enable")
            or inbound.get("expiryTime", 0) != 0
            or any(client.get(k) != desired[k] for k in ("email", "limitIp", "expiryTime", "enable", "subId"))
        ):
            raise RetryLater("Panel did not confirm the requested subscription state")
        return int(inbound["port"])
