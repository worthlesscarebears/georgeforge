# George Forge

[![PyPI - Version](https://img.shields.io/pypi/v/allianceauth-georgeforge?style=for-the-badge)](https://pypi.org/project/allianceauth-georgeforge)

An app for george. I guess other people can use it if they want.

## Settings

All are optional. The webhook can be unset.

```python
# Georgeforge
# Webhook to post orders to
GEORGEFORGE_ADMIN_WEBHOOK = "https://discord.com/api/webhooks/1/abcd"
# Discord role ID to ping when a new order is placed
GEORGEFORGE_ADMIN_WEBHOOK_ROLE_ID = 123456789
# Deposit instructions shown to users when placing an order with a deposit
GEORGEFORGE_ORDER_DEPOSIT_INSTRUCTIONS = "Please send your deposit to WCBR"
# Character ID behind the manager-only "Manager Options" checkout checkbox,
# which places an order under that account instead of the manager
GEORGEFORGE_MANAGER_ORDER_CHARACTER_ID = 2124621080
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
