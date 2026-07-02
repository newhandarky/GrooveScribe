from app.core.config import Settings
from app.queue import CeleryJobQueue
from app.services.job_queue import NoopJobQueue, build_job_queue
from app.services.local_job_queue import LocalJobQueue
from app.services.pipeline_service import PipelineServiceRunner


def test_build_job_queue_defaults_to_local() -> None:
    queue = build_job_queue(Settings(job_queue_backend="local"))

    assert isinstance(queue, LocalJobQueue)
    assert isinstance(queue.runner_factory(), PipelineServiceRunner)


def test_build_job_queue_can_select_celery() -> None:
    queue = build_job_queue(Settings(job_queue_backend="celery"))

    assert isinstance(queue, CeleryJobQueue)


def test_build_job_queue_can_select_noop() -> None:
    queue = build_job_queue(Settings(job_queue_backend="noop"))

    assert isinstance(queue, NoopJobQueue)


def test_build_job_queue_rejects_invalid_backend() -> None:
    try:
        build_job_queue(Settings(job_queue_backend="redis"))
    except ValueError as exc:
        assert "unsupported job queue backend" in str(exc)
    else:
        raise AssertionError("expected invalid queue backend to fail")
