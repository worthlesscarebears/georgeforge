"""App Settings"""

# Django
from django.conf import settings


def discord_bot_active():
    return "aadiscordbot" in settings.INSTALLED_APPS


def webhook_available():
    try:
        # Third Party
        import discord

        return discord is not None
    except ImportError:
        return False


# Name of this app as shown in the Auth sidebar, page titles
GEORGEFORGE_APP_NAME = getattr(settings, "GEORGEFORGE_APP_NAME", "George Forge")

GEORGEFORGE_ADMIN_WEBHOOK = getattr(settings, "GEORGEFORGE_ADMIN_WEBHOOK", None)

GEORGEFORGE_ADMIN_WEBHOOK_ROLE_ID = getattr(
    settings, "GEORGEFORGE_ADMIN_WEBHOOK_ROLE_ID", None
)

GEORGEFORGE_ORDER_PENDING_DEFAULT = getattr(
    settings, "GEORGEFORGE_ORDER_PENDING_DEFAULT", True
)

GEORGEFORGE_DEPOSIT_DUE = getattr(settings, "GEORGEFORGE_DEPOSIT_DUE", 7)

GEORGEFORGE_ORDER_DEPOSIT_INSTRUCTIONS = getattr(
    settings, "GEORGEFORGE_ORDER_DEPOSIT_INSTRUCTIONS", None
)
