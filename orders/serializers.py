"""
Serializers for the Cart / Order app.

Assumptions / notes:
  - A `CartItem` through-model exists: cart (FK), item (FK), quantity,
    related_name="items" back to Cart.
  - `OrderItem` needs one more field to enforce `Item.max_downloads`:
        download_count = models.PositiveIntegerField(default=0)
    Add it to models.py -- the download view in views.py assumes it exists.
  - `user.models.Address` is serialized with `fields = "__all__"`.
  - "Effective price" = discount_price when set and lower than price,
    else price.
"""

from django.db import transaction
from django.urls import reverse, NoReverseMatch
from django.utils import timezone

from rest_framework import serializers

from user.models import Address
from catalog.models import Item
from .models import Cart, CartItem, Order, OrderItem


def get_effective_price(item):
    """Discount price wins if set and actually lower than the list price."""
    if item.discount_price is not None and item.discount_price < item.price:
        return item.discount_price
    return item.price


# ---------------------------------------------------------------------------
# Lightweight nested serializers for models owned by other apps
# ---------------------------------------------------------------------------

class ItemMiniSerializer(serializers.ModelSerializer):
    effective_price = serializers.SerializerMethodField()

    class Meta:
        model = Item
        fields = [
            "id", "title", "slug", "item_type",
            "price", "discount_price", "effective_price",
            "is_active", "stock_quantity",
        ]
        read_only_fields = fields

    def get_effective_price(self, obj):
        return get_effective_price(obj)


class AddressSerializer(serializers.ModelSerializer):
    class Meta:
        model = Address
        fields = "__all__"


# ---------------------------------------------------------------------------
# Cart
# ---------------------------------------------------------------------------

class CartItemSerializer(serializers.ModelSerializer):
    item = ItemMiniSerializer(read_only=True)
    subtotal = serializers.SerializerMethodField()

    class Meta:
        model = CartItem
        fields = ["id", "item", "quantity", "subtotal"]
        read_only_fields = fields

    def get_subtotal(self, obj):
        return obj.quantity * get_effective_price(obj.item)


class CartSerializer(serializers.ModelSerializer):
    items = CartItemSerializer(many=True, read_only=True)
    total = serializers.SerializerMethodField()

    class Meta:
        model = Cart
        fields = ["id", "user", "items", "total", "created_at", "updated_at"]
        read_only_fields = ["id", "user", "created_at", "updated_at"]

    def get_total(self, obj):
        return sum(ci.quantity * get_effective_price(ci.item) for ci in obj.items.all())


class AddCartItemSerializer(serializers.Serializer):
    """Adds an item to the current user's cart, or bumps its quantity."""

    item_id = serializers.PrimaryKeyRelatedField(
        queryset=Item.objects.filter(is_active=True), source="item"
    )
    quantity = serializers.IntegerField(min_value=1, default=1)

    def validate(self, attrs):
        item = attrs["item"]
        quantity = attrs["quantity"]

        if item.item_type == Item.PHYSICAL:
            already_in_cart = 0
            request = self.context.get("request")
            if request is not None:
                cart = getattr(request.user, "cart", None)
                if cart is not None:
                    existing = cart.items.filter(item=item).first()
                    already_in_cart = existing.quantity if existing else 0

            available = item.stock_quantity or 0
            if quantity + already_in_cart > available:
                raise serializers.ValidationError(
                    f"Only {available} unit(s) of '{item.title}' available."
                )

        return attrs


class UpdateCartItemSerializer(serializers.Serializer):
    """Changes the quantity of an existing cart line. Pass the CartItem via
    context={'cart_item': cart_item} so stock can be checked."""

    quantity = serializers.IntegerField(min_value=1)

    def validate_quantity(self, value):
        cart_item = self.context.get("cart_item")
        if cart_item and cart_item.item.item_type == Item.PHYSICAL:
            stock = cart_item.item.stock_quantity or 0
            if value > stock:
                raise serializers.ValidationError(
                    f"Only {stock} unit(s) of '{cart_item.item.title}' available."
                )
        return value


# ---------------------------------------------------------------------------
# Orders
# ---------------------------------------------------------------------------

class OrderItemSerializer(serializers.ModelSerializer):
    download_url = serializers.SerializerMethodField()

    class Meta:
        model = OrderItem
        fields = [
            "id", "item", "item_title", "item_type", "quantity",
            "unit_price", "status", "is_delivered", "delivered_at",
            "download_url",
        ]
        read_only_fields = fields

    def get_download_url(self, obj):
        if obj.item_type != Item.DIGITAL:
            return None
        if obj.order.status not in (Order.PAID,Order.SHIPPED, Order.DELIVERED):
            return None
        try:
            url = reverse("order-item-download", args=[obj.id])
        except NoReverseMatch:
            return None
        request = self.context.get("request")
        return request.build_absolute_uri(url) if request else url


class OrderListSerializer(serializers.ModelSerializer):
    class Meta:
        model = Order
        fields = ["id", "status", "total_amount", "created_at", "paid_at"]
        read_only_fields = fields


class OrderDetailSerializer(serializers.ModelSerializer):
    items = OrderItemSerializer(many=True, read_only=True)
    shipping_address = AddressSerializer(read_only=True)

    class Meta:
        model = Order
        fields = [
            "id", "status", "shipping_address", "total_amount",
            "items", "created_at", "paid_at",
        ]
        read_only_fields = fields


class OrderCreateSerializer(serializers.Serializer):
    """Checks out the current user's cart into an Order + OrderItems.

    Re-validates stock at checkout time (locking the relevant Item rows)
    since availability may have changed since items were added to the cart.
    """

    shipping_address_id = serializers.PrimaryKeyRelatedField(
        queryset=Address.objects.all()
    )

    def validate(self, attrs):
        request = self.context["request"]
        cart = getattr(request.user, "cart", None)
        if cart is None or not cart.items.exists():
            raise serializers.ValidationError("Your cart is empty.")
        attrs["cart"] = cart
        return attrs

    def create(self, validated_data):
        cart = validated_data["cart"]
        address = validated_data["shipping_address_id"]
        request = self.context["request"]

        with transaction.atomic():
            cart_items = list(cart.items.select_related("item"))
            item_ids = [ci.item_id for ci in cart_items]
            # Lock the Item rows so two concurrent checkouts can't oversell stock.
            locked_items = {
                i.id: i for i in Item.objects.select_for_update().filter(id__in=item_ids)
            }

            order_items = []
            total = 0
            physical_updates = []

            for ci in cart_items:
                item = locked_items[ci.item_id]

                if not item.is_active:
                    raise serializers.ValidationError(f"'{item.title}' is no longer available.")

                if item.item_type == Item.PHYSICAL:
                    stock = item.stock_quantity or 0
                    if stock < ci.quantity:
                        raise serializers.ValidationError(
                            f"Only {stock} unit(s) of '{item.title}' left in stock."
                        )
                    item.stock_quantity = stock - ci.quantity
                    physical_updates.append(item)

                unit_price = get_effective_price(item)
                total += unit_price * ci.quantity
                order_items.append(OrderItem(
                    item=item,
                    item_title=item.title,
                    item_type=item.item_type,
                    quantity=ci.quantity,
                    unit_price=unit_price,
                ))

            order = Order.objects.create(
                user=request.user,
                shipping_address=address,
                total_amount=total,
            )
            for oi in order_items:
                oi.order = order
            OrderItem.objects.bulk_create(order_items)

            if physical_updates:
                Item.objects.bulk_update(physical_updates, ["stock_quantity"])

            cart.items.all().delete()

        return order

    def to_representation(self, instance):
        return OrderDetailSerializer(instance, context=self.context).data


class OrderStatusUpdateSerializer(serializers.ModelSerializer):
    """Staff-only: move an order through its lifecycle."""

    class Meta:
        model = Order
        fields = ["status"]

    def validate_status(self, value):
        if self.instance and self.instance.status == Order.CANCELLED:
            raise serializers.ValidationError("Cancelled orders cannot be updated.")
        return value

    def update(self, instance, validated_data):
        new_status = validated_data["status"]
        instance.status = new_status
        if new_status == Order.PAID and instance.paid_at is None:
            instance.paid_at = timezone.now()
        instance.save()
        return instance


class OrderItemStatusUpdateSerializer(serializers.ModelSerializer):
    """Staff-only: update fulfillment status of a single (physical) order line."""

    class Meta:
        model = OrderItem
        fields = ["status", "is_delivered", "delivered_at"]

    def update(self, instance, validated_data):
        instance.status = validated_data.get("status", instance.status)
        if instance.status == OrderItem.DELIVERED:
            instance.is_delivered = True
            instance.delivered_at = instance.delivered_at or timezone.now()
        instance.save()
        return instance