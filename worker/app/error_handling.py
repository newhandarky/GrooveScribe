from __future__ import annotations

from dataclasses import dataclass

from billiard.exceptions import SoftTimeLimitExceeded, TimeLimitExceeded

from .constants import PipelineStage, WorkerErrorCode
from .services.job_status_service import InvalidJobStateTransitionError
from .storage import StorageKeyError


ERROR_MESSAGES: dict[str, str] = {
    WorkerErrorCode.ARTIFACT_NOT_FOUND.value: "找不到指定的處理檔案。",
    WorkerErrorCode.DRUM_TRANSCRIPTION_FAILED.value: "鼓 MIDI 轉寫失敗，請嘗試使用鼓聲較清楚的音檔。",
    WorkerErrorCode.INVALID_JOB_STATE_TRANSITION.value: "分析任務狀態轉換不合法。",
    WorkerErrorCode.MIDI_POST_PROCESSING_FAILED.value: "MIDI 後處理失敗。",
    WorkerErrorCode.NOTATION_GENERATION_FAILED.value: "鼓譜產生失敗，但可嘗試下載其他已完成的輸出。",
    WorkerErrorCode.PDF_EXPORT_FAILED.value: "PDF 匯出失敗，請先下載 MusicXML。",
    WorkerErrorCode.PIPELINE_FAILED.value: "音訊分析流程失敗，請稍後再試或重新上傳音檔。",
    WorkerErrorCode.SOURCE_SEPARATION_FAILED.value: "鼓軌分離失敗，請嘗試使用音質較清楚的檔案。",
    WorkerErrorCode.STORAGE_WRITE_FAILED.value: "檔案儲存失敗，請稍後再試。",
    WorkerErrorCode.WORKER_TIMEOUT.value: "分析任務執行逾時，請稍後再試或重新上傳音檔。",
}

STAGE_ERROR_CODES: dict[str, str] = {
    PipelineStage.SOURCE_SEPARATION.value: WorkerErrorCode.SOURCE_SEPARATION_FAILED.value,
    PipelineStage.DRUM_TRANSCRIPTION.value: WorkerErrorCode.DRUM_TRANSCRIPTION_FAILED.value,
    PipelineStage.MIDI_POST_PROCESSING.value: WorkerErrorCode.MIDI_POST_PROCESSING_FAILED.value,
    PipelineStage.NOTATION_GENERATION.value: WorkerErrorCode.NOTATION_GENERATION_FAILED.value,
    PipelineStage.PDF_EXPORT.value: WorkerErrorCode.PDF_EXPORT_FAILED.value,
}


class PipelineStageError(Exception):
    def __init__(self, stage: str, message: str = "pipeline stage failed") -> None:
        self.stage = stage
        super().__init__(message)


@dataclass(frozen=True)
class WorkerError:
    code: str
    message: str
    stage: str


def error_message_for(code: str) -> str:
    return ERROR_MESSAGES.get(code, ERROR_MESSAGES[WorkerErrorCode.PIPELINE_FAILED.value])


def map_exception_to_worker_error(exc: Exception, *, current_stage: str | None = None) -> WorkerError:
    stage = current_stage or PipelineStage.FAILED.value
    if isinstance(exc, (SoftTimeLimitExceeded, TimeLimitExceeded, TimeoutError)):
        return WorkerError(
            code=WorkerErrorCode.WORKER_TIMEOUT.value,
            message=error_message_for(WorkerErrorCode.WORKER_TIMEOUT.value),
            stage=stage,
        )
    if isinstance(exc, InvalidJobStateTransitionError):
        return WorkerError(
            code=WorkerErrorCode.INVALID_JOB_STATE_TRANSITION.value,
            message=error_message_for(WorkerErrorCode.INVALID_JOB_STATE_TRANSITION.value),
            stage=stage,
        )
    if isinstance(exc, StorageKeyError):
        return WorkerError(
            code=WorkerErrorCode.STORAGE_WRITE_FAILED.value,
            message=error_message_for(WorkerErrorCode.STORAGE_WRITE_FAILED.value),
            stage=stage,
        )
    if isinstance(exc, PipelineStageError):
        code = STAGE_ERROR_CODES.get(exc.stage, WorkerErrorCode.PIPELINE_FAILED.value)
        return WorkerError(code=code, message=error_message_for(code), stage=exc.stage)
    code = STAGE_ERROR_CODES.get(stage, WorkerErrorCode.PIPELINE_FAILED.value)
    return WorkerError(code=code, message=error_message_for(code), stage=stage)
