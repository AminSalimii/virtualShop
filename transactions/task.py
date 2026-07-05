"""
transactions/tasks.py

Tasks
-----
send_sms_notification       Sends a plain-text SMS via Kavenegar (NOT for OTPs)
process_successful_order    Post-payment fulfillment: digital unlock + physical flag + SMS receipt
send_otp_sms                Sends OTP code via Kavenegar verify_lookup template (from otp_auth)

Note: send_otp_sms lives in otp_auth/tasks.py and is imported here for clarity.
      This file defines its own send_sms_notification for non-OTP messages
      (receipts, shipping updates) because those use a different Kavenegar template.
"""

import logging
from celery import shared_task
from django.conf import settings
from django.utils import timezone
from kavenegar import KavenegarAPI, APIException, HTTPException
from virtualShop.catalog.task import generate_digital_delivery  

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────
#  Task 1 — Plain SMS (receipts, shipping updates)
# ─────────────────────────────────────────────────────────

@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=10,
    acks_late=True,
    name="transactions.tasks.send_sms_notification",
)
def send_sms_notification(self, phone: str, message: str) -> dict:
    """
    Sends a free-form SMS via Kavenegar's simple send endpoint.
    Used for order receipts, shipping notifications — NOT for OTPs.

    Uses a separate Kavenegar template/sender from otp_auth.tasks.send_otp_sms
    so the two flows never share or conflict with each other.

    Parameters
    ----------
    phone   : str  Recipient phone number e.g. '+989123456789'
    message : str  Message body

    Returns
    -------
    dict  Kavenegar response payload
    """
    try:
        api = KavenegarAPI(settings.KAVENEGAR_API_KEY, timeout=settings.KAVENEGAR_TIMEOUT)
        params = {
            "receptor": phone,
            "message":  message,
            "sender":   settings.KAVENEGAR_SMS_SENDER,   # set in settings, e.g. '10008663'
        }
        response = api.sms_send(params)
        logger.info("SMS sent to %s | Response: %s", phone, response)
        return response

    except APIException as exc:
        logger.error("Kavenegar APIException sending SMS to %s: %s", phone, exc)
        raise self.retry(exc=exc)

    except HTTPException as exc:
        logger.error("Kavenegar HTTPException sending SMS to %s: %s", phone, exc)
        raise self.retry(exc=exc)


# ─────────────────────────────────────────────────────────
#  Task 2 — Post-payment fulfillment
# ─────────────────────────────────────────────────────────

@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=10,
    acks_late=True,
    name="transactions.tasks.process_successful_order",
)
def process_successful_order(self, order_id: int) -> dict:
    """
    Triggered immediately after ZarinPal verify returns code 100 or 101.

    For each OrderItem:
      - DIGITAL → generate_digital_delivery.delay() unlocks the download
      - PHYSICAL → status set to 'ready_to_ship' for the admin to action

    Sends an SMS receipt to the user's phone via send_sms_notification.

    Parameters
    ----------
    order_id : int  PK of the Order to fulfil

    Returns
    -------
    dict  Summary: counts of digital/physical items processed
    """
    # Local imports — avoids circular: transactions → orders → transactions
    from orders.models import Order, OrderItem
    from catalog.models import Item

    try:
        order = Order.objects.select_related("user").prefetch_related(
            "items__item"
        ).get(id=order_id)

        if order.status != Order.PAID:
            logger.warning(
                "process_successful_order called on Order %s with status '%s' — expected PAID.",
                order_id, order.status,
            )
            return {"order_id": order_id, "status": "skipped", "reason": "order not PAID"}

        digital_count  = 0
        physical_count = 0

        for order_item in order.items.all():

            if order_item.item_type == Item.DIGITAL:
                # Async — worker unlocks download + stamps delivered_at
                generate_digital_delivery.delay(order_item.id)
                digital_count += 1

            elif order_item.item_type == Item.PHYSICAL:
                # Mark ready for admin to ship
                order_item.status = OrderItem.READY_TO_SHIP
                order_item.save(update_fields=["status"])
                physical_count += 1

        # Send SMS receipt (uses plain send, not OTP template)
        phone   = str(order.user.phone_number)
        message = (
            f"سفارش شما به شماره {order.id} با موفقیت پرداخت شد.\n"
            f"مبلغ: {order.total_amount:,} تومان\n"
            f"با تشکر از خرید شما."
        )
        send_sms_notification.delay(phone, message)

        logger.info(
            "Order %s fulfilled — digital: %d, physical: %d.",
            order_id, digital_count, physical_count,
        )
        return {
            "order_id":      order_id,
            "digital_count":  digital_count,
            "physical_count": physical_count,
        }

    except Exception as exc:
        logger.error("process_successful_order failed for Order %s: %s", order_id, exc)
        raise self.retry(exc=exc)