# Django
from django import forms
from django.utils.translation import gettext_lazy as _


class BulkImportStoreItemsForm(forms.Form):
    """ """

    MODE_CLEAR_AND_INSERT = "clear_and_insert"
    MODE_ADDITIVE = "additive"

    IMPORT_MODE_CHOICES = [
        (
            MODE_CLEAR_AND_INSERT,
            _(
                "Clear and Insert: removes all current items from the shop "
                "before importing, so the shop exactly matches the CSV."
            ),
        ),
        (
            MODE_ADDITIVE,
            _(
                "Additive: only adds or updates the items in the CSV. "
                "Existing items not mentioned in the CSV are left unchanged."
            ),
        ),
    ]

    import_mode = forms.ChoiceField(
        label=_("Import Mode"),
        choices=IMPORT_MODE_CHOICES,
        initial=MODE_CLEAR_AND_INSERT,
        widget=forms.RadioSelect,
    )

    data = forms.CharField(
        label=_("CSV Paste"),
        empty_value=_("Item Name,Description,Price,Deposit"),
        widget=forms.Textarea(
            attrs={
                "rows": "15",
                "placeholder": _("Item Name,Description,Price,Deposit"),
            }
        ),
    )
