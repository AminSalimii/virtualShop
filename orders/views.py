"""
Views for the Cart / Order app (Django REST Framework).

Endpoints (wire these up in urls.py):

    GET    /cart/                          -> CartView
    DELETE /cart/                          -> CartView (clear cart)
    POST   /cart/items/                    -> CartItemView (add item)
    PATCH  /cart/items/<pk>/               -> CartItemDetailView (change qty)
    DELETE /cart/items/<pk>/               -> CartItemDetailView (remove)

    GET    /orders/                        -> OrderListCreateView (list mine)
    POST   /orders/                        -> OrderListCreateView (checkout)
    GET    /orders/<pk>/                   -> OrderDetailView
    POST   /orders/<pk>/cancel/            -> OrderCancelView

    PATCH  /orders/<pk>/status/            -> OrderStatusUpdateView   (staff)
    PATCH  /order-items/<pk>/status/       -> OrderItemStatusUpdateView (staff)
    GET    /order-items/<pk>/download/     -> OrderItemDownloadView
                                               (name this URL "order-item-download")

Note: OrderItemDownloadView assumes OrderItem has a `download_count` field
(see note in serializers.py) so Item.max_downloads can be enforced.
"""

from django.db import transaction
from django.db.models import Prefetch
from django.http import Http404, FileResponse
from django.shortcuts import get_object_or_404

from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from catalog.models import Item
from .models import Cart, CartItem, Order, OrderItem
from .serializers import (
    AddCartItemSerializer,
    CartSerializer,
    OrderCreateSerializer,
    OrderDetailSerializer,
    OrderItemStatusUpdateSerializer,
    OrderListSerializer,
    OrderStatusUpdateSerializer,
    UpdateCartItemSerializer,
)


# ---------------------------------------------------------------------------
# Cart
# ---------------------------------------------------------------------------

class CartView(APIView):
    """Retrieve or clear the logged-in user's cart (auto-created on first use)."""

    permission_classes = [permissions.IsAuthenticated]

    def get_object(self, user):
        cart, _ = Cart.objects.get_or_create(user=user)
        return cart

    def get(self, request):
        cart = self.get_object(request.user)
        return Response(CartSerializer(cart).data)

    def delete(self, request):
        cart = self.get_object(request.user)
        cart.items.all().delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class CartItemView(APIView):
    """Add an item to the cart (bumps quantity if it's already there)."""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        cart, _ = Cart.objects.get_or_create(user=request.user)
        serializer = AddCartItemSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        item = serializer.validated_data["item"]
        quantity = serializer.validated_data["quantity"]

        cart_item, created = CartItem.objects.get_or_create(
            cart=cart, item=item, defaults={"quantity": quantity}
        )
        if not created:
            cart_item.quantity += quantity
            cart_item.save(update_fields=["quantity"])

        return Response(CartSerializer(cart).data, status=status.HTTP_201_CREATED)


class CartItemDetailView(APIView):
    """Update the quantity of, or remove, a single cart line."""

    permission_classes = [permissions.IsAuthenticated]

    def get_cart_item(self, request, pk):
        return get_object_or_404(
            CartItem.objects.select_related("item"), pk=pk, cart__user=request.user
        )

    def patch(self, request, pk):
        cart_item = self.get_cart_item(request, pk)
        serializer = UpdateCartItemSerializer(data=request.data, context={"cart_item": cart_item})
        serializer.is_valid(raise_exception=True)
        cart_item.quantity = serializer.validated_data["quantity"]
        cart_item.save(update_fields=["quantity"])
        return Response(CartSerializer(cart_item.cart).data)

    def delete(self, request, pk):
        cart_item = self.get_cart_item(request, pk)
        cart = cart_item.cart
        cart_item.delete()
        return Response(CartSerializer(cart).data, status=status.HTTP_200_OK)


# ---------------------------------------------------------------------------
# Orders (customer-facing)
# ---------------------------------------------------------------------------

class OrderListCreateView(generics.ListCreateAPIView):
    """List the current user's orders, or check out their cart into a new one."""

    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return Order.objects.filter(user=self.request.user).order_by("-created_at")

    def get_serializer_class(self):
        return OrderCreateSerializer if self.request.method == "POST" else OrderListSerializer


class OrderDetailView(generics.RetrieveAPIView):
    """Retrieve a single order (owner or staff)."""

    permission_classes = [permissions.IsAuthenticated]
    serializer_class = OrderDetailSerializer

    def get_queryset(self):
        qs = Order.objects.select_related("shipping_address").prefetch_related(
            Prefetch("items", queryset=OrderItem.objects.select_related("item", "order"))
        )
        if self.request.user.is_staff:
            return qs
        return qs.filter(user=self.request.user)


class OrderCancelView(APIView):
    """Let a customer cancel an order before it's paid/processed."""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        order = get_object_or_404(Order, pk=pk, user=request.user)
        if order.status not in (Order.PENDING, Order.AWAITING_PAYMENT):
            return Response(
                {"detail": f"Orders in '{order.status}' status cannot be cancelled."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        with transaction.atomic():
            physical_items = order.items.filter(item_type=Item.PHYSICAL).select_related("item")
            locked_ids = [oi.item_id for oi in physical_items]
            locked = {i.id: i for i in Item.objects.select_for_update().filter(id__in=locked_ids)}
            updates = []
            for oi in physical_items:
                item = locked[oi.item_id]
                item.stock_quantity = (item.stock_quantity or 0) + oi.quantity
                updates.append(item)
            if updates:
                Item.objects.bulk_update(updates, ["stock_quantity"])

            order.status = Order.CANCELLED
            order.save(update_fields=["status"])
        return Response(OrderDetailSerializer(order, context={"request": request}).data)


class OrderItemDownloadView(APIView):
    """Serve a digital item's protected file, enforcing order ownership,
    payment status, and Item.max_downloads.

    Assumes OrderItem has a `download_count` field (see serializers.py note).
    Name this URL pattern "order-item-download" so OrderItemSerializer can
    build links to it.
    """

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, pk):
        order_item = get_object_or_404(
            OrderItem.objects.select_related("order", "item"), pk=pk
        )
        if order_item.order.user_id != request.user.id and not request.user.is_staff:
            raise Http404

        if order_item.item_type != Item.DIGITAL or not order_item.item.digital_file:
            return Response(
                {"detail": "No digital file for this item."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if order_item.order.status not in (
            Order.PAID, Order.PROCESSING, Order.SHIPPED, Order.DELIVERED
        ):
            return Response({"detail": "Order is not paid yet."}, status=status.HTTP_403_FORBIDDEN)

        max_downloads = order_item.item.max_downloads
        if max_downloads is not None and order_item.download_count >= max_downloads:
            return Response({"detail": "Download limit reached."}, status=status.HTTP_403_FORBIDDEN)

        order_item.download_count += 1
        order_item.save(update_fields=["download_count"])

        f = order_item.item.digital_file
        return FileResponse(f.open("rb"), as_attachment=True, filename=f.name.split("/")[-1])


# ---------------------------------------------------------------------------
# Staff / fulfillment
# ---------------------------------------------------------------------------

class OrderStatusUpdateView(generics.UpdateAPIView):
    """Staff endpoint to move an order through its lifecycle."""

    permission_classes = [permissions.IsAdminUser]
    queryset = Order.objects.all()
    serializer_class = OrderStatusUpdateSerializer
    http_method_names = ["patch"]


class OrderItemStatusUpdateView(generics.UpdateAPIView):
    """Staff endpoint to update the fulfillment status of a single order line."""

    permission_classes = [permissions.IsAdminUser]
    queryset = OrderItem.objects.all()
    serializer_class = OrderItemStatusUpdateSerializer
    http_method_names = ["patch"]