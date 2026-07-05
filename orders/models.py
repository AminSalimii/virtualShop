from django.db import models
from user.models import User, Address
from catalog.models import Item




class Cart(models.Model):
    user       = models.OneToOneField(User, on_delete=models.CASCADE, related_name="cart")
    updated_at = models.DateTimeField(auto_now=True)




class Order(models.Model):
    PENDING, AWAITING_PAYMENT, PAID, PROCESSING, SHIPPED, DELIVERED, CANCELLED, FAILED = (
        "pending", "awaiting_payment", "paid", "processing", "shipped", "delivered", "cancelled", "failed"
    )
    STATUS_CHOICES = [(s, s) for s in (
        PENDING, AWAITING_PAYMENT, PAID, PROCESSING, SHIPPED, DELIVERED, CANCELLED, FAILED
    )]

    user             = models.ForeignKey(User, on_delete=models.PROTECT, related_name="orders")
    status           = models.CharField(max_length=20, choices=STATUS_CHOICES, default=PENDING)
    shipping_address = models.ForeignKey(Address, on_delete=models.PROTECT, related_name="orders")
    total_amount     = models.DecimalField(max_digits=12, decimal_places=0)
    created_at       = models.DateTimeField(auto_now_add=True)
    paid_at          = models.DateTimeField(null=True, blank=True)





class OrderItem(models.Model):
    READY_TO_SHIP, SHIPPED, DELIVERED = "ready_to_ship", "shipped", "delivered"
    STATUS_CHOICES = [(s, s) for s in (READY_TO_SHIP, SHIPPED, DELIVERED)]    
    
    order      = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="items")
    item       = models.ForeignKey(Item, on_delete=models.PROTECT)
    item_title = models.CharField(max_length=255)  # snapshot
    item_type  = models.CharField(max_length=10)  # snapshot
    quantity   = models.PositiveIntegerField()
    unit_price = models.DecimalField(max_digits=12, decimal_places=0) # snapshot
    status     = models.CharField(max_length=20, choices=STATUS_CHOICES, default=READY_TO_SHIP)
    is_delivered = models.BooleanField(default=False)
    delivered_at = models.DateTimeField(null=True, blank=True)