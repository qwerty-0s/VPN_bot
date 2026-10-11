# VPN_bot

Personal Python project; no Arcadia or Tracker workflow. Read README.md,
ARCHITECTURE.md and docs/plan.md. Original historical reports are in docs/history/.

Use aiogram 3 and aiohttp. The entrypoint remains python main.py. Keep SQL in
vpn_bot/storage.py and migration code, provider calls in integrations/, and business
rules in services.py using ports.py. No configuration/network side effects at import.
Never log credentials, session cookies, payment links or subscription links.

For changes to payments, verify ownership, amount/currency binding, idempotency,
concurrent renewal, crash recovery and rollback. Tests must use disposable databases
and fake HTTP servers. See README.md for pytest, PostgreSQL and ruff commands.
Do not use old report claims as current test evidence. Do not deploy without a task.
