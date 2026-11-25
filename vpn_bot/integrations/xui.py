"""Adapter for the 3x-ui v3 multi-inbound /panel/api/clients contract.

Attaches each user to the configured existing VLESS Reality inbounds
(e.g. new-reality and new-reality WARP) under a single shared subscription.
"""

import json
import re
from urllib.parse import quote

from aiohttp import ClientError, ClientSession, ClientTimeout

from ..domain import RetryLater


def decode(value):
    return json.loads(value) if isinstance(value, str) else value


class XUI:
    def __init__(self, session: ClientSession, url, username, password, verify_ssl=True, inbounds=()):
        self.session, self.url = session, url.rstrip("/")
        self.username, self.password, self.verify_ssl = username, password, verify_ssl
        self.inbounds = tuple(str(item).strip() for item in inbounds if str(item).strip())
        if not self.inbounds:
            raise ValueError("At least one target inbound must be configured")
        self.csrf_token = None
        self._csrf_checked = False

    def _reset_csrf(self):
        self.csrf_token = None
        self._csrf_checked = False

    async def _ensure_csrf(self):
        if not self._csrf_checked:
            try:
                async with self.session.get(
                    self.url + "/",
                    ssl=self.verify_ssl,
                    timeout=ClientTimeout(total=8),
                    allow_redirects=True,
                ) as resp:
                    html = await resp.text()
                    match = re.search(r'name="csrf-token" content="([^"]+)"', html)
                    if match:
                        self.csrf_token = match.group(1)
            except Exception:
                pass
            finally:
                self._csrf_checked = True

    async def _request(self, method, path, *, allow_not_found=False, **kwargs):
        try:
            await self._ensure_csrf()
            headers = {**kwargs.pop("headers", {})}
            if self.csrf_token:
                headers["x-csrf-token"] = self.csrf_token
            async with self.session.request(
                method,
                self.url + path,
                headers=headers,
                ssl=self.verify_ssl,
                timeout=ClientTimeout(total=8),
                allow_redirects=False,
                **kwargs,
            ) as response:
                if allow_not_found and response.status == 404:
                    return None
                if response.status != 200:
                    self._reset_csrf()
                    raise RetryLater(f"Panel HTTP {response.status}")
                data = await response.json(content_type=None)
            if allow_not_found and isinstance(data, dict) and data.get("success") is False:
                msg = str(data.get("msg", "")).lower()
                if "not found" in msg or "no record" in msg:
                    return None
            if not isinstance(data, dict) or data.get("success") is not True:
                self._reset_csrf()
                raise RetryLater("Panel operation failed")
            return data.get("obj")
        except (ClientError, TimeoutError, ValueError, TypeError) as exc:
            self._reset_csrf()
            raise RetryLater("Panel unavailable or invalid response") from exc

    async def _list(self):
        rows = await self._request("GET", "/panel/api/inbounds/list")
        if not isinstance(rows, list):
            raise RetryLater("Invalid panel inbound list")
        return rows

    async def _get_client(self, email):
        return await self._request(
            "GET", f"/panel/api/clients/get/{quote(email, safe='')}", allow_not_found=True
        )

    def _resolve_inbounds(self, rows):
        resolved = []
        seen_ids = set()
        for target in self.inbounds:
            matches = [
                row
                for row in rows
                if str(row.get("id")) == target or str(row.get("remark", "")).strip() == target
            ]
            if not matches:
                raise RetryLater(f"Configured inbound {target!r} not found")
            if len(matches) > 1:
                raise RetryLater(f"Multiple inbounds match {target!r}")
            inbound = matches[0]
            if inbound.get("protocol") != "vless":
                raise RetryLater(f"Expected VLESS inbound for {target!r}")
            if not inbound.get("enable"):
                raise RetryLater(f"Configured inbound {target!r} is disabled")
            inbound_id = int(inbound["id"])
            if inbound_id in seen_ids:
                raise RetryLater(f"Duplicate configured inbound {target!r}")
            seen_ids.add(inbound_id)
            resolved.append(inbound)
        return resolved

    @staticmethod
    def _check_conflicts(rows, subscription):
        for inbound in rows:
            clients = decode(inbound.get("settings", "{}")).get("clients", [])
            for client in clients:
                same_uuid = client.get("id") == subscription.uuid
                same_email = client.get("email") == subscription.email
                if same_uuid != same_email:
                    raise RetryLater("Panel identity conflict; manual reconciliation required")

    @staticmethod
    def _client(subscription):
        return {
            "id": subscription.uuid,
            "email": subscription.email,
            "flow": "",
            "limitIp": subscription.devices,
            "totalGB": 0,
            "expiryTime": subscription.expiry_ms,
            "enable": subscription.enabled,
            "tgId": int(subscription.telegram_id or 0),
            "subId": subscription.sub_id,
            "reset": 0,
        }

    @classmethod
    def _update_payload(cls, existing, subscription):
        desired = cls._client(subscription)
        payload = {
            "flow": existing.get("flow", ""),
            "totalGB": existing.get("totalGB", 0),
            "reset": existing.get("reset", 0),
        }
        for key in ("comment", "group", "adTag", "security"):
            if key in existing and existing[key] is not None:
                payload[key] = existing[key]
        payload.update(desired)
        return payload

    @staticmethod
    def _inbound_has_desired_client(inbound, desired):
        clients = decode(inbound.get("settings", "{}")).get("clients", [])
        matches = [c for c in clients if c.get("id") == desired["id"] or c.get("email") == desired["email"]]
        if len(matches) != 1:
            return False
        client = matches[0]
        return all(
            client.get(k) == desired[k] for k in ("id", "email", "limitIp", "expiryTime", "enable", "subId")
        )

    async def ensure(self, subscription):
        await self._request("POST", "/login", data={"username": self.username, "password": self.password})
        rows = await self._list()
        target_inbounds = self._resolve_inbounds(rows)
        target_ids = [int(inbound["id"]) for inbound in target_inbounds]
        self._check_conflicts(rows, subscription)

        desired = self._client(subscription)
        record = await self._get_client(subscription.email)
        if record is None:
            await self._request(
                "POST",
                "/panel/api/clients/add",
                json={"client": desired, "inboundIds": target_ids},
            )
        else:
            existing = record.get("client") if isinstance(record, dict) else None
            if not isinstance(existing, dict):
                raise RetryLater("Invalid client record from panel")
            existing_uuid = existing.get("uuid") or existing.get("id")
            if existing_uuid != subscription.uuid:
                raise RetryLater("Panel identity conflict; manual reconciliation required")
            attached = {int(i) for i in record.get("inboundIds", [])}
            missing = [iid for iid in target_ids if iid not in attached]
            if missing:
                await self._request(
                    "POST",
                    f"/panel/api/clients/{quote(subscription.email, safe='')}/attach",
                    json={"inboundIds": missing},
                )
            await self._request(
                "POST",
                f"/panel/api/clients/update/{quote(subscription.email, safe='')}",
                json=self._update_payload(existing, subscription),
            )

        # Read back both client record and inbound lists to confirm propagation.
        confirmed = await self._get_client(subscription.email)
        confirmed_client = confirmed.get("client") if isinstance(confirmed, dict) else None
        confirmed_ids = (
            {int(i) for i in confirmed.get("inboundIds", [])} if isinstance(confirmed, dict) else set()
        )
        if (
            not isinstance(confirmed_client, dict)
            or (confirmed_client.get("uuid") or confirmed_client.get("id")) != desired["id"]
            or not set(target_ids).issubset(confirmed_ids)
            or any(
                confirmed_client.get(k) != desired[k]
                for k in ("email", "limitIp", "expiryTime", "enable", "subId")
            )
        ):
            raise RetryLater("Panel did not confirm the requested subscription state")

        confirmed_inbounds = self._resolve_inbounds(await self._list())
        if any(not self._inbound_has_desired_client(inbound, desired) for inbound in confirmed_inbounds):
            raise RetryLater("Panel did not confirm client state in all target inbounds")
        return None
