from datetime import UTC, datetime

from fastapi.testclient import TestClient

from app.api.routes.transcriptions import get_upload_service
from app.main import create_app
from app.models.enums import JobStatus
from app.services.upload_service import UploadResult


class FakeUploadService:
    def __init__(self) -> None:
        self.calls = []

    def create_upload_job(
        self,
        *,
        db,
        filename,
        content_type,
        content,
        title=None,
        pipeline_mode=None,
        adtof_threshold_preset=None,
        tom_filter_preset=None,
    ):
        self.calls.append(
            {
                "filename": filename,
                "content_type": content_type,
                "content": content,
                "title": title,
                "pipeline_mode": pipeline_mode,
                "adtof_threshold_preset": adtof_threshold_preset,
                "tom_filter_preset": tom_filter_preset,
            }
        )
        return UploadResult(
            job_id="job-123",
            status=JobStatus.QUEUED,
            created_at=datetime(2026, 6, 25, tzinfo=UTC),
        )


def test_upload_api_returns_202_with_job_links() -> None:
    app = create_app()
    fake_service = FakeUploadService()
    app.dependency_overrides[get_upload_service] = lambda: fake_service
    client = TestClient(app)

    response = client.post(
        "/api/v1/transcriptions",
        files={"file": ("demo.wav", b"fake-wav", "audio/wav")},
        data={"title": "Demo"},
    )

    assert response.status_code == 202
    body = response.json()
    assert body["job_id"] == "job-123"
    assert body["status"] == "queued"
    assert body["status_url"] == "/api/v1/transcriptions/job-123/status"
    assert body["result_url"] == "/api/v1/transcriptions/job-123"
    assert body["created_at"] in {"2026-06-25T00:00:00Z", "2026-06-25T00:00:00+00:00"}
    assert fake_service.calls == [
        {
            "filename": "demo.wav",
            "content_type": "audio/wav",
            "content": b"fake-wav",
            "title": "Demo",
            "pipeline_mode": None,
            "adtof_threshold_preset": None,
            "tom_filter_preset": None,
        }
    ]


def test_upload_api_accepts_true_ai_product_config() -> None:
    app = create_app()
    fake_service = FakeUploadService()
    app.dependency_overrides[get_upload_service] = lambda: fake_service
    client = TestClient(app)

    response = client.post(
        "/api/v1/transcriptions",
        files={"file": ("demo.wav", b"fake-wav", "audio/wav")},
        data={
            "pipeline_mode": "true_ai",
            "adtof_threshold_preset": "separated_v1",
            "tom_filter_preset": "tom_guard_v1",
        },
    )

    assert response.status_code == 202
    assert fake_service.calls[-1]["pipeline_mode"] == "true_ai"
    assert fake_service.calls[-1]["adtof_threshold_preset"] == "separated_v1"
    assert fake_service.calls[-1]["tom_filter_preset"] == "tom_guard_v1"
