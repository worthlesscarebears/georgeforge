"""App Views"""

# Standard Library
import csv
import itertools
import logging
import uuid
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

# Alliance Auth (External Libs)
from eveuniverse.models import EveType

# George Forge
from georgeforge.forms import BulkImportStoreItemsForm
from georgeforge.models import DeliverySystem, ForSale, Order
from georgeforge.tasks import (
    send_deliverydateupdate_dm,
    send_order_invoice,
    send_order_webhook,
    send_statusupdate_dm,
)

from . import app_settings

logger = logging.getLogger(__name__)


@login_required
@permission_required("georgeforge.place_order")
def store(request: WSGIRequest) -> HttpResponse:
    """Store view

    :param request: WSGIRequest:

    """

    for_sale = (
        ForSale.objects.select_related("eve_type__eve_group")
        .all()
        .order_by("eve_type__eve_group__name")
    )

    groups = [
        (key, list(l))
        for key, l in itertools.groupby(
            for_sale, key=attrgetter("eve_type.eve_group.name")
        )
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
    }

    return render(request, "georgeforge/views/my_orders.html", context)


@login_required
@permission_required("georgeforge.place_order")
@require_POST
def cart_checkout_api(request: WSGIRequest) -> JsonResponse:
    """Cart checkout API endpoint

    :param request: WSGIRequest:
    :return: JsonResponse:

    """
    # Standard Library
    import json

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"success": False, "error": "Invalid JSON"}, status=400)

    items = data.get("items", [])
    deliverysystem_id = data.get("deliverysystem_id")
    notes = data.get("notes", "")

    if not items:
        return JsonResponse({"success": False, "error": "No items in cart"}, status=400)

    if not deliverysystem_id:
        return JsonResponse(
            {"success": False, "error": "Delivery system required"}, status=400
        )

    try:
        deliverysystem = (
            DeliverySystem.objects.select_related("system")
            .get(system_id=deliverysystem_id, enabled=True)
            .system
        )
    except DeliverySystem.DoesNotExist:
        return JsonResponse(
            {"success": False, "error": "Invalid or disabled delivery system"},
            status=400,
        )

    cart_session_id = str(uuid.uuid4())

    items_dict = {}
    for item in items:
        for_sale_id = item.get("for_sale_id")
        quantity = item.get("quantity", 1)

        if quantity < 1:
            return JsonResponse(
                {"success": False, "error": "Minimum quantity 1"}, status=400
            )

        if for_sale_id in items_dict:
            items_dict[for_sale_id] += quantity
        else:
            items_dict[for_sale_id] = quantity

    orders = []

    for for_sale_id, quantity in items_dict.items():
        try:
            for_sale = ForSale.objects.get(id=for_sale_id)
        except ForSale.DoesNotExist:
            return JsonResponse(
                {"success": False, "error": f"Item {for_sale_id} not found"}, status=400
            )

        order = Order.objects.create(
            user=request.user,
            price=for_sale.price,
            totalcost=(for_sale.price * quantity),
            deposit=(for_sale.deposit * quantity),
            eve_type=for_sale.eve_type,
            notes=notes,
            description=for_sale.description,
            status=Order.OrderStatus.PENDING,
            deliverysystem=deliverysystem,
            quantity=quantity,
            estimated_delivery_date="",
            cart_session_id=cart_session_id,
        )

        orders.append(order)

    total_deposit = sum(float(order.deposit) for order in orders)
    deposit_instructions = (
        app_settings.GEORGEFORGE_ORDER_DEPOSIT_INSTRUCTIONS
        if total_deposit > 0
        else None
    )

    if deposit_instructions:
        messages.success(request, _(deposit_instructions))

    for order in orders:
        if not app_settings.GEORGEFORGE_ORDER_PENDING_DEFAULT:
            order.status = Order.OrderStatus.AWAITING_DEPOSIT
            order.save()
            send_order_invoice(order)
        send_order_webhook.delay(order.pk)
        send_statusupdate_dm(order)

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
            "cart_session_id": cart_session_id,
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

    if order.status != old_status:
        send_statusupdate_dm(order)
        if order.status == Order.OrderStatus.AWAITING_DEPOSIT:
            send_order_invoice(order)
        if order.status == Order.OrderStatus.REJECTED:
            Order.cancel_invoice(order_id)

    logger.info(
        f"Updated order {order_id} status from {old_status} to {status} by {request.user}"
    )

    return JsonResponse(
        {
            "success": True,
            "pk": order_id,
            "newValue": status,
            "display": order.get_status_display(),
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
            parsed = [
                row
                for row in csv.DictReader(
                    data.splitlines(),
                    fieldnames=["Item Name", "Description", "Price", "Deposit"],
                )
            ]
            ForSale.objects.all().delete()

            had_error = 0

            for item in parsed:
                try:
                    eve_type = EveType.objects.filter(
                        eve_group__eve_category_id__in=app_settings.GEORGEFORGE_CATEGORIES
                    ).get(name=item["Item Name"])

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

                    ForSale.objects.create(
                        eve_type=eve_type,
                        description=item["Description"],
                        price=price_val,
                        deposit=deposit_val,
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
