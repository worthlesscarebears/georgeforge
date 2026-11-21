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

# Character ID of the account that the manager-only "Manager Options"
# checkbox at checkout places orders under instead of the manager
GEORGEFORGE_MANAGER_ORDER_CHARACTER_ID = getattr(
    settings, "GEORGEFORGE_MANAGER_ORDER_CHARACTER_ID", 2124621080
)
