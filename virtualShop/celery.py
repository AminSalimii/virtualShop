"""
celery.py  —  place this next to your project's settings.py (same folder as manage.py)
 
Broker  : RabbitMQ  (reliable task delivery)
Backend : Redis     (task result storage + OTP cache)
"""
 
import os
from celery import Celery
from celery.schedules import crontab
 
os.environ.setdefault("DJANGO_SETTINGS_MODULE", 'virtualShop.settings')  # ← change 'config' to your project name
 
app = Celery("config")  # ← change 'config' to your project name
 
# Pull CELERY_* keys from Django settings
app.config_from_object("django.conf:settings", namespace="CELERY")
 
# Auto-discover tasks.py in every INSTALLED_APP
app.autodiscover_tasks()
 
 
# ──────────────────────────────────────────────
#  Celery Beat periodic tasks
# ──────────────────────────────────────────────
app.conf.beat_schedule = {
    # Logs a summary of active OTP keys every 5 minutes.
    # Redis TTL handles actual expiry automatically — this is for
    # observability/alerting; replace with your own monitoring logic.
    "log-active-otp-count": {
        "task": "otp_auth.tasks.log_active_otp_count",
        "schedule": crontab(minute="*/5"),
    },
}
