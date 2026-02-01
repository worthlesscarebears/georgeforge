"""Admin models"""

# Django
from django.contrib import admin

# George Forge
from georgeforge.models import DeliverySystem, ForSale, Order


class ManageStoreAdmin(admin.ModelAdmin):
    def _has_perm(self, request) -> bool:
        return request.user.has_perm("georgeforge.manage_store")

    def has_view_permission(self, request, obj=None):
        return self._has_perm(request)

    def has_add_permission(self, request):
        return self._has_perm(request)

    def has_change_permission(self, request, obj=None):
        return self._has_perm(request)

    def has_delete_permission(self, request, obj=None):
        return self._has_perm(request)


@admin.register(ForSale)
class ForSaleAdmin(ManageStoreAdmin):
    """ """

    list_display = ["eve_type", "description", "deposit", "price"]
    #autocomplete_fields = ["eve_type"]


@admin.register(DeliverySystem)
class DeliverySystemAdmin(ManageStoreAdmin):
    """ """

    list_display = ["system", "enabled", "friendly_name"]
    #autocomplete_fields = ["system"]


@admin.register(Order)
class OrderAdmin(ManageStoreAdmin):
    """ """

    list_display = [
        "user",
        "status",
        "eve_type",
        "price",
        "description",
        "notes",
        "estimated_delivery_date",
        "cart_session_id",
    ]
    #autocomplete_fields = ["eve_type"]
