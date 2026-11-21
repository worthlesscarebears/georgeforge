"""
App Models
"""

# Standard Library
import base64
import uuid
from decimal import ROUND_DOWN, Decimal

# Third Party
from invoices.models import Invoice

# Django
from django.conf import settings
from django.contrib.auth.models import User
from django.core.validators import MinValueValidator
from django.db import models
from django.utils.translation import gettext_lazy as _

# Alliance Auth (External Libs)
from eve_sde.models import ItemType, SolarSystem

# George Forge
from georgeforge import app_settings


def generate_invoice_ref(session_id: str) -> str:
    """Return the deposit invoice reference for a cart session.

    The reference has to be entered into the EVE in-game wallet transfer
    reason field, which silently truncates at 40 characters. A raw UUID
    makes refs too long (GF-DEP- + 36 chars = 43), so compress the UUID
    to unpadded base32 (26 chars) for a 33 character reference.
    """
    try:
        raw = uuid.UUID(str(session_id)).bytes
    except (ValueError, AttributeError, TypeError):
        return f"GF-DEP-{session_id}"  # not a uuid, use it as-is
    return f"GF-DEP-{base64.b32encode(raw).decode().rstrip('=')}"


class General(models.Model):
    """Meta model for app permissions"""

    class Meta:
        """Meta definitions"""

        managed = False
        default_permissions = ()
        permissions = (
            ("place_order", "Can place an order"),
            ("manage_store", "Can manage the store"),
        )


class ForSale(models.Model):
    """An item for sale"""

    class Meta:
        default_permissions = ()

    eve_type = models.ForeignKey(
        ItemType,
        verbose_name=_("EVE Type"),
        on_delete=models.CASCADE,
        limit_choices_to={"published": 1},
    )

    description = models.TextField(
        _("Description"),
        blank=True,
        max_length=4096,
    )

    price = models.DecimalField(
        _("Price"),
        max_digits=15,
        decimal_places=2,
        help_text=_("Cost per unit"),
        validators=[MinValueValidator(1)],
    )

    deposit = models.DecimalField(
        _("Deposit"),
        default=0,
        max_digits=15,
        decimal_places=2,
        help_text=_("Deposit per unit"),
    )

    def __str__(self) -> str:
        return self.eve_type.name


class DeliverySystem(models.Model):
    """A SolarSystem Available for orders to be delivered to"""

    class Meta:
        default_permissions = ()

    system = models.ForeignKey(
        SolarSystem,
        verbose_name=_("Solar System"),
        on_delete=models.CASCADE,
    )

    friendly_name = models.TextField(
        _("Friendly Name"),
        max_length=32,
        default=None,
        null=True,
        blank=True,
    )

    enabled = models.BooleanField(
        default=True,
    )

    @property
    def friendly(self):
        if self.friendly_name:
            return f"{self.system.name} - {self.friendly_name}"
        return self.system.name


class DiscountMixin(models.Model):
    """Shared percent / flat-ISK discount configuration"""

    class DiscountType(models.TextChoices):
        PERCENT = "percent", _("Percent")
        FLAT = "flat", _("Flat ISK")

    class Meta:
        abstract = True

    discount_type = models.CharField(
        _("Discount type"),
        max_length=16,
        choices=DiscountType.choices,
        default=DiscountType.PERCENT,
    )

    value = models.DecimalField(
        _("Value"),
        max_digits=15,
        decimal_places=2,
        help_text=_("Percentage of the order total, or a flat ISK amount"),
        validators=[MinValueValidator(0)],
    )

    def calculate_discount(self, subtotal: Decimal) -> Decimal:
        """Return the discount for a subtotal, floored at zero"""
        if subtotal <= 0:
            return Decimal("0.00")
        if self.discount_type == self.DiscountType.PERCENT:
            amount = subtotal * self.value / Decimal("100")
        else:
            amount = self.value
        amount = amount.quantize(Decimal("0.01"), rounding=ROUND_DOWN)
        return min(amount, subtotal)

    @property
    def discount_display(self) -> str:
        if self.discount_type == self.DiscountType.PERCENT:
            return f"{self.value}%"
        return f"{self.value:,.2f} ISK"

    @property
    def scoped_item_ids(self) -> set | None:
        """IDs of the store items this discount applies to.

        None means the discount applies to every item.
        """
        item_ids = set(self.items.values_list("id", flat=True))
        return item_ids or None


class VoucherCode(DiscountMixin):
    """A discount code redeemable at checkout"""

    class Meta:
        default_permissions = ()

    code = models.CharField(
        _("Code"),
        max_length=64,
        unique=True,
        help_text=_("Customers enter this code at checkout"),
    )

    description = models.TextField(
        _("Description"),
        blank=True,
        max_length=1024,
        help_text=_("Internal note, not shown to customers"),
    )

    max_uses = models.PositiveIntegerField(
        _("Maximum uses"),
        null=True,
        blank=True,
        help_text=_("Leave blank for unlimited uses"),
    )

    one_use_per_user = models.BooleanField(
        _("One use per user"),
        default=False,
    )

    expires_at = models.DateTimeField(
        _("Expires at"),
        null=True,
        blank=True,
        help_text=_("Leave blank for no expiry"),
    )

    enabled = models.BooleanField(_("Enabled"), default=True)

    items = models.ManyToManyField(
        ForSale,
        verbose_name=_("Items"),
        blank=True,
        related_name="voucher_codes",
        help_text=_(
            "Limit this code to these store items only. "
            "Leave blank to allow every item."
        ),
    )

    def save(self, *args, **kwargs):
        self.code = self.code.strip().upper()
        super().save(*args, **kwargs)

    @property
    def use_count(self) -> int:
        return self.redemptions.count()

    @property
    def is_usable(self) -> bool:
        """Whether the voucher is currently redeemable by anyone"""
        # Django
        from django.utils import timezone

        if not self.enabled:
            return False
        if self.expires_at and self.expires_at < timezone.now():
            return False
        if self.max_uses is not None and self.use_count >= self.max_uses:
            return False
        return True

    def unavailable_reason(self, user) -> str | None:
        """Why this voucher cannot be used by the given user, else None"""
        # Django
        from django.utils import timezone

        if not self.enabled:
            return _("This code is not active")
        if self.expires_at and self.expires_at < timezone.now():
            return _("This code has expired")
        if self.max_uses is not None and self.use_count >= self.max_uses:
            return _("This code has reached its usage limit")
        if self.one_use_per_user and self.redemptions.filter(user=user).exists():
            return _("You have already used this code")
        return None

    def __str__(self) -> str:
        return self.code


class VoucherRedemption(models.Model):
    """A single use of a VoucherCode"""

    class Meta:
        default_permissions = ()

    voucher = models.ForeignKey(
        VoucherCode,
        verbose_name=_("Voucher"),
        related_name="redemptions",
        on_delete=models.CASCADE,
    )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_("User"),
        on_delete=models.RESTRICT,
    )

    order = models.ForeignKey(
        "Order",
        verbose_name=_("Order"),
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="voucher_redemptions",
    )

    used_at = models.DateTimeField(_("Used at"), auto_now_add=True)

    def __str__(self) -> str:
        return f"{self.voucher.code} - {self.user}"


class AffiliationDiscount(DiscountMixin):
    """An automatic discount for users matching any linked group or state"""

    class Meta:
        default_permissions = ()

    name = models.CharField(_("Name"), max_length=100)

    groups = models.ManyToManyField(
        "auth.Group",
        verbose_name=_("Groups"),
        blank=True,
        related_name="georgeforge_discounts",
        help_text=_("Users in any of these groups qualify"),
    )

    states = models.ManyToManyField(
        "authentication.State",
        verbose_name=_("States"),
        blank=True,
        related_name="georgeforge_discounts",
        help_text=_("Users in any of these states qualify"),
    )

    items = models.ManyToManyField(
        ForSale,
        verbose_name=_("Items"),
        blank=True,
        related_name="affiliation_discounts",
        help_text=_(
            "Limit this discount to these store items only. "
            "Leave blank to allow every item."
        ),
    )

    enabled = models.BooleanField(_("Enabled"), default=True)

    @property
    def is_usable(self) -> bool:
        return self.enabled

    def user_qualifies(self, user) -> bool:
        """Whether the given user matches this discount's affiliation rules"""
        # Alliance Auth
        from allianceauth.authentication.models import State

        if not self.enabled:
            return False
        if (
            self.groups.exists()
            and user.groups.filter(
                pk__in=self.groups.values_list("pk", flat=True)
            ).exists()
        ):
            return True
        if self.states.exists():
            user_state = State.objects.get_for_user(user)
            if user_state.pk in self.states.values_list("pk", flat=True):
                return True
        return False

    def __str__(self) -> str:
        return self.name


class Order(models.Model):
    """An order from a user"""

    class Meta:
        default_permissions = ()

    class OrderStatus(models.IntegerChoices):
        """ """

        PENDING = 10, _("Pending")
        AWAITING_DEPOSIT = 20, _("Awaiting Deposit")
        DEPOSIT_RECIEVED = 25, _("Deposit Recieved")
        BUILDING_PARTS = 30, _("Building Parts")
        BUILDING_HULL = 35, _("Building Hull")
        AWAITING_FINAL_PAYMENT = 40, _("Contract Up")
        DELIVERED = 50, _("Delivered")
        REJECTED = 60, _("Rejected")

    user = models.ForeignKey(
        User,
        verbose_name=_("Purchaser"),
        on_delete=models.RESTRICT,
    )

    price = models.DecimalField(
        _("Price per unit"),
        max_digits=15,
        decimal_places=2,
        help_text=_("Cost per unit"),
    )

    totalcost = models.DecimalField(
        _("Total Order cost"),
        max_digits=25,
        decimal_places=2,
        help_text=_("Total Order cost"),
    )

    deposit = models.DecimalField(
        _("Deposit required per unit"),
        max_digits=25,
        decimal_places=2,
        help_text=_("Deposit required per unit"),
    )

    paid = models.DecimalField(
        _("Amount Paid"),
        default=0,
        max_digits=25,
        decimal_places=2,
        help_text=_("Amount paid"),
    )

    eve_type = models.ForeignKey(
        ItemType,
        verbose_name=_("EVE Type"),
        on_delete=models.CASCADE,
        limit_choices_to={"published": 1},
    )

    quantity = models.PositiveIntegerField(
        _("Quantity"),
        default=1,
        validators=[MinValueValidator(1)],
    )

    notes = models.TextField(
        _("Notes"),
        blank=True,
        max_length=4096,
    )

    description = models.TextField(
        _("Description"),
        blank=True,
        max_length=4096,
    )

    deliverysystem = models.ForeignKey(
        SolarSystem,
        verbose_name=_("Delivery System"),
        on_delete=models.CASCADE,
    )

    status = models.IntegerField(_("Status"), choices=OrderStatus.choices)

    cart_session_id = models.CharField(
        _("Cart Session ID"),
        max_length=64,
        db_index=True,
    )

    estimated_delivery_date = models.CharField(
        _("Estimated Delivery Date"),
        max_length=50,
        blank=True,
        help_text=_("Estimated date when the order will be delivered"),
    )

    voucher_code = models.ForeignKey(
        VoucherCode,
        verbose_name=_("Voucher code"),
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="orders",
    )

    affiliation_discount = models.ForeignKey(
        AffiliationDiscount,
        verbose_name=_("Affiliation discount"),
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="orders",
    )

    discount_amount = models.DecimalField(
        _("Discount amount"),
        max_digits=25,
        decimal_places=2,
        default=0,
        help_text=_("ISK deducted from total cost by the applied discount"),
    )

    original_price = models.DecimalField(
        _("Original price"),
        max_digits=25,
        decimal_places=2,
        null=True,
        blank=True,
        help_text=_("Line total before discount, if any"),
    )

    @property
    def invoice_ref(self):
        """Reference of the deposit invoice covering the cart session
        (i.e. the entire order) this line item belongs to"""
        return generate_invoice_ref(self.cart_session_id)

    @classmethod
    def ping_invoice(cls, inv):
        # ping the invoice to the user ( if we know them )
        message = f"{inv.note}\n\nPlease [CLICK HERE]({settings.SITE_URL}/invoice/r/) for instructions on how to pay your deposit!\n"
        inv.notify(message, title=app_settings.GEORGEFORGE_APP_NAME)

    @classmethod
    def generate_invoice(cls, cid, orders, due_date):
        """Create or update the single deposit invoice covering the given
        line items (an entire cart session).

        :param cid: character id to bill
        :param orders: iterable of Order line items sharing a cart session
        :param due_date: invoice due date
        """
        orders = list(orders)
        session_id = orders[0].cart_session_id
        ref = generate_invoice_ref(session_id)
        order_refs = ", ".join(f"#{order.pk}" for order in orders)
        line_items = ", ".join(
            f"{order.quantity}x {order.eve_type.name}" for order in orders
        )
        msg = f"Deposit invoice for Order(s) {order_refs} ({line_items})"
        outstanding = sum(order.deposit - order.paid for order in orders)
        # rounding to whole thousands must never ask for more than is owed
        amount = min(round(outstanding, -3), outstanding)

        try:
            inv = Invoice.objects.get(invoice_ref=ref)
        except Invoice.DoesNotExist:
            return Invoice.objects.create(
                character_id=cid,
                amount=amount,
                invoice_ref=ref,
                note=msg,
                due_date=due_date,
            )
        else:
            # never touch an invoice that has already been paid
            if not inv.paid:
                inv.character_id = cid
                inv.amount = amount
                inv.note = msg
                inv.due_date = due_date
                inv.save()
            return inv

    @classmethod
    def cancel_invoice(cls, order):
        """Delete the deposit invoice covering the cart session the given
        order (line item) belongs to.

        Unpaid invoices are removed; paid ones are left alone. Callers can
        regenerate the invoice for any remaining line items of the session
        afterwards (see georgeforge.tasks.send_order_invoice).

        :param order: an Order (line item) of the affected cart session
        """
        refs = [order.invoice_ref]
        # include legacy per-line-item refs so older invoices get cleaned up too
        refs.extend(
            f"GF-DEP-{pk}"
            for pk in cls.objects.filter(
                cart_session_id=order.cart_session_id
            ).values_list("pk", flat=True)
        )
        deleted, _ = Invoice.objects.filter(invoice_ref__in=refs, paid=False).delete()
        return deleted > 0
