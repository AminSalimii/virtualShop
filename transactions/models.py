from django.db import models
from orders.models import Order




class Transaction(models.Model):
    PENDING, SUCCESS, FAILED = "pending", "success", "failed"
    STATUS_CHOICES = [(PENDING, "در انتظار"), (SUCCESS, "موفق"), (FAILED, "ناموفق")]

    order       = models.ForeignKey(Order, on_delete=models.PROTECT, related_name="transactions")
    gateway     = models.CharField(max_length=20, default="zarinpal")
    amount      = models.DecimalField(max_digits=12, decimal_places=0)  # Toman, must match order.total_amount

    authority   = models.CharField(max_length=64, unique=True, null=True, blank=True)
    ref_id      = models.CharField(max_length=64, null=True, blank=True)
    card_pan    = models.CharField(max_length=32, null=True, blank=True)

    status      = models.CharField(max_length=10, choices=STATUS_CHOICES, default=PENDING)
    created_at  = models.DateTimeField(auto_now_add=True)
    verified_at = models.DateTimeField(null=True, blank=True)
