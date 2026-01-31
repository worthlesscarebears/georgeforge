"""Template tags for georgeforge"""

# Third Party
# eve_sde
from eve_sde.models import ItemType

# Django
from django import template
from django.utils.translation import gettext_lazy as _

# George Forge
from georgeforge import app_settings

register = template.Library()


@register.filter
def has_discord_linked(user):
    """Check if user has discord linked using get_discord_user_id"""
    if not app_settings.discord_bot_active():
        return True

    try:
        # Third Party
        from aadiscordbot.cogs.utils.exceptions import NotAuthenticated
        from aadiscordbot.utils.auth import get_discord_user_id

        get_discord_user_id(user)
        return True
    except NotAuthenticated:
        return False
    except ImportError:
        return True


@register.filter
def evetype_icon(eve_type, size=32):
    """Take an eve_type object and return an image HTML element of it's icon WITH an item level overlay"""
    base_icon_url = f"https://images.evetech.net/types/{eve_type.id}/icon?size=64"
    pip = ""
    tl = ItemType.objects.get(id=eve_type.id).meta_group_id_raw
    if tl is None or tl == 1:
        pip = ""
    else:
        pip = f'<img class="pip" src="/static/georgeforge/img/{int(tl)}.png" />'

    return f'{pip}<img height="{size}" width="{size}" src="{base_icon_url}" alt="{_("Item Icon")}" />'
