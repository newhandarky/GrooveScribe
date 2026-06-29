from __future__ import annotations

from app.core.config import Settings
from app.core.errors import ApiErrorException, ErrorCode
from app.queue import TRANSCRIPTION_TASK_NAME, CeleryJobQueue


class FakeCelery:
    def __init__(self, *, should_fail: bool = False) -> None:
        self.should_fail = should_fail
        self.calls = []
        self.conf = {}

    def send_task(self, name, *, args=None, kwargs=None, queue=None):
        if self.should_fail:
            raise RuntimeError("redis unavailable")
        self.calls.append({"name": name, "args": args, "kwargs": kwargs, "queue": queue})


def test_celery_job_queue_sends_transcription_task_payload() -> None:
    celery = FakeCelery()
    queue = CeleryJobQueue(settings=Settings(celery_task_default_queue="groovescribe"), celery_app=celery)

    queue.enqueue_transcription("job-1", pipeline_config_id="config-1")

    assert celery.calls == [
        {
            "name": TRANSCRIPTION_TASK_NAME,
            "args": ["job-1"],
            "kwargs": {"pipeline_config_id": "config-1"},
            "queue": "groovescribe",
        }
    ]


def test_celery_job_queue_maps_enqueue_failure() -> None:
    queue = CeleryJobQueue(settings=Settings(), celery_app=FakeCelery(should_fail=True))

    try:
        queue.enqueue_transcription("job-1")
    except ApiErrorException as exc:
        assert exc.code == ErrorCode.QUEUE_ENQUEUE_FAILED
    else:
        raise AssertionError("expected QUEUE_ENQUEUE_FAILED")
