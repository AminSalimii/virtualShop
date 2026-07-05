from rest_framework.views import APIView
from orders.models import Order
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from django.shortcuts import get_object_or_404, redirect
from django.conf import settings
from django.utils import timezone
import requests
from .models import Transaction
from .tasks import process_successful_order





class PaymentRequestView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, order_id):
        order = get_object_or_404(Order, id=order_id, user=request.user, status=Order.AWAITING_PAYMENT)

        payload = {
            "merchant_id":  settings.ZARINPAL_MERCHANT_ID,
            "amount":       int(order.total_amount),
            "currency":     "IRT",   # be explicit — IRT=Toman, IRR=Rial, never rely on a default
            "callback_url": settings.ZARINPAL_CALLBACK_URL,
            "description":  f"Order #{order.id}",
            "metadata":     {"mobile": str(request.user.phone_number)},
        }
        resp = requests.post(
            "https://payment.zarinpal.com/pg/v4/payment/request.json",
            json=payload, timeout=15,
        ).json()

        if resp["data"]["code"] != 100:
            return Response({"detail": "خطا در اتصال به درگاه پرداخت."}, status=400)

        authority = resp["data"]["authority"]
        Transaction.objects.create(order=order, amount=order.total_amount, authority=authority)

        return Response({"payment_url": f"https://www.zarinpal.com/pg/StartPay/{authority}"})


class PaymentCallbackView(APIView):
    permission_classes = [AllowAny]  # ZarinPal hits this server-to-server, not your logged-in session

    def get(self, request):
        authority = request.query_params.get("Authority")
        txn = get_object_or_404(Transaction, authority=authority)

        if request.query_params.get("Status") != "OK":
            txn.status = Transaction.FAILED
            txn.save(update_fields=["status"])
            txn.order.status = Order.FAILED
            txn.order.save(update_fields=["status"])
            return redirect(settings.FRONTEND_PAYMENT_FAILED_URL)

        if txn.status == Transaction.SUCCESS:
            return redirect(settings.FRONTEND_PAYMENT_SUCCESS_URL)  # already processed, don't repeat it

        # Always verify with YOUR stored amount, never anything from the URL/client
        resp = requests.post(
            "https://payment.zarinpal.com/pg/v4/payment/verify.json",
            json={
                "merchant_id": settings.ZARINPAL_MERCHANT_ID,
                "amount":      int(txn.amount),
                "authority":   authority,
            }, timeout=15,
        ).json()

        code = resp["data"].get("code")
        if code in (100, 101):
            txn.status, txn.ref_id, txn.card_pan, txn.verified_at = (
                Transaction.SUCCESS, resp["data"].get("ref_id"), resp["data"].get("card_pan"), timezone.now()
            )
            txn.save()
            txn.order.status, txn.order.paid_at = Order.PAID, timezone.now()
            txn.order.save(update_fields=["status", "paid_at"])
            process_successful_order.delay(txn.order.id)
            return redirect(settings.FRONTEND_PAYMENT_SUCCESS_URL)

        txn.status = Transaction.FAILED
        txn.save(update_fields=["status"])
        return redirect(settings.FRONTEND_PAYMENT_FAILED_URL)
