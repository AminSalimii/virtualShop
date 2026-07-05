"""
catalog/tasks.py

Tasks
-----
generate_digital_delivery   Unlocks a digital OrderItem for download after payment
"""

import logging
from celery import shared_task
from django.utils import timezone

logger = logging.getLogger(__name__)


@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=5,
    acks_late=True,
    name="catalog.tasks.generate_digital_delivery",
)
def generate_digital_delivery(self, order_item_id: int) -> dict:
    """
    Called by transactions.tasks.process_successful_order after a successful payment.

    Marks the OrderItem as delivered so DigitalDownloadView unlocks the file.
    Uses a local import to avoid circular dependency with orders app.

    Parameters
    ----------
    order_item_id : int  PK of the OrderItem to unlock

    Returns
    -------
    dict  Summary of what was updated
    """
    try:
        # Local import — avoids circular: catalog → orders → catalog
        from orders.models import OrderItem

        order_item = OrderItem.objects.select_related(
            "item", "order__user"
        ).get(id=order_item_id)

        if order_item.is_delivered:
            logger.info(
                "OrderItem %s already delivered — skipping.", order_item_id
            )
            return {"order_item_id": order_item_id, "status": "already_delivered"}

        if not order_item.item.digital_file:
            logger.error(
                "OrderItem %s has no digital_file attached to Item %s.",
                order_item_id, order_item.item_id,
            )
            raise ValueError(f"Item {order_item.item_id} has no digital_file.")

        order_item.is_delivered = True
        order_item.delivered_at = timezone.now()
        order_item.status       = "delivered"
        order_item.save(update_fields=["is_delivered", "delivered_at", "status"])

        logger.info(
            "Digital delivery unlocked — OrderItem %s, user %s, item '%s'.",
            order_item_id,
            order_item.order.user_id,
            order_item.item_title,
        )
        return {
            "order_item_id": order_item_id,
            "status":        "delivered",
            "delivered_at":  str(order_item.delivered_at),
        }

    except Exception as exc:
        logger.error("generate_digital_delivery failed for OrderItem %s: %s", order_item_id, exc)
        raise self.retry(exc=exc)