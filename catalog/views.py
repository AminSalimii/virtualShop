from django.shortcuts import render
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.shortcuts import get_object_or_404
from django.http import FileResponse
from .models import Item, OrderItem, Order

class DigitalDownloadView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, order_item_id):
        order_item = get_object_or_404(
            OrderItem, id=order_item_id, order__user=request.user, item_type=Item.DIGITAL
        )
        if order_item.order.status != Order.PAID:
            return Response({"detail": "این سفارش هنوز پرداخت نشده است."}, status=403)

        f = order_item.item.digital_file
        return FileResponse(f.open("rb"), as_attachment=True, filename=f.name.split("/")[-1])