"""
tasks.py  —  Celery tasks for OTP delivery and monitoring.

Tasks
-----
send_otp_sms        Sends OTP via Kavenegar verify_lookup (async, retryable)
log_active_otp_count  Beat task: logs how many OTP keys are live in Redis
"""

import logging
from django.conf import settings
from django.core.cache import cache
from kavenegar import KavenegarAPI, APIException, HTTPException

from celery import shared_task

logger = logging.getLogger(__name__)

OTP_KEY_PREFIX = "otp:"  # matches the prefix used in views.py


# ──────────────────────────────────────────────────────────────
#  Task 1 — Send OTP SMS via Kavenegar
# ──────────────────────────────────────────────────────────────

@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=10,   # seconds between retries
    acks_late=True,           # message stays in queue until task succeeds
    name="otp_auth.tasks.send_otp_sms",
)
def send_otp_sms(self, phone: str, otp: str) -> dict:
    """
    Send an OTP code to `phone` using Kavenegar's verify_lookup endpoint.

    Parameters
    ----------
    phone : str   E.164-like Iranian mobile number, e.g. '09123456789'
    otp   : str   The generated OTP code, e.g. '481920'

    Returns
    -------
    dict  Kavenegar response payload on success.

    Retries
    -------
    Retries up to 3 times (10-second back-off) on APIException / HTTPException.
    """
    try:
        api = KavenegarAPI(
            settings.KAVENEGAR_API_KEY,
            timeout=settings.KAVENEGAR_TIMEOUT,
        )
        params = {
            "receptor": phone,
            "template": settings.KAVENEGAR_OTP_TEMPLATE,  # template name in Kavenegar panel
            "token": otp,
            "type": "sms",
        }
        response = api.verify_lookup(params)
        logger.info("OTP sent to %s | Kavenegar response: %s", phone, response)
        return response

    except APIException as exc:
        logger.error("Kavenegar APIException for %s: %s", phone, exc)
        raise self.retry(exc=exc)

    except HTTPException as exc:
        logger.error("Kavenegar HTTPException for %s: %s", phone, exc)
        raise self.retry(exc=exc)


# ──────────────────────────────────────────────────────────────
#  Task 2 — Beat: monitor how many OTP keys are alive in Redis
# ──────────────────────────────────────────────────────────────

@shared_task(name="otp_auth.tasks.log_active_otp_count")
def log_active_otp_count() -> int:
    """
    Celery Beat task — runs every 5 minutes (configured in celery.py).

    Counts live OTP keys in Redis and logs the result.
    Replace the logger call with a metrics push (Prometheus, Datadog, etc.)
    if you need dashboards or alerts.
    """
    from django_redis import get_redis_connection  # pip install django-redis

    redis_client = get_redis_connection("default")
    pattern = f"{OTP_KEY_PREFIX}*"

    # SCAN is non-blocking; safe for production Redis
    count = sum(1 for _ in redis_client.scan_iter(pattern))
    logger.info("[Beat] Active OTP keys in Redis: %d", count)
    return count
