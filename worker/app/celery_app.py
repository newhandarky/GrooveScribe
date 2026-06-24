from celery import Celery

celery_app = Celery(
    "groovescribe_worker",
    broker="redis://localhost:6379/0",
)
