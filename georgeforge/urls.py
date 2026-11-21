"""App URLs"""

# Django
from django.urls import path

# George Forge
from georgeforge import views

app_name: str = "georgeforge"

urlpatterns = [
    path("store", views.store, name="store"),
    path("checkout", views.checkout, name="checkout"),
    path("checkout/prepare", views.checkout_prepare, name="checkout_prepare"),
    path("orders", views.my_orders, name="my_orders"),
    path("orders/all", views.all_orders, name="all_orders"),
    path("api/cart/checkout", views.cart_checkout_api, name="cart_checkout_api"),
    path(
        "api/orders/<int:order_id>/status",
        views.order_update_status,
        name="order_update_status",
    ),
    path(
        "api/orders/<int:order_id>/paid",
        views.order_update_paid,
        name="order_update_paid",
    ),
    path(
        "api/orders/<int:order_id>/quantity",
        views.order_update_quantity,
        name="order_update_quantity",
    ),
    path(
        "api/orders/<int:order_id>/system",
        views.order_update_system,
        name="order_update_system",
    ),
    path(
        "api/orders/<int:order_id>/estimated-date",
        views.order_update_estimated_date,
        name="order_update_estimated_date",
    ),
    path("bulk_import_form", views.bulk_import_form, name="bulk_import_form"),
    path("bulk_import_form/export", views.export_offers, name="export_offers"),
    path("admin/tasks", views.admin_create_tasks, name="admin_create_tasks"),
]
