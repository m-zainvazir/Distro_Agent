from celery import Celery

from app.core.config import settings

celery_app = Celery(
    "distroagent",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["app.tasks.discovery"],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    task_track_started=True,
    result_expires=3600,        # results kept in Redis for 1 hour
    worker_pool="solo",         # Windows: prefork/billiard semaphores are broken
)
