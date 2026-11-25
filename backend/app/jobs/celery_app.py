"""Celery delivery for analysis jobs; PostgreSQL owns their state."""

from celery import Celery

from app.core.config import Settings

celery_app = Celery("analysis", include=["app.jobs.analysis_worker"])


def configure_celery(app: Celery, config: Settings) -> Celery:
    app.conf.update(
        broker_url=config.redis_url.get_secret_value(),
        task_default_queue="analysis",
        task_ignore_result=True,
        task_acks_late=True,
        worker_prefetch_multiplier=1,
        broker_connection_timeout=config.analysis_publish_timeout_seconds,
        broker_transport_options={
            "socket_connect_timeout": config.analysis_publish_timeout_seconds,
            "socket_timeout": config.analysis_publish_timeout_seconds,
        },
        task_time_limit=config.analysis_task_time_limit_seconds,
        task_serializer="json",
        accept_content=["json"],
    )
    return app
