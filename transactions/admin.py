from django.contrib import admin
from .models import Transaction


@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = ("id", "order", "gateway", "amount", "status", "authority", "ref_id", "created_at", "verified_at")
    list_filter = ("status", "gateway")
    search_fields = ("authority", "ref_id", "order__id")
    readonly_fields = ("order", "gateway", "amount", "authority", "ref_id", "card_pan", "created_at", "verified_at")
    ordering = ("-created_at",)

    def has_add_permission(self, request):
        # Transactions are only ever created by the payment flow itself.
        return False