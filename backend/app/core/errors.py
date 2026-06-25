from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from http import HTTPStatus
from typing import Any


class ErrorCode(StrEnum):
    INVALID_FILE_TYPE = "INVALID_FILE_TYPE"
    FILE_TOO_LARGE = "FILE_TOO_LARGE"
    AUDIO_TOO_LONG = "AUDIO_TOO_LONG"
    AUDIO_METADATA_UNREADABLE = "AUDIO_METADATA_UNREADABLE"
    QUEUE_ENQUEUE_FAILED = "QUEUE_ENQUEUE_FAILED"
    JOB_NOT_FOUND = "JOB_NOT_FOUND"
    JOB_NOT_COMPLETED = "JOB_NOT_COMPLETED"
    EXPORT_NOT_FOUND = "EXPORT_NOT_FOUND"
    EXPORT_NOT_READY = "EXPORT_NOT_READY"
    STORAGE_WRITE_FAILED = "STORAGE_WRITE_FAILED"
    STORAGE_READ_FAILED = "STORAGE_READ_FAILED"
    ARTIFACT_NOT_FOUND = "ARTIFACT_NOT_FOUND"
    ARTIFACT_INVALID = "ARTIFACT_INVALID"
    PATH_TRAVERSAL_REJECTED = "PATH_TRAVERSAL_REJECTED"
    AUDIO_DECODE_FAILED = "AUDIO_DECODE_FAILED"
    SOURCE_SEPARATION_FAILED = "SOURCE_SEPARATION_FAILED"
    DRUM_TRANSCRIPTION_FAILED = "DRUM_TRANSCRIPTION_FAILED"
    MIDI_POST_PROCESSING_FAILED = "MIDI_POST_PROCESSING_FAILED"
    NOTATION_GENERATION_FAILED = "NOTATION_GENERATION_FAILED"
    PDF_EXPORT_FAILED = "PDF_EXPORT_FAILED"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    INTERNAL_SERVER_ERROR = "INTERNAL_SERVER_ERROR"


@dataclass(frozen=True)
class ErrorDefinition:
    code: str
    message: str
    status_code: int
    retriable: bool = False


ERROR_CATALOG: dict[str, ErrorDefinition] = {
    ErrorCode.INVALID_FILE_TYPE: ErrorDefinition(
        code=ErrorCode.INVALID_FILE_TYPE,
        message="目前只支援 MP3 或 WAV 音檔。",
        status_code=HTTPStatus.UNSUPPORTED_MEDIA_TYPE,
    ),
    ErrorCode.FILE_TOO_LARGE: ErrorDefinition(
        code=ErrorCode.FILE_TOO_LARGE,
        message="音檔超過目前允許的大小限制。",
        status_code=HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
    ),
    ErrorCode.AUDIO_TOO_LONG: ErrorDefinition(
        code=ErrorCode.AUDIO_TOO_LONG,
        message="音檔長度超過目前允許的分析時間。",
        status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
    ),
    ErrorCode.AUDIO_METADATA_UNREADABLE: ErrorDefinition(
        code=ErrorCode.AUDIO_METADATA_UNREADABLE,
        message="無法讀取音檔資訊，請確認檔案可正常播放後再重新上傳。",
        status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
    ),
    ErrorCode.QUEUE_ENQUEUE_FAILED: ErrorDefinition(
        code=ErrorCode.QUEUE_ENQUEUE_FAILED,
        message="暫時無法建立分析任務，請稍後再試。",
        status_code=HTTPStatus.SERVICE_UNAVAILABLE,
        retriable=True,
    ),
    ErrorCode.JOB_NOT_FOUND: ErrorDefinition(
        code=ErrorCode.JOB_NOT_FOUND,
        message="找不到指定的分析任務。",
        status_code=HTTPStatus.NOT_FOUND,
    ),
    ErrorCode.JOB_NOT_COMPLETED: ErrorDefinition(
        code=ErrorCode.JOB_NOT_COMPLETED,
        message="分析任務尚未完成，請稍後再查詢結果。",
        status_code=HTTPStatus.CONFLICT,
        retriable=True,
    ),
    ErrorCode.EXPORT_NOT_FOUND: ErrorDefinition(
        code=ErrorCode.EXPORT_NOT_FOUND,
        message="找不到指定的匯出檔案。",
        status_code=HTTPStatus.NOT_FOUND,
    ),
    ErrorCode.EXPORT_NOT_READY: ErrorDefinition(
        code=ErrorCode.EXPORT_NOT_READY,
        message="匯出檔案尚未準備完成。",
        status_code=HTTPStatus.CONFLICT,
        retriable=True,
    ),
    ErrorCode.STORAGE_WRITE_FAILED: ErrorDefinition(
        code=ErrorCode.STORAGE_WRITE_FAILED,
        message="檔案儲存失敗，請稍後再試。",
        status_code=HTTPStatus.SERVICE_UNAVAILABLE,
        retriable=True,
    ),
    ErrorCode.STORAGE_READ_FAILED: ErrorDefinition(
        code=ErrorCode.STORAGE_READ_FAILED,
        message="檔案讀取失敗，請稍後再試。",
        status_code=HTTPStatus.SERVICE_UNAVAILABLE,
        retriable=True,
    ),
    ErrorCode.ARTIFACT_NOT_FOUND: ErrorDefinition(
        code=ErrorCode.ARTIFACT_NOT_FOUND,
        message="找不到指定的處理檔案。",
        status_code=HTTPStatus.NOT_FOUND,
    ),
    ErrorCode.ARTIFACT_INVALID: ErrorDefinition(
        code=ErrorCode.ARTIFACT_INVALID,
        message="處理檔案格式不正確或已損壞。",
        status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
    ),
    ErrorCode.PATH_TRAVERSAL_REJECTED: ErrorDefinition(
        code=ErrorCode.PATH_TRAVERSAL_REJECTED,
        message="檔案路徑不合法。",
        status_code=HTTPStatus.BAD_REQUEST,
    ),
    ErrorCode.AUDIO_DECODE_FAILED: ErrorDefinition(
        code=ErrorCode.AUDIO_DECODE_FAILED,
        message="音檔解碼失敗，請確認檔案可正常播放。",
        status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
    ),
    ErrorCode.SOURCE_SEPARATION_FAILED: ErrorDefinition(
        code=ErrorCode.SOURCE_SEPARATION_FAILED,
        message="鼓軌分離失敗，請嘗試使用音質較清楚的檔案。",
        status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
    ),
    ErrorCode.DRUM_TRANSCRIPTION_FAILED: ErrorDefinition(
        code=ErrorCode.DRUM_TRANSCRIPTION_FAILED,
        message="鼓 MIDI 轉寫失敗，請嘗試使用鼓聲較清楚的音檔。",
        status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
    ),
    ErrorCode.MIDI_POST_PROCESSING_FAILED: ErrorDefinition(
        code=ErrorCode.MIDI_POST_PROCESSING_FAILED,
        message="MIDI 後處理失敗。",
        status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
    ),
    ErrorCode.NOTATION_GENERATION_FAILED: ErrorDefinition(
        code=ErrorCode.NOTATION_GENERATION_FAILED,
        message="鼓譜產生失敗，但可嘗試下載其他已完成的輸出。",
        status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
    ),
    ErrorCode.PDF_EXPORT_FAILED: ErrorDefinition(
        code=ErrorCode.PDF_EXPORT_FAILED,
        message="PDF 匯出失敗，請先下載 MusicXML。",
        status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
    ),
    ErrorCode.VALIDATION_ERROR: ErrorDefinition(
        code=ErrorCode.VALIDATION_ERROR,
        message="請求資料格式不正確。",
        status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
    ),
    ErrorCode.INTERNAL_SERVER_ERROR: ErrorDefinition(
        code=ErrorCode.INTERNAL_SERVER_ERROR,
        message="系統發生未預期錯誤，請稍後再試。",
        status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
        retriable=True,
    ),
}


def normalize_error_code(code: str | ErrorCode) -> str:
    return str(code.value if isinstance(code, ErrorCode) else code)


def get_error_definition(code: str | ErrorCode) -> ErrorDefinition:
    return ERROR_CATALOG.get(normalize_error_code(code), ERROR_CATALOG[ErrorCode.INTERNAL_SERVER_ERROR])


def status_code_for_error(code: str | ErrorCode, override: int | None = None) -> int:
    if override is not None:
        return override
    return int(get_error_definition(code).status_code)


def build_error_payload(
    code: str | ErrorCode,
    *,
    message: str | None = None,
    retriable: bool | None = None,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    definition = get_error_definition(code)
    return {
        "error": {
            "code": definition.code,
            "message": message or definition.message,
            "retriable": definition.retriable if retriable is None else retriable,
            "details": details or {},
        }
    }


class ApiErrorException(Exception):
    def __init__(
        self,
        code: str | ErrorCode,
        *,
        message: str | None = None,
        status_code: int | None = None,
        retriable: bool | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        definition = get_error_definition(code)
        self.code = definition.code
        self.message = message or definition.message
        self.status_code = status_code_for_error(definition.code, status_code)
        self.retriable = definition.retriable if retriable is None else retriable
        self.details = details or {}
        super().__init__(self.message)

    def to_payload(self) -> dict[str, Any]:
        return build_error_payload(
            self.code,
            message=self.message,
            retriable=self.retriable,
            details=self.details,
        )


def api_error_from_exception(exc: Exception) -> ApiErrorException:
    code = getattr(exc, "code", ErrorCode.INTERNAL_SERVER_ERROR)
    return ApiErrorException(code)
