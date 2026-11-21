"""App Views"""

# Standard Library
import csv
import itertools
import json
import logging
import uuid
from decimal import ROUND_DOWN, Decimal
from operator import attrgetter

# Third Party
from django_celery_beat.models import CrontabSchedule, PeriodicTask

# Django
from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.core.handlers.wsgi import WSGIRequest
from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.template.defaultfilters import pluralize
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_POST

# Alliance Auth
from allianceauth.eveonline.models import EveCharacter

# Alliance Auth (External Libs)
from eve_sde.models import ItemType

# George Forge
from georgeforge.forms import BulkImportStoreItemsForm
from georgeforge.models import (
    AffiliationDiscount,
    DeliverySystem,
    ForSale,
    Order,
    VoucherCode,
    VoucherRedemption,
)
from georgeforge.tasks import (
    send_deliverydateupdate_dm,
    send_order_invoice,
    send_order_webhook,
    send_statusupdate_dm,
)

from . import app_settings

logger = logging.getLogger(__name__)

CHECKOUT_SESSION_KEY = "georgeforge_checkout"


@login_required
@permission_required("georgeforge.place_order")
def store(request: WSGIRequest) -> HttpResponse:
    """Store view

    :param request: WSGIRequest:

    """

    for_sale = (
        ForSale.objects.select_related("eve_type__group")
        .all()
        .order_by("eve_type__group__name")
    )

    groups = [
        (key, list(l))
        for key, l in itertools.groupby(for_sale, key=attrgetter("eve_type.group.name"))
    ]
    groups.sort(key=lambda pair: max(entry.price for entry in pair[1]), reverse=True)

    delivery_systems = DeliverySystem.objects.filter(enabled=True).select_related(
        "system"
    )

    context = {
        "for_sale": groups,
        "delivery_systems": delivery_systems,
        "user_id": request.user.id,
    }

    return render(request, "georgeforge/views/store.html", context)


@login_required
@permission_required("georgeforge.place_order")
def my_orders(request: WSGIRequest) -> HttpResponse:
    """My Orders view

    :param request: WSGIRequest:

    """

    my_orders = (
        Order.objects.select_related()
        .filter(user=request.user, status__lt=Order.OrderStatus.DELIVERED)
        .order_by("-id")
    )
    done_orders = (
        Order.objects.select_related()
        .filter(user=request.user, status__gte=Order.OrderStatus.DELIVERED)
        .order_by("-id")
    )

    context = {
        "my_orders": my_orders,
        "done_orders": done_orders,
        "user_id": request.user.id,
        "clear_cart": request.session.pop("georgeforge_cart_clear", False),
    }

    return render(request, "georgeforge/views/my_orders.html", context)


def _validate_cart_payload(data: dict):
    """Validate a cart payload (items, delivery system, notes).

    Returns (lines, deliverysystem, notes, error). On error the first three
    are None/empty and error is a plain string.
    """
    items = data.get("items", [])
    deliverysystem_id = data.get("deliverysystem_id")
    notes = data.get("notes", "")

    if not items:
        return None, None, "", "No items in cart"

    if not deliverysystem_id:
        return None, None, "", "Delivery system required"

    try:
        deliverysystem = (
            DeliverySystem.objects.select_related("system")
            .get(system_id=deliverysystem_id, enabled=True)
            .system
        )
    except DeliverySystem.DoesNotExist:
        return None, None, "", "Invalid or disabled delivery system"

    quantities = {}
    for item in items:
        for_sale_id = item.get("for_sale_id")
        quantity = item.get("quantity", 1)
        if not isinstance(quantity, int) or quantity < 1:
            return None, None, "", "Minimum quantity 1"
        quantities[for_sale_id] = quantities.get(for_sale_id, 0) + quantity

    lines = []
    for for_sale_id, quantity in quantities.items():
        try:
            for_sale = ForSale.objects.get(id=for_sale_id)
        except ForSale.DoesNotExist:
            return None, None, "", f"Item {for_sale_id} not found"

        lines.append(
            {
                "for_sale": for_sale,
                "quantity": quantity,
                "line_total": for_sale.price * quantity,
                "line_deposit": for_sale.deposit * quantity,
            }
        )

    return lines, deliverysystem, notes, None


def _eligible_subtotal(discount_obj, lines: list, subtotal: Decimal):
    """Return (eligible_ids, eligible_subtotal) for an item-scoped discount.

    eligible_ids of None means the discount applies to every line.
    """
    eligible_ids = discount_obj.scoped_item_ids
    if eligible_ids is None:
        return None, subtotal
    eligible_total = sum(
        line["line_total"] for line in lines if line["for_sale"].id in eligible_ids
    )
    return eligible_ids, eligible_total


def _resolve_discount(user, cart: dict, lines: list, subtotal: Decimal) -> dict:
    """Resolve the session's discount selection against a cart.

    A voucher code always takes precedence over an affiliation discount.
    Item-scoped discounts only discount their eligible lines.
    Returns a dict with voucher / affiliation / amount / eligible_ids /
    error keys (eligible_ids of None = every line is eligible).
    """
    result = {
        "voucher": None,
        "affiliation": None,
        "amount": Decimal("0.00"),
        "eligible_ids": None,
        "error": None,
    }

    voucher_code = (cart.get("voucher_code") or "").strip()
    affiliation_id = cart.get("affiliation_id")

    if voucher_code:
        try:
            voucher = VoucherCode.objects.get(code=voucher_code.upper())
        except VoucherCode.DoesNotExist:
            result["error"] = _("Unknown voucher code")
            return result

        reason = voucher.unavailable_reason(user)
        if reason:
            result["error"] = reason
            return result

        eligible_ids, eligible_subtotal = _eligible_subtotal(voucher, lines, subtotal)
        if eligible_ids is not None and eligible_subtotal <= 0:
            result["error"] = _("This code does not apply to any items in your cart")
            return result

        result["voucher"] = voucher
        result["eligible_ids"] = eligible_ids
        result["amount"] = voucher.calculate_discount(eligible_subtotal)
        return result

    if affiliation_id:
        try:
            affiliation = AffiliationDiscount.objects.get(
                id=affiliation_id, enabled=True
            )
        except (AffiliationDiscount.DoesNotExist, TypeError, ValueError):
            result["error"] = _("Unknown discount")
            return result

        if not affiliation.user_qualifies(user):
            result["error"] = _("You are not eligible for this discount")
            return result

        eligible_ids, eligible_subtotal = _eligible_subtotal(
            affiliation, lines, subtotal
        )
        if eligible_ids is not None and eligible_subtotal <= 0:
            result["error"] = _(
                "This discount does not apply to any items in your cart"
            )
            return result

        result["affiliation"] = affiliation
        result["eligible_ids"] = eligible_ids
        result["amount"] = affiliation.calculate_discount(eligible_subtotal)

    return result


def _allocate_discount(discount_amount: Decimal, line_totals: list) -> list:
    """Split a cart-level discount across order lines proportionally.

    Shares are floored to cents and the remainder goes to the largest line,
    so the allocations always sum to at most the requested discount.
    """
    count = len(line_totals)
    if discount_amount <= 0 or count == 0:
        return [Decimal("0.00")] * count

    subtotal = sum(line_totals, Decimal("0"))
    if subtotal <= 0:
        return [Decimal("0.00")] * count

    if count == 1:
        return [min(discount_amount, line_totals[0])]

    shares = [
        (discount_amount * total / subtotal).quantize(
            Decimal("0.01"), rounding=ROUND_DOWN
        )
        for total in line_totals
    ]
    remainder = discount_amount - sum(shares, Decimal("0"))
    largest = max(range(count), key=lambda index: line_totals[index])
    shares[largest] += remainder

    return [min(share, total) for share, total in zip(shares, line_totals)]


def _manager_order_target():
    """Resolve the configured manager-order character to its owning account.

    Powers the manager-only "Manager Options" checkout checkbox, which
    places an order under a fixed account instead of the manager.

    Returns (user, character_name, error). user is None when the configured
    character cannot be resolved; error is None when it resolves cleanly.
    """
    char_id = app_settings.GEORGEFORGE_MANAGER_ORDER_CHARACTER_ID
    try:
        char_id = int(char_id)
    except (TypeError, ValueError):
        logger.error(
            "GEORGEFORGE_MANAGER_ORDER_CHARACTER_ID is not a valid character ID: %r",
            char_id,
        )
        return None, None, _("Manager order character ID is misconfigured")

    try:
        character = EveCharacter.objects.select_related(
            "character_ownership__user"
        ).get(character_id=char_id)
    except EveCharacter.DoesNotExist:
        logger.error(
            "GEORGEFORGE_MANAGER_ORDER_CHARACTER_ID character %s does not exist",
            char_id,
        )
        return (
            None,
            None,
            _("Manager order character %(id)s was not found") % {"id": char_id},
        )

    try:
        user = character.character_ownership.user
    except ObjectDoesNotExist:
        logger.error("Manager order character %s is not owned by any user", char_id)
        return (
            None,
            character.character_name,
            _("Manager order character %(name)s is not owned by any user")
            % {"name": character.character_name},
        )

    if not user.is_active:
        logger.error("Manager order character %s owner account is disabled", char_id)
        return (
            None,
            character.character_name,
            _("The account owning manager order character %(name)s is disabled")
            % {"name": character.character_name},
        )

    return user, character.character_name, None


def _checkout_context(request: WSGIRequest):
    """Build the checkout page context from the session cart.

    Returns (context, error). On error the caller should redirect away.
    """
    cart = request.session.get(CHECKOUT_SESSION_KEY)
    if not cart:
        return None, _("Your cart is empty")

    lines, deliverysystem, notes, error = _validate_cart_payload(cart)
    if error:
        return None, _(error)

    # managers may tick "Manager Options" to place the order under the
    # configured account instead of themselves
    is_manager = request.user.has_perm("georgeforge.manage_store")
    on_behalf = is_manager and bool(cart.get("on_behalf"))
    manager_character_name = None
    manager_error = None
    order_user = request.user

    if is_manager:
        target_user, manager_character_name, manager_error = _manager_order_target()
        if target_user is not None and on_behalf:
            order_user = target_user

    subtotal = sum(line["line_total"] for line in lines)
    deposit_total = sum(line["line_deposit"] for line in lines)

    discount = _resolve_discount(order_user, cart, lines, subtotal)

    # only the applied discount's eligible lines share the discount
    eligible_ids = discount["eligible_ids"]
    eligible_lines = [
        line
        for line in lines
        if eligible_ids is None or line["for_sale"].id in eligible_ids
    ]
    allocations = _allocate_discount(
        discount["amount"], [line["line_total"] for line in eligible_lines]
    )
    allocation_by_id = {
        line["for_sale"].id: allocation
        for line, allocation in zip(eligible_lines, allocations)
    }

    discount_total = Decimal("0")
    for line in lines:
        allocation = allocation_by_id.get(line["for_sale"].id, Decimal("0.00"))
        line["discount_eligible"] = (
            eligible_ids is None or line["for_sale"].id in eligible_ids
        )
        line["discount_amount"] = allocation
        line["total"] = line["line_total"] - allocation
        discount_total += allocation

    voucher_code = (cart.get("voucher_code") or "").strip()
    selected_affiliation = None if voucher_code else cart.get("affiliation_id")

    affiliation_options = []
    for affiliation in AffiliationDiscount.objects.filter(enabled=True).order_by(
        "name"
    ):
        if not affiliation.user_qualifies(order_user):
            continue

        option_ids_for_aff, option_subtotal = _eligible_subtotal(
            affiliation, lines, subtotal
        )
        if option_ids_for_aff is not None and option_subtotal <= 0:
            # scoped discount with nothing to apply to in this cart
            continue

        affiliation_options.append(
            {
                "id": affiliation.id,
                "name": affiliation.name,
                "display": affiliation.discount_display,
                "amount": affiliation.calculate_discount(option_subtotal),
                "selected": selected_affiliation == affiliation.id,
            }
        )

    applied_label = None
    if discount["voucher"]:
        applied_label = (
            f"{discount['voucher'].code} ({discount['voucher'].discount_display})"
        )
    elif discount["affiliation"]:
        applied_label = (
            f"{discount['affiliation'].name} "
            f"({discount['affiliation'].discount_display})"
        )

    option_ids = [option["id"] for option in affiliation_options]
    if selected_affiliation not in option_ids:
        # no longer selectable (or never was) -> keep the "none" radio checked
        selected_affiliation = None

    context = {
        "lines": lines,
        "subtotal": subtotal,
        "deposit_total": deposit_total,
        "discount_total": discount_total,
        "grand_total": subtotal - discount_total,
        "discount": discount,
        "discount_error": discount["error"],
        "applied_label": applied_label,
        "discount_scoped": bool(
            discount["eligible_ids"] is not None
            and (discount["voucher"] or discount["affiliation"])
        ),
        "voucher_code": voucher_code,
        "selected_affiliation": selected_affiliation,
        "affiliation_options": affiliation_options,
        "deliverysystem": deliverysystem,
        "notes": notes,
        "user_id": request.user.id,
        "is_manager": is_manager,
        "on_behalf": on_behalf,
        "manager_character_name": manager_character_name,
        "manager_error": manager_error,
        "order_user": order_user,
    }

    return context, None


def _apply_discount_form(request: WSGIRequest) -> None:
    """Store the checkout discount form selection in the session."""
    cart = request.session.get(CHECKOUT_SESSION_KEY)
    if cart is None:
        return

    code = (request.POST.get("voucher_code") or "").strip().upper()
    affiliation = request.POST.get("affiliation_discount") or ""

    cart["voucher_code"] = code
    if code:
        # a voucher code always wins over an affiliation discount
        cart["affiliation_id"] = None
    elif affiliation and affiliation != "none":
        try:
            cart["affiliation_id"] = int(affiliation)
        except (TypeError, ValueError):
            cart["affiliation_id"] = None
    else:
        cart["affiliation_id"] = None

    request.session[CHECKOUT_SESSION_KEY] = cart


def _apply_manager_form(request: WSGIRequest) -> None:
    """Store the manager on-behalf checkbox state in the session.

    Ignored without manage_store, so a forged POST cannot move the order
    to another account.
    """
    cart = request.session.get(CHECKOUT_SESSION_KEY)
    if cart is None:
        return

    checked = request.POST.get("on_behalf") in {"1", "on", "true", "True"}
    cart["on_behalf"] = bool(checked) and request.user.has_perm(
        "georgeforge.manage_store"
    )
    request.session[CHECKOUT_SESSION_KEY] = cart


def _append_manager_note(notes: str, manager) -> str:
    """Append which manager placed an on-behalf order to the order notes."""
    main_character = getattr(getattr(manager, "profile", None), "main_character", None)
    name = main_character.character_name if main_character else manager.username
    line = f"Placed by Manager: {name}"
    return f"{notes}\n{line}" if notes else line


def _create_orders(
    request: WSGIRequest,
    lines: list,
    deliverysystem,
    notes: str,
    discount=None,
    order_user=None,
) -> list:
    """Create one Order per cart line, applying any discount allocation.

    order_user defaults to the requesting user; managers placing an order
    on behalf of the configured account pass that account's user instead.
    """
    discount = discount or {}
    voucher = discount.get("voucher")
    affiliation = discount.get("affiliation")
    order_user = order_user or request.user

    cart_session_id = str(uuid.uuid4())
    orders = []

    for line in lines:
        line_total = line["line_total"]
        allocation = line.get("discount_amount", Decimal("0"))

        orders.append(
            Order.objects.create(
                user=order_user,
                price=line["for_sale"].price,
                totalcost=line_total - allocation,
                deposit=line["line_deposit"],
                # only a line that actually took a discount has a "before" price
                original_price=line_total if allocation > 0 else None,
                discount_amount=allocation,
                voucher_code=voucher,
                affiliation_discount=affiliation,
                eve_type=line["for_sale"].eve_type,
                notes=notes,
                description=line["for_sale"].description,
                status=Order.OrderStatus.PENDING,
                deliverysystem=deliverysystem,
                quantity=line["quantity"],
                estimated_delivery_date="",
                cart_session_id=cart_session_id,
            )
        )

    if voucher is not None:
        # one redemption covers the whole cart session
        VoucherRedemption.objects.create(
            voucher=voucher, user=order_user, order=orders[0]
        )

    return orders


def _finalise_cart(request: WSGIRequest, orders: list, on_behalf: bool = False):
    """Deposit message, status defaults, webhooks, DMs and deposit invoice.

    Returns the deposit instructions (or None).
    """
    total_deposit = sum(float(order.deposit) for order in orders)
    deposit_instructions = (
        app_settings.GEORGEFORGE_ORDER_DEPOSIT_INSTRUCTIONS
        if total_deposit > 0 and not on_behalf
        else None
    )

    if deposit_instructions:
        messages.success(request, _(deposit_instructions))

    for order in orders:
        if on_behalf:
            # manager orders placed under the configured account skip the
            # deposit step entirely - no deposit invoice is ever sent
            order.status = Order.OrderStatus.DEPOSIT_RECIEVED
            order.save()
        elif not app_settings.GEORGEFORGE_ORDER_PENDING_DEFAULT:
            order.status = (
                Order.OrderStatus.DEPOSIT_RECIEVED
                if total_deposit == 0
                else Order.OrderStatus.AWAITING_DEPOSIT
            )
            order.save()
        send_order_webhook.delay(order.pk)
        send_statusupdate_dm(order)

    if any(order.status == Order.OrderStatus.AWAITING_DEPOSIT for order in orders):
        # one deposit invoice covers the entire order (cart session)
        send_order_invoice(orders[0])

    return deposit_instructions


@login_required
@permission_required("georgeforge.place_order")
@require_POST
def checkout_prepare(request: WSGIRequest) -> HttpResponse:
    """Store the JS cart in the session and hand off to the checkout page."""
    raw_cart = request.POST.get("cart_data", "")

    try:
        data = json.loads(raw_cart)
    except json.JSONDecodeError:
        messages.error(request, _("Invalid cart data"))
        return redirect("georgeforge:store")

    lines, deliverysystem, notes, error = _validate_cart_payload(data)
    if error:
        messages.error(request, _(error))
        return redirect("georgeforge:store")

    previous = request.session.get(CHECKOUT_SESSION_KEY) or {}

    request.session[CHECKOUT_SESSION_KEY] = {
        "items": [
            {"for_sale_id": line["for_sale"].id, "quantity": line["quantity"]}
            for line in lines
        ],
        "deliverysystem_id": deliverysystem.id,
        "notes": notes,
        # keep any discount the user already applied to this cart
        "voucher_code": previous.get("voucher_code", ""),
        "affiliation_id": previous.get("affiliation_id"),
        # keep any manager on-behalf selection for this cart
        "on_behalf": previous.get("on_behalf", False),
    }

    return redirect("georgeforge:checkout")


@login_required
@permission_required("georgeforge.place_order")
def checkout(request: WSGIRequest) -> HttpResponse:
    """Server rendered checkout: items, discount selection and order placement."""
    if request.method == "POST":
        action = request.POST.get("action")

        if action == "remove_discount":
            cart = request.session.get(CHECKOUT_SESSION_KEY) or {}
            cart["voucher_code"] = ""
            cart["affiliation_id"] = None
            request.session[CHECKOUT_SESSION_KEY] = cart
            return redirect("georgeforge:checkout")

        if action in {"apply_discount", "place_order"}:
            _apply_discount_form(request)
            _apply_manager_form(request)

        if action == "place_order":
            return _place_order(request)

        return redirect("georgeforge:checkout")

    context, error = _checkout_context(request)
    if error:
        messages.info(request, error)
        return redirect("georgeforge:store")

    return render(request, "georgeforge/views/checkout.html", context)


def _place_order(request: WSGIRequest) -> HttpResponse:
    """Validate the discount again, create the orders and clear the session."""
    context, error = _checkout_context(request)
    if error:
        messages.error(request, error)
        return redirect("georgeforge:store")

    if context["on_behalf"] and context["manager_error"]:
        # never fall back to the manager's own account silently
        messages.error(request, context["manager_error"])
        return redirect("georgeforge:checkout")

    if context["discount_error"]:
        # the page re-renders with the inline discount error
        return redirect("georgeforge:checkout")

    notes = context["notes"]
    if context["on_behalf"]:
        # record which manager actually placed the order
        notes = _append_manager_note(notes, request.user)

    orders = _create_orders(
        request,
        context["lines"],
        context["deliverysystem"],
        notes,
        context["discount"],
        order_user=context["order_user"],
    )
    deposit_instructions = _finalise_cart(
        request, orders, on_behalf=context["on_behalf"]
    )

    messages.success(request, _("Your order has been placed!"))
    if deposit_instructions:
        messages.success(request, _(deposit_instructions))

    request.session.pop(CHECKOUT_SESSION_KEY, None)
    # tells the orders page to clear the browser-side cart
    request.session["georgeforge_cart_clear"] = True

    return redirect("georgeforge:my_orders")


@login_required
@permission_required("georgeforge.place_order")
@require_POST
def cart_checkout_api(request: WSGIRequest) -> JsonResponse:
    """Cart checkout API endpoint (JSON, no discounts)

    :param request: WSGIRequest:
    :return: JsonResponse:

    """
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"success": False, "error": "Invalid JSON"}, status=400)

    lines, deliverysystem, notes, error = _validate_cart_payload(data)
    if error:
        return JsonResponse({"success": False, "error": error}, status=400)

    orders = _create_orders(request, lines, deliverysystem, notes)
    deposit_instructions = _finalise_cart(request, orders)

    return JsonResponse(
        {
            "success": True,
            "orders": [
                {
                    "id": order.id,
                    "eve_type": order.eve_type.name,
                    "quantity": order.quantity,
                    "totalcost": float(order.totalcost),
                    "deposit": float(order.deposit),
                }
                for order in orders
            ],
            "cart_session_id": orders[0].cart_session_id,
            "deposit_instructions": deposit_instructions,
        }
    )


@login_required
@permission_required("georgeforge.manage_store")
def all_orders(request: WSGIRequest) -> HttpResponse:
    """Order Management handler/view

    :param request: WSGIRequest:

    """
    orders = (
        Order.objects.select_related()
        .filter(status__lt=Order.OrderStatus.DELIVERED)
        .order_by("-id")
    )
    done_orders = (
        Order.objects.select_related()
        .filter(status__gte=Order.OrderStatus.DELIVERED)
        .order_by("-id")
    )
    dsystems = []
    for x in DeliverySystem.objects.select_related().all():
        dsystems.append([x.system.id, x.friendly])
    context = {
        "all_orders": orders,
        "done_orders": done_orders,
        "status": Order.OrderStatus.choices,
        "dsystems": dsystems,
    }

    return render(request, "georgeforge/views/all_orders.html", context)


@login_required
@permission_required("georgeforge.manage_store")
@require_POST
def order_update_status(request: WSGIRequest, order_id: int) -> JsonResponse:
    """AJAX endpoint to update order status

    :param request: WSGIRequest:
    :param order_id: Order ID:
    :return: JsonResponse:

    """
    try:
        order = Order.objects.get(id=order_id)
    except Order.DoesNotExist:
        return JsonResponse({"success": False, "error": "Order not found"}, status=404)

    try:
        status = int(request.POST.get("value"))
    except (ValueError, TypeError):
        return JsonResponse(
            {"success": False, "error": "Invalid status value"}, status=400
        )

    if status not in dict(Order.OrderStatus.choices).keys():
        return JsonResponse(
            {"success": False, "error": "Not a valid status"}, status=400
        )

    old_status = order.status
    order.status = status
    order.save()
    updated_orders = [
        {"pk": order.pk, "status": status, "display": order.get_status_display()}
    ]

    if order.status != old_status:
        if order.status == Order.OrderStatus.DEPOSIT_RECIEVED:
            # One invoice covers the checkout, so receiving the deposit on one
            # line item applies to every line item still awaiting that deposit.
            linked_orders = Order.objects.filter(
                cart_session_id=order.cart_session_id,
                status=Order.OrderStatus.AWAITING_DEPOSIT,
            ).exclude(pk=order.pk)
            for linked_order in linked_orders:
                linked_order.status = Order.OrderStatus.DEPOSIT_RECIEVED
                linked_order.save()
                send_statusupdate_dm(linked_order)
                updated_orders.append(
                    {
                        "pk": linked_order.pk,
                        "status": linked_order.status,
                        "display": linked_order.get_status_display(),
                    }
                )
            send_statusupdate_dm(order)
            Order.cancel_invoice(order)
        else:
            send_statusupdate_dm(order)
            if order.status == Order.OrderStatus.AWAITING_DEPOSIT:
                send_order_invoice(order)
            if order.status == Order.OrderStatus.REJECTED:
                Order.cancel_invoice(order)
                # Regenerate the session invoice for any remaining line items;
                # no-op if nothing is left awaiting a deposit.
                send_order_invoice(order)

    logger.info(
        f"Updated order {order_id} status from {old_status} to {status} by {request.user}"
    )

    return JsonResponse(
        {
            "success": True,
            "pk": order_id,
            "newValue": status,
            "display": order.get_status_display(),
            "updatedOrders": updated_orders,
        }
    )


@login_required
@permission_required("georgeforge.manage_store")
@require_POST
def order_update_paid(request: WSGIRequest, order_id: int) -> JsonResponse:
    """AJAX endpoint to update order paid amount

    :param request: WSGIRequest:
    :param order_id: Order ID:
    :return: JsonResponse:

    """
    try:
        order = Order.objects.get(id=order_id)
    except Order.DoesNotExist:
        return JsonResponse({"success": False, "error": "Order not found"}, status=404)

    try:
        paid = float(request.POST.get("value").strip(","))
    except (ValueError, TypeError, AttributeError):
        return JsonResponse(
            {"success": False, "error": "Invalid paid amount"}, status=400
        )

    if paid < 0.00:
        return JsonResponse(
            {"success": False, "error": "Negative payment not allowed"}, status=400
        )

    order.paid = paid
    order.save()

    logger.info(f"Updated order {order_id} paid amount to {paid} by {request.user}")

    return JsonResponse({"success": True, "pk": order_id, "newValue": paid})


@login_required
@permission_required("georgeforge.manage_store")
@require_POST
def order_update_quantity(request: WSGIRequest, order_id: int) -> JsonResponse:
    """AJAX endpoint to update order quantity

    :param request: WSGIRequest:
    :param order_id: Order ID:
    :return: JsonResponse:

    """
    try:
        order = Order.objects.get(id=order_id)
    except Order.DoesNotExist:
        return JsonResponse({"success": False, "error": "Order not found"}, status=404)

    try:
        quantity = int(request.POST.get("value"))
    except (ValueError, TypeError):
        return JsonResponse({"success": False, "error": "Invalid quantity"}, status=400)

    if quantity < 1:
        return JsonResponse(
            {"success": False, "error": "Minimum quantity is 1"}, status=400
        )

    order.quantity = quantity
    order.totalcost = order.price * quantity
    order.save()

    logger.info(f"Updated order {order_id} quantity to {quantity} by {request.user}")

    return JsonResponse({"success": True, "pk": order_id, "newValue": quantity})


@login_required
@permission_required("georgeforge.manage_store")
@require_POST
def order_update_system(request: WSGIRequest, order_id: int) -> JsonResponse:
    """AJAX endpoint to update order delivery system

    :param request: WSGIRequest:
    :param order_id: Order ID:
    :return: JsonResponse:

    """
    try:
        order = Order.objects.get(id=order_id)
    except Order.DoesNotExist:
        return JsonResponse({"success": False, "error": "Order not found"}, status=404)

    try:
        system_id = int(request.POST.get("value"))
    except (ValueError, TypeError):
        return JsonResponse(
            {"success": False, "error": "Invalid system ID"}, status=400
        )

    try:
        deliverysystem = (
            DeliverySystem.objects.select_related("system")
            .get(system_id=system_id, enabled=True)
            .system
        )
    except DeliverySystem.DoesNotExist:
        return JsonResponse(
            {"success": False, "error": "Invalid or disabled delivery system"},
            status=400,
        )

    order.deliverysystem = deliverysystem
    order.save()

    logger.info(
        f"Updated order {order_id} delivery system to {system_id} by {request.user}"
    )

    return JsonResponse(
        {
            "success": True,
            "pk": order_id,
            "newValue": system_id,
            "display": deliverysystem.name,
        }
    )


@login_required
@permission_required("georgeforge.manage_store")
@require_POST
def order_update_estimated_date(request: WSGIRequest, order_id: int) -> JsonResponse:
    """AJAX endpoint to update order estimated delivery date

    :param request: WSGIRequest:
    :param order_id: Order ID:
    :return: JsonResponse:

    """
    try:
        order = Order.objects.get(id=order_id)
    except Order.DoesNotExist:
        return JsonResponse({"success": False, "error": "Order not found"}, status=404)

    date_value = request.POST.get("value")

    old_date = order.estimated_delivery_date
    if not date_value or date_value.strip() == "":
        order.estimated_delivery_date = ""
    else:
        order.estimated_delivery_date = date_value.strip()

    order.save()

    if order.estimated_delivery_date != old_date:
        send_deliverydateupdate_dm(order)

    logger.info(
        f"Updated order {order_id} estimated delivery date to {order.estimated_delivery_date} by {request.user}"
    )

    return JsonResponse(
        {
            "success": True,
            "pk": order_id,
            "newValue": (
                str(order.estimated_delivery_date)
                if order.estimated_delivery_date
                else ""
            ),
        }
    )


@login_required
@permission_required("georgeforge.manage_store")
def bulk_import_form(request: WSGIRequest) -> HttpResponse:
    """

    :param request: WSGIRequest:

    """
    if request.method == "POST":
        form = BulkImportStoreItemsForm(request.POST)

        if form.is_valid():
            data = form.cleaned_data["data"]
            non_destructive = (
                form.cleaned_data["import_mode"]
                == BulkImportStoreItemsForm.MODE_ADDITIVE
            )
            parsed = [
                row
                for row in csv.DictReader(
                    data.splitlines(),
                    fieldnames=["Item Name", "Description", "Price", "Deposit"],
                )
            ]

            if not non_destructive:
                ForSale.objects.all().delete()

            had_error = 0

            for item in parsed:
                try:
                    eve_type = ItemType.objects.filter(published=1).get(
                        name=item["Item Name"]
                    )

                    try:
                        price_val = float(item["Price"])
                        deposit_val = float(item["Deposit"])
                    except (ValueError, TypeError):
                        messages.warning(
                            request,
                            _("%(name)s has invalid price or deposit value")
                            % {"name": item["Item Name"]},
                        )
                        had_error += 1
                        continue

                    if price_val <= 0:
                        messages.warning(
                            request,
                            _("%(name)s price must be greater than zero")
                            % {"name": item["Item Name"]},
                        )
                        had_error += 1
                        continue

                    if deposit_val < 0:
                        messages.warning(
                            request,
                            _("%(name)s deposit cannot be negative")
                            % {"name": item["Item Name"]},
                        )
                        had_error += 1
                        continue

                    ForSale.objects.update_or_create(
                        eve_type=eve_type,
                        defaults={
                            "description": item["Description"],
                            "price": price_val,
                            "deposit": deposit_val,
                        },
                    )
                except ObjectDoesNotExist:
                    messages.warning(
                        request,
                        _("%(name)s does not exist and was not added")
                        % {"name": item["Item Name"]},
                    )
                    had_error += 1
                except ValidationError as ex:
                    messages.warning(
                        request,
                        _("%(name)s had a validation error: %(error)s")
                        % {"name": item["Item Name"], "error": ex.message}
                        % ex.params,
                    )
                    had_error += 1

            imported = len(parsed) - had_error

            if imported > 0:
                messages.success(
                    request,
                    _("Imported %(n)s item%(plural)s")
                    % {"n": imported, "plural": pluralize(imported)},
                )

            return redirect("georgeforge:bulk_import_form")

    context = {"form": BulkImportStoreItemsForm()}

    return render(request, "georgeforge/views/bulk_import_form.html", context)


@login_required
@permission_required("georgeforge.manage_store")
def export_offers(request: WSGIRequest) -> HttpResponse:
    """

    :param request: WSGIRequest:

    """
    response = HttpResponse(
        content_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="auth_forsale.csv"'},
    )

    writer = csv.writer(response)
    for listing in ForSale.objects.all():
        writer.writerow(
            [listing.eve_type.name, listing.description, listing.price, listing.deposit]
        )
    return response


@login_required
@permission_required("georgeforge.manage_store")
def admin_create_tasks(request):
    schedule_invoice_status, _ = CrontabSchedule.objects.get_or_create(
        minute="15,30,45",
        hour="*",
        day_of_week="*",
        day_of_month="*",
        month_of_year="*",
        timezone="UTC",
    )

    PeriodicTask.objects.update_or_create(
        task="georgeforge.tasks.check_invoice_status",
        defaults={
            "crontab": schedule_invoice_status,
            "name": "GeorgeForge: Scan deposits",
            "enabled": True,
        },
    )
    messages.info(request, "Created/Reset Invoice Task to defaults")

    return redirect("georgeforge:store")
