"""
App Models
"""

# Third Party
from invoices.models import Invoice

# Django
from django.conf import settings
from django.contrib.auth.models import User
from django.core.validators import MinValueValidator
from django.db import models
from django.utils.translation import gettext_lazy as _

# Alliance Auth (External Libs)
from eve_sde.models import SolarSystem, ItemType

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

    @classmethod
    def ping_invoice(cls, inv):
        # ping the invoice to the user ( if we know them )
        message = f"{inv.note}\n\nPlease [CLICK HERE]({settings.SITE_URL}/invoice/r/) for instructions on how to pay your deposit!\n"
        inv.notify(message, title=app_settings.GEORGEFORGE_APP_NAME)

    @classmethod
    def generate_invoice(cls, cid, oid, price, due_date):
        msg = f"Deposit invoice for Order #{oid}"
        ref = f"GF-DEP-{str(oid)}"
        return Invoice.objects.create(
            character_id=cid,
            amount=round(price, -3),
            invoice_ref=ref,
            note=msg,
            due_date=due_date,
        )

    @classmethod
    def cancel_invoice(cls, oid):
        ref = f"GF-DEP-{str(oid)}"
        try:
            i = Invoice.objects.get(invoice_ref=ref)
        except Invoice.DoesNotExist:
            return True
        else:
            i.delete()
        return True
