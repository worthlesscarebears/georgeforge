"""Admin models"""

# Django
from django.contrib import admin

# George Forge
from georgeforge.models import (
    AffiliationDiscount,
    DeliverySystem,
    ForSale,
    Order,
    VoucherCode,
    VoucherRedemption,
)


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
    # autocomplete_fields = ["eve_type"]


@admin.register(DeliverySystem)
class DeliverySystemAdmin(ManageStoreAdmin):
    """ """

    list_display = ["system", "enabled", "friendly_name"]
    # autocomplete_fields = ["system"]


class ItemScopeAdminMixin:
    """Shared "Applies to" column for item-scoped discounts"""

    @admin.display(description="Applies to")
    def scope(self, obj):
        count = obj.items.count()
        if not count:
            return "All items"
        return f"{count} item(s)"


class VoucherRedemptionInline(admin.TabularInline):
    model = VoucherRedemption
    extra = 0
    readonly_fields = ["user", "order", "used_at"]
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(VoucherCode)
class VoucherCodeAdmin(ManageStoreAdmin, ItemScopeAdminMixin):
    """ """

    list_display = [
        "code",
        "discount_type",
        "value",
        "scope",
        "max_uses",
        "use_count",
        "one_use_per_user",
        "expires_at",
        "enabled",
    ]
    list_filter = ["enabled", "discount_type", "one_use_per_user"]
    search_fields = ["code", "description"]
    filter_horizontal = ["items"]
    readonly_fields = []
    inlines = [VoucherRedemptionInline]

    def get_readonly_fields(self, request, obj=None):
        return ["use_count"] if obj else []


@admin.register(AffiliationDiscount)
class AffiliationDiscountAdmin(ManageStoreAdmin, ItemScopeAdminMixin):
    """ """

    list_display = ["name", "discount_type", "value", "scope", "enabled"]
    list_filter = ["enabled", "discount_type"]
    search_fields = ["name"]
    filter_horizontal = ["groups", "states", "items"]


@admin.register(Order)
class OrderAdmin(ManageStoreAdmin):
    """ """

    list_display = [
        "user",
        "status",
        "eve_type",
        "price",
        "original_price",
        "discount_amount",
        "voucher_code",
        "affiliation_discount",
        "description",
        "notes",
        "estimated_delivery_date",
        "cart_session_id",
        "invoice_ref",
    ]
    list_filter = ["status", "voucher_code", "affiliation_discount"]
    autocomplete_fields = ["eve_type"]
