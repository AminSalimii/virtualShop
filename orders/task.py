from celery import shared_task
from django.utils import timezone
from orders.models import OrderItem

@shared_task
def generate_digital_delivery(order_item_id):
    """
    Called by process_successful_order after a PAID order is confirmed.
    Marks the OrderItem as ready and records when delivery was made.
    The actual download is handled by DigitalDownloadView — this task
    just flips the state so the view knows the item is unlocked.
    """
    order_item = OrderItem.objects.select_related("item", "order__user").get(id=order_item_id)

    order_item.is_delivered = True
    order_item.delivered_at = timezone.now()
    order_item.save(update_fields=["is_delivered", "delivered_at"])