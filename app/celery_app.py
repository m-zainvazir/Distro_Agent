import os
import sys

from celery import Celery

from app.core.config import settings

# LangSmith tracing for agents running inside Celery workers.
# The FastAPI lifespan sets these for web processes; workers need them here.
if settings.langsmith_api_key:
    os.environ.setdefault("LANGCHAIN_TRACING_V2", "true")
    os.environ.setdefault("LANGCHAIN_API_KEY", settings.langsmith_api_key)
    os.environ.setdefault("LANGCHAIN_PROJECT", settings.langsmith_project)

celery_app = Celery(
    "distroagent",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=[
        "app.tasks.discovery",
        "app.tasks.email_tasks",
        "app.tasks.reply_tasks",
        "app.tasks.calibration_task",
        "app.tasks.invoice_task",
        "app.tasks.metrics_task",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    task_track_started=True,
    result_expires=3600,        # results kept in Redis for 1 hour
    # Windows dev: billiard semaphores are broken, fall back to solo.
    # Production (Linux): use prefork for real concurrency.
    worker_pool="solo" if sys.platform == "win32" else "prefork",
    beat_schedule={
        "send-approved-emails": {
            "task": "email.send_approved",
            "schedule": 900.0,   # every 15 minutes
        },
        "check-replies": {
            "task": "replies.check_replies",
            "schedule": 3600.0,  # every hour
        },
        "calibrate-scoring-weights": {
            "task": "calibration.run_daily",
            "schedule": 86400.0,  # every 24 hours
        },
        "send-daily-kpi-digest": {
            "task": "metrics.send_daily_digest",
            "schedule": 86400.0,  # every 24 hours
        },
    },
)
