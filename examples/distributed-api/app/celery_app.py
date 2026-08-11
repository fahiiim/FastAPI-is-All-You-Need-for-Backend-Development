from celery import Celery
from celery.schedules import crontab

from .config import get_settings

settings = get_settings()
celery = Celery("exports", broker=settings.redis_url, backend=settings.redis_url)
celery.conf.update(
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_serializer="json",
    accept_content=["json"],
    result_expires=3600,
    beat_schedule={
        "dispatch-outbox-frequently": {
            "task": "exports.dispatch_outbox",
            "schedule": 1.0,
        },
        "remove-old-results-daily": {
            "task": "celery.backend_cleanup",
            "schedule": crontab(hour=3, minute=0),
        },
    },
    imports=("app.tasks",),
)
