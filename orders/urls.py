"""
URLs for the Cart / Order app.

Include this in your project's root urls.py, e.g.:

    path("api/", include("orders.urls")),

Note: the "order-item-download" name is relied on directly by
OrderItemSerializer.get_download_url() (via reverse()) — don't rename it
without updating serializers.py too.
"""

from django.urls import path

from .views import (
    CartItemDetailView,
    CartItemView,
    CartView,
    OrderCancelView,
    OrderDetailView,
    OrderItemDownloadView,
    OrderItemStatusUpdateView,
    OrderListCreateView,
    OrderStatusUpdateView,
)

urlpatterns = [
    # Cart
    path("cart/", CartView.as_view(), name="cart-detail"),
    path("cart/items/", CartItemView.as_view(), name="cart-item-list"),
    path("cart/items/<int:pk>/", CartItemDetailView.as_view(), name="cart-item-detail"),

    # Orders (customer-facing)
    path("", OrderListCreateView.as_view(), name="order-list"),
    path("<int:pk>/", OrderDetailView.as_view(), name="order-detail"),
    path("<int:pk>/cancel/", OrderCancelView.as_view(), name="order-cancel"),

    # Staff / fulfillment
    path("<int:pk>/status/", OrderStatusUpdateView.as_view(), name="order-status-update"),
    path(
        "order-items/<int:pk>/status/",
        OrderItemStatusUpdateView.as_view(),
        name="order-item-status-update",
    ),
    path(
        "order-items/<int:pk>/download/",
        OrderItemDownloadView.as_view(),
        name="order-item-download",
    ),
]