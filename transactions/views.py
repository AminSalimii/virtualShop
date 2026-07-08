from rest_framework.views import APIView
from orders.models import Order
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from django.shortcuts import get_object_or_404, redirect
from django.conf import settings
from django.utils import timezone
import logging
import requests
from .models import Transaction
from .tasks import process_successful_order

logger = logging.getLogger(__name__)





class PaymentRequestView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, order_id):
        order = get_object_or_404(Order, id=order_id, user=request.user, status=Order.AWAITING_PAYMENT)

        payload = {
            "merchant_id":  settings.ZARINPAL_MERCHANT_ID,
            "amount":       int(order.total_amount),
            "currency":     "IRT",   
            "callback_url": settings.ZARINPAL_CALLBACK_URL,
            "description":  f"Order #{order.id}",
            "metadata":     {"mobile": str(request.user.phone_number)},
        }
        try:
            resp = requests.post(
                "https://payment.zarinpal.com/pg/v4/payment/request.json",
                json=payload, timeout=15,
            ).json()
        except (requests.RequestException, ValueError) as exc:
            logger.error("ZarinPal request.json call failed for order %s: %s", order.id, exc)
            return Response({"detail": "خطا در اتصال به درگاه پرداخت."}, status=502)

        data = resp.get("data") or {}
        if data.get("code") != 100:
            logger.error(
                "ZarinPal payment request rejected for order %s: %s",
                order.id, resp.get("errors") or data,
            )
            return Response({"detail": "خطا در اتصال به درگاه پرداخت."}, status=400)

        authority = data["authority"]
        Transaction.objects.create(order=order, amount=order.total_amount, authority=authority)

        return Response({"payment_url": f"https://www.zarinpal.com/pg/StartPay/{authority}"})


class PaymentCallbackView(APIView):
    permission_classes = [AllowAny]  

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
        try:
            resp = requests.post(
                "https://payment.zarinpal.com/pg/v4/payment/verify.json",
                json={
                    "merchant_id": settings.ZARINPAL_MERCHANT_ID,
                    "amount":      int(txn.amount),
                    "authority":   authority,
                }, timeout=15,
            ).json()
        except (requests.RequestException, ValueError) as exc:
            logger.error("ZarinPal verify.json call failed for transaction %s: %s", txn.id, exc)
            return redirect(settings.FRONTEND_PAYMENT_FAILED_URL)

        data = resp.get("data") or {}
        code = data.get("code")
        if code in (100, 101):
            txn.status, txn.ref_id, txn.card_pan, txn.verified_at = (
                Transaction.SUCCESS, data.get("ref_id"), data.get("card_pan"), timezone.now()
            )
            txn.save()
            txn.order.status, txn.order.paid_at = Order.PAID, timezone.now()
            txn.order.save(update_fields=["status", "paid_at"])
            process_successful_order.delay(txn.order.id)
            return redirect(settings.FRONTEND_PAYMENT_SUCCESS_URL)

        logger.error("ZarinPal verify failed for transaction %s: %s", txn.id, resp.get("errors") or data)
        txn.status = Transaction.FAILED
        txn.save(update_fields=["status"])
        return redirect(settings.FRONTEND_PAYMENT_FAILED_URL)