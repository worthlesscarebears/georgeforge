# George Forge

[![PyPI - Version](https://img.shields.io/pypi/v/allianceauth-georgeforge?style=for-the-badge)](https://pypi.org/project/allianceauth-georgeforge)

An app for george. I guess other people can use it if they want.

## Settings

All are optional. Forge categories has somewhat reasonable defaults (could
probably be tuned) and the webhook can be unset.

```python
# Georgeforge
# Item categories you wish to sell
FORGE_CATEGORIES = [4,6,7,8,18,20,63,66]
# Webhook to post orders to
INDUSTRY_ADMIN_WEBHOOK = "https://discord.com/api/webhooks/1/abcd"
# Discord role ID to ping when a new order is placed
INDUSTRY_ADMIN_WEBHOOK_ROLE_ID = 123456789
# Deposit instructions shown to users when placing an order with a deposit
ORDER_DEPOSIT_INSTRUCTIONS = "Please send your deposit to Character Name"
```

## Installation

We depend on
[django-eveonline-sde](https://github.com/Solar-Helix-Independent-Transport/django-eveonline-sde)
so follow those instructions. Also corptools
and invoices.

```bash
python manage.py migrate
python manage.py collectstatic --no-input
```
