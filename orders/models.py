from django.db import models
from user.models import User
from catalog.models import Item




class Cart(models.Model):
    user       = models.OneToOneField(User, on_delete=models.CASCADE, related_name="cart")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class CartItem(models.Model):
    cart     = models.ForeignKey(Cart, on_delete=models.CASCADE, related_name="items")
    item     = models.ForeignKey(Item, on_delete=models.CASCADE)
    quantity = models.PositiveIntegerField(default=1)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["cart", "item"], name="unique_cart_item"),
        ]
 

class Order(models.Model):
    PENDING, AWAITING_PAYMENT, PAID, PROCESSING, SHIPPED, DELIVERED, CANCELLED, FAILED = (
        "pending", "awaiting_payment", "paid", "processing", "shipped", "delivered", "cancelled", "failed"
    )
    STATUS_CHOICES = [(s, s) for s in (
        PENDING, AWAITING_PAYMENT, PAID, PROCESSING, SHIPPED, DELIVERED, CANCELLED, FAILED
    )]

    user             = models.ForeignKey(User, on_delete=models.PROTECT, related_name="orders")
    status           = models.CharField(max_length=20, choices=STATUS_CHOICES, default=PENDING)
    shipping_address = models.ForeignKey("user.Address", null=True, blank=True, on_delete=models.SET_NULL)
    total_amount     = models.DecimalField(max_digits=12, decimal_places=0)
    created_at       = models.DateTimeField(auto_now_add=True)
    paid_at          = models.DateTimeField(null=True, blank=True)





class OrderItem(models.Model):
    PENDING, PROCESSING, SHIPPED, DELIVERED, CANCELLED = (
        "pending", "processing", "shipped", "delivered", "cancelled"
    )
    STATUS_CHOICES = [(s, s) for s in (PENDING, PROCESSING, SHIPPED, DELIVERED, CANCELLED)]

    
    order      = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="items")
    item       = models.ForeignKey(Item, on_delete=models.PROTECT)
    item_title = models.CharField(max_length=255)  
    item_type  = models.CharField(max_length=10)  
    quantity   = models.PositiveIntegerField()
    unit_price = models.DecimalField(max_digits=12, decimal_places=0) 
    status     = models.CharField(max_length=20, choices=STATUS_CHOICES, default=PENDING)
    is_delivered = models.BooleanField(default=False)
    delivered_at = models.DateTimeField(null=True, blank=True)
    download_count = models.PositiveIntegerField(default=0)