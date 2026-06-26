from fastapi.testclient import TestClient

from app.api.routes.transcriptions import (
    get_download_service,
    get_job_query_service,
    get_result_service,
    get_upload_service,
)
from app.core.config import Settings, get_settings
from app.core.errors import ApiErrorException, ErrorCode
from app.db.session import get_db_session
from app.main import create_app
from app.storage.errors import StorageWriteFailedError


def _override_db_session():
    yield object()


def _assert_error_shape(body: dict, code: str) -> None:
    assert set(body.keys()) == {"error"}
    assert set(body["error"].keys()) == {"code", "message", "retriable", "details"}
    assert body["error"]["code"] == code
    assert isinstance(body["error"]["message"], str)
    assert isinstance(body["error"]["retriable"], bool)
    assert isinstance(body["error"]["details"], dict)


def _client_with_overrides(overrides: dict | None = None) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_db_session] = _override_db_session
    for dependency, replacement in (overrides or {}).items():
        app.dependency_overrides[dependency] = replacement
    return TestClient(app)


def test_upload_invalid_file_type_uses_unified_error_shape() -> None:
    class FakeUploadService:
        def create_upload_job(self, **kwargs):
            raise ApiErrorException(ErrorCode.INVALID_FILE_TYPE)

    client = _client_with_overrides({get_upload_service: lambda: FakeUploadService()})

    response = client.post(
        "/api/v1/transcriptions",
        files={"file": ("demo.wav", b"fake-wav", "audio/wav")},
    )

    assert response.status_code == 400
    _assert_error_shape(response.json(), "INVALID_FILE_TYPE")


def test_upload_file_too_large_uses_unified_error_shape() -> None:
    settings = Settings(upload_max_size_bytes=1)
    client = _client_with_overrides({get_settings: lambda: settings})

    response = client.post(
        "/api/v1/transcriptions",
        files={"file": ("demo.wav", b"too-large", "audio/wav")},
    )

    assert response.status_code == 413
    _assert_error_shape(response.json(), "FILE_TOO_LARGE")


def test_upload_storage_write_error_uses_unified_error_shape() -> None:
    class FakeUploadService:
        def create_upload_job(self, **kwargs):
            raise StorageWriteFailedError("disk full at /tmp/internal")

    client = _client_with_overrides({get_upload_service: lambda: FakeUploadService()})

    response = client.post(
        "/api/v1/transcriptions",
        files={"file": ("demo.wav", b"fake-wav", "audio/wav")},
    )

    assert response.status_code == 500
    body = response.json()
    _assert_error_shape(body, "STORAGE_WRITE_FAILED")
    assert "/tmp/internal" not in body["error"]["message"]


def test_status_job_not_found_uses_unified_error_shape() -> None:
    class FakeJobQueryService:
        def get_job_or_raise(self, db, job_id):
            raise ApiErrorException(ErrorCode.JOB_NOT_FOUND, details={"job_id": job_id})

    client = _client_with_overrides({get_job_query_service: lambda: FakeJobQueryService()})

    response = client.get("/api/v1/transcriptions/missing/status")

    assert response.status_code == 404
    _assert_error_shape(response.json(), "JOB_NOT_FOUND")


def test_result_job_not_completed_uses_unified_error_shape() -> None:
    class FakeResultService:
        def get_completed_result(self, db, job_id):
            raise ApiErrorException(ErrorCode.JOB_NOT_COMPLETED, details={"job_id": job_id})

    client = _client_with_overrides({get_result_service: lambda: FakeResultService()})

    response = client.get("/api/v1/transcriptions/job-1")

    assert response.status_code == 409
    _assert_error_shape(response.json(), "JOB_NOT_COMPLETED")


def test_download_export_not_found_uses_unified_error_shape() -> None:
    class FakeDownloadService:
        def open_export(self, db, *, job_id, export_type):
            raise ApiErrorException(ErrorCode.EXPORT_NOT_FOUND, details={"type": export_type})

    client = _client_with_overrides({get_download_service: lambda: FakeDownloadService()})

    response = client.get("/api/v1/transcriptions/job-1/download/pdf")

    assert response.status_code == 404
    _assert_error_shape(response.json(), "EXPORT_NOT_FOUND")


def test_download_export_not_ready_uses_unified_error_shape() -> None:
    class FakeDownloadService:
        def open_export(self, db, *, job_id, export_type):
            raise ApiErrorException(ErrorCode.EXPORT_NOT_READY, details={"type": export_type})

    client = _client_with_overrides({get_download_service: lambda: FakeDownloadService()})

    response = client.get("/api/v1/transcriptions/job-1/download/midi")

    assert response.status_code == 409
    _assert_error_shape(response.json(), "EXPORT_NOT_READY")


def test_pipeline_failed_uses_unified_error_shape() -> None:
    app = create_app()

    @app.get("/raise-pipeline-failed")
    def raise_pipeline_failed():
        raise ApiErrorException(ErrorCode.PIPELINE_FAILED)

    response = TestClient(app).get("/raise-pipeline-failed")

    assert response.status_code == 500
    _assert_error_shape(response.json(), "PIPELINE_FAILED")


def test_unknown_api_route_uses_route_not_found_error_shape() -> None:
    response = TestClient(create_app()).get("/api/v1/does-not-exist")

    assert response.status_code == 404
    _assert_error_shape(response.json(), "ROUTE_NOT_FOUND")
