from celery import Celery
from core.config import Config

celery = Celery(
    "pioui",
    broker=Config.CELERY_BROKER_URL,
    backend=Config.CELERY_RESULT_BACKEND,
)

celery.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    task_track_started=True,
    result_expires=Config.CELERY_RESULT_EXPIRES,
    worker_prefetch_multiplier=1,     # fair scheduling
    task_acks_late=True,              # redeliver on crash
    worker_cancel_long_running_tasks_on_connection_loss=True,
    task_time_limit=Config.CELERY_TASK_TIME_LIMIT,
    task_soft_time_limit=Config.CELERY_TASK_SOFT_TIME_LIMIT,
    include=["tasks"],                # <-- ensure tasks module is loaded
)
