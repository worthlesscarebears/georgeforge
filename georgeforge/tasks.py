"""App Tasks"""

# Standard Library
import json
import logging
from datetime import datetime, timedelta

# Third Party
import requests
from celery import shared_task
from invoices.models import Invoice

# Django
from django.utils import timezone

# Alliance Auth
from allianceauth.services.tasks import QueueOnce

# George Forge
from georgeforge.models import Order

from . import app_settings

logger = logging.getLogger(__name__)

# Create your tasks here
if app_settings.webhook_available():
    # Third Party
    from discord import Color, Embed

if app_settings.discord_bot_active():
    # Third Party
    from aadiscordbot.cogs.utils.exceptions import NotAuthenticated
    from aadiscordbot.tasks import send_message
    from aadiscordbot.utils.auth import get_discord_user_id


# Shamelessly yoinked from aa-securegroups/tasks.py
def send_discord_dm(user, title, message, color):
    if app_settings.discord_bot_active():
        try:
            e = Embed(title=title, description=message, color=color)
            try:
                send_message(user_id=get_discord_user_id(user), embed=e)
                logger.info(f"sent discord ping to {user} - {message}")
            except NotAuthenticated:
                logger.warning(f"Unable to ping {user} - {message}")

        except Exception as e:
            logger.error(e, exc_info=1)
            pass


def send_statusupdate_dm(order):
    if app_settings.discord_bot_active():
        match order.status:
            case Order.OrderStatus.PENDING:
                c = Color.blue()
            case Order.OrderStatus.AWAITING_DEPOSIT:
                c = Color.purple()
            case Order.OrderStatus.DEPOSIT_RECIEVED:
                c = Color.blue()
            case Order.OrderStatus.BUILDING_PARTS:
                c = Color.orange()
            case Order.OrderStatus.BUILDING_HULL:
                c = Color.orange()
            case Order.OrderStatus.AWAITING_FINAL_PAYMENT:
                c = Color.purple()
            case Order.OrderStatus.DELIVERED:
                c = Color.green()
            case Order.OrderStatus.REJECTED:
                c = Color.red()

        e = Embed(
            title=f"Order #{order.pk} Status: {order.get_status_display()}", color=c
        )
        e.add_field(name="Item", value=order.eve_type.name, inline=True)
        e.add_field(name="Quantity", value=str(order.quantity), inline=True)
        e.add_field(name="Price per Unit", value=f"{order.price:,.2f} ISK", inline=True)
        e.add_field(name="Total Cost", value=f"{order.totalcost:,.2f} ISK", inline=True)
        e.add_field(name="Deposit", value=f"{order.deposit:,.2f} ISK", inline=True)
        e.add_field(
            name="Delivery System", value=order.deliverysystem.name, inline=True
        )
        if order.estimated_delivery_date:
            e.add_field(
                name="Estimated Delivery",
                value=order.estimated_delivery_date,
                inline=True,
            )
        if order.description:
            e.add_field(name="Description", value=order.description, inline=False)
        if order.notes:
            e.add_field(name="Notes", value=order.notes, inline=False)
        if (
            order.status == Order.OrderStatus.PENDING
            and order.deposit > 0
            and app_settings.GEORGEFORGE_ORDER_DEPOSIT_INSTRUCTIONS
        ):
            e.add_field(
                name="Deposit Instructions",
                value=app_settings.GEORGEFORGE_ORDER_DEPOSIT_INSTRUCTIONS,
                inline=False,
            )

        try:
            send_message(user_id=get_discord_user_id(order.user), embed=e)
            logger.info(
                f"sent discord ping to {order.user} - order #{order.pk} status updated to {order.get_status_display()}"
            )
        except NotAuthenticated:
            logger.warning(
                f"Unable to ping {order.user} - order #{order.pk} status updated"
            )


def send_deliverydateupdate_dm(order):
    if app_settings.discord_bot_active():
        e = Embed(title=f"Order #{order.pk} Delivery Date Updated", color=Color.blue())

        if order.estimated_delivery_date:
            e.add_field(
                name="New Estimated Delivery",
                value=order.estimated_delivery_date,
                inline=False,
            )
        else:
            e.add_field(name="Estimated Delivery", value="Cleared", inline=False)

        e.add_field(name="Item", value=order.eve_type.name, inline=True)
        e.add_field(name="Quantity", value=str(order.quantity), inline=True)
        e.add_field(name="Price per Unit", value=f"{order.price:,.2f} ISK", inline=True)
        e.add_field(name="Total Cost", value=f"{order.totalcost:,.2f} ISK", inline=True)
        e.add_field(name="Deposit", value=f"{order.deposit:,.2f} ISK", inline=True)
        e.add_field(
            name="Delivery System", value=order.deliverysystem.name, inline=True
        )
        e.add_field(name="Status", value=order.get_status_display(), inline=True)
        if order.description:
            e.add_field(name="Description", value=order.description, inline=False)
        if order.notes:
            e.add_field(name="Notes", value=order.notes, inline=False)

        try:
            send_message(user_id=get_discord_user_id(order.user), embed=e)
            logger.info(
                f"sent discord ping to {order.user} - order #{order.pk} delivery date updated"
            )
        except NotAuthenticated:
            logger.warning(
                f"Unable to ping {order.user} - order #{order.pk} delivery date updated"
            )


@shared_task
def send_update_to_webhook(content=None, embed=None):
    web_hook = app_settings.GEORGEFORGE_ADMIN_WEBHOOK
    if web_hook is not None:
        custom_headers = {"Content-Type": "application/json"}
        payload = {}
        if embed:
            payload["embeds"] = [embed]
        if content:
            payload["content"] = content
        elif not embed:
            payload["content"] = "New order update"
        r = requests.post(
            web_hook,
            headers=custom_headers,
            data=json.dumps(payload),
        )
        logger.debug(f"Got status code {r.status_code} after sending ping")
        try:
            r.raise_for_status()
        except Exception as e:
            logger.error(e, exc_info=1)


@shared_task
def send_order_webhook(order_pk, updated=False, update_type=0):
    if not app_settings.webhook_available():
        return

    order = Order.objects.get(pk=order_pk)
    if not updated:
        embed = Embed(
            title=f"New Ship Order: {order.quantity} x {order.eve_type.name}",
            color=Color.blue(),
        )
        embed.add_field(
            name="Purchaser",
            value=order.user.profile.main_character.character_name,
            inline=True,
        )
        embed.add_field(name="Quantity", value=str(order.quantity), inline=True)
        embed.add_field(
            name="Price per Unit",
            value=f"{order.price:,.2f} ISK",
            inline=True,
        )
        embed.add_field(
            name="Total Cost",
            value=f"{order.totalcost:,.2f} ISK",
            inline=True,
        )
        embed.add_field(name="Deposit", value=f"{order.deposit:,.2f} ISK", inline=True)
        embed.add_field(
            name="Delivery System", value=order.deliverysystem.name, inline=True
        )
        embed.add_field(name="Status", value=order.get_status_display(), inline=True)
        if order.description:
            embed.add_field(name="Description", value=order.description, inline=False)
        if order.notes:
            embed.add_field(name="Notes", value=order.notes, inline=False)
    else:
        embed = Embed(title=f"Order #{order.id} updated!", color=Color.purple())
        embed.add_field(
            name="New status", value=f"```{order.get_status_display()}```", inline=True
        )
        embed.add_field(
            name="Order Date (M/D/Y)",
            value=f"```{str(datetime.now().strftime('%m/%d/%Y'))}```",  # i hate this as much as you do, i know
        )
        match update_type:
            case 0:  # DEPOSIT_PAID
                embed.add_field(
                    name="Deposit paid!",
                    value=f"```Invoice GF-DEP-{order.id} marked as paid.```",
                    inline=False,
                )
                embed.add_field(
                    name="Quantity", value=f"```{order.quantity}```", inline=True
                )
                embed.add_field(
                    name="Item", value=f"```{order.eve_type.name}```", inline=True
                )
                embed.add_field(
                    name="Type",
                    value=f"```{order.eve_type.group.name}```",
                    inline=True,
                )
                embed.add_field(
                    name="Client",
                    value=f"```{order.user.profile.main_character.character_name}```",
                    inline=True,
                )
                embed.add_field(
                    name="Paid", value=f"```{order.paid:,.2f}```", inline=True
                )
                embed.add_field(
                    name="Order Total",
                    value=f"```{order.totalcost:,.2f}```",
                    inline=True,
                )
                embed.add_field(name="Notes", value=f"```{order.notes}```", inline=True)
            case 1:  # ADMIN_INVOICE
                embed.add_field(
                    name="Invoice missing - assuming this is an internal order!",
                    value=f"```Invoice GF-DEP-{order.id} missing.```",
                    inline=False,
                )
                embed.add_field(
                    name="Order details",
                    value=f"```{order.quantity} x {order.eve_type.name} for {order.user.profile.main_character.character_name}```",
                    inline=False,
                )

    content = None
    role_id = app_settings.GEORGEFORGE_ADMIN_WEBHOOK_ROLE_ID
    if role_id:
        content = f"<@&{role_id}>"

    send_update_to_webhook.delay(content=content, embed=embed.to_dict())


@shared_task(bind=True, base=QueueOnce)
def check_invoice_status(self):
    logger.info("Checking for complete Invoices")
    for order in Order.objects.filter(status=Order.OrderStatus.AWAITING_DEPOSIT).all():
        ref = f"GF-DEP-{str(order.id)}"
        try:
            inv = Invoice.objects.filter(invoice_ref=ref).get()
        except Invoice.DoesNotExist:
            order.status = Order.OrderStatus.DEPOSIT_RECIEVED
            order.save()
            send_order_webhook(order.id, True, 1)
            continue
        if inv.paid:
            order.paid += inv.amount
            order.status = Order.OrderStatus.DEPOSIT_RECIEVED
            order.save()
            send_order_webhook(order.id, True)


def send_order_invoice(order):
    if order.deposit != 0 and order.deposit > order.paid:
        isk = order.deposit - order.paid
        due = timezone.now() + timedelta(days=app_settings.GEORGEFORGE_DEPOSIT_DUE)
        character_id = order.user.profile.main_character.id
        inv = Order.generate_invoice(character_id, order.id, isk, due)
        if inv.amount < 1:
            logger.error(
                f"{order.deposit} - {order.paid} = {order.deposit - order.paid} or {isk}"
            )
            logger.error(print(inv))
            return 0
        else:
            inv.save()
            Order.ping_invoice(inv)
