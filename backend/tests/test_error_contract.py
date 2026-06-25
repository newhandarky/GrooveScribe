from app.core.errors import (
    ApiErrorException,
    ErrorCode,
    api_error_from_exception,
    build_error_payload,
    get_error_definition,
    status_code_for_error,
)
from app.storage.errors import ArtifactNotFoundError, StorageWriteFailedError


def test_known_error_payload_uses_stable_contract() -> None:
    payload = build_error_payload(ErrorCode.INVALID_FILE_TYPE)

    assert set(payload.keys()) == {"error"}
    assert payload["error"] == {
        "code": "INVALID_FILE_TYPE",
        "message": "目前只支援 MP3 或 WAV 音檔。",
        "retriable": False,
        "details": {},
    }


def test_error_payload_supports_safe_details() -> None:
    payload = build_error_payload(
        ErrorCode.FILE_TOO_LARGE,
        details={"max_size_mb": 100},
    )

    assert payload["error"]["details"] == {"max_size_mb": 100}


def test_unknown_error_code_falls_back_to_internal_server_error() -> None:
    payload = build_error_payload("UNKNOWN_ERROR")

    assert payload["error"]["code"] == "INTERNAL_SERVER_ERROR"
    assert payload["error"]["retriable"] is True


def test_api_error_exception_keeps_status_and_payload_consistent() -> None:
    exc = ApiErrorException(ErrorCode.JOB_NOT_COMPLETED, details={"job_id": "job-1"})

    assert exc.status_code == 409
    assert exc.to_payload()["error"]["code"] == "JOB_NOT_COMPLETED"
    assert exc.to_payload()["error"]["details"] == {"job_id": "job-1"}


def test_storage_error_can_be_mapped_without_exposing_internal_details() -> None:
    exc = api_error_from_exception(StorageWriteFailedError("disk quota exceeded at /tmp/internal"))

    assert exc.code == "STORAGE_WRITE_FAILED"
    assert exc.status_code == 503
    assert exc.to_payload()["error"]["message"] == "檔案儲存失敗，請稍後再試。"
    assert "/tmp/internal" not in exc.to_payload()["error"]["message"]


def test_error_catalog_maps_missing_artifact_to_not_found() -> None:
    exc = api_error_from_exception(ArtifactNotFoundError())

    assert get_error_definition(exc.code).code == "ARTIFACT_NOT_FOUND"
    assert status_code_for_error(exc.code) == 404


def test_payload_does_not_include_traceback_field() -> None:
    payload = build_error_payload(ErrorCode.INTERNAL_SERVER_ERROR)

    assert "traceback" not in payload["error"]
    assert "stack" not in payload["error"]
