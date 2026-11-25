"""Configured Celery CLI entry point."""

from app.core.config import Settings
from app.jobs.celery_app import celery_app, configure_celery

configure_celery(celery_app, Settings())
