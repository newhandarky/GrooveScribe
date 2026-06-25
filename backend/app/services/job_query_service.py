from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.errors import ApiErrorException, ErrorCode
from app.models import TranscriptionJob
from app.models.enums import PipelineStage

_STAGE_MESSAGES: dict[str, str] = {
    PipelineStage.UPLOADED.value: "音檔已上傳，等待排隊。",
    PipelineStage.QUEUED.value: "任務已排隊，等待開始分析。",
    PipelineStage.PREPROCESSING.value: "正在標準化音檔。",
    PipelineStage.SOURCE_SEPARATION.value: "正在分離鼓軌。",
    PipelineStage.STEM_VALIDATION.value: "正在檢查鼓軌品質。",
    PipelineStage.DRUM_TRANSCRIPTION.value: "正在轉寫鼓 MIDI。",
    PipelineStage.MIDI_POST_PROCESSING.value: "正在整理與量化 MIDI。",
    PipelineStage.NOTATION_GENERATION.value: "正在產生鼓譜。",
    PipelineStage.PDF_EXPORT.value: "正在匯出 PDF。",
    PipelineStage.COMPLETED.value: "分析已完成。",
    PipelineStage.FAILED.value: "分析失敗，請查看錯誤訊息。",
}


class JobQueryService:
    def get_job_or_raise(self, db: Session, job_id: str) -> TranscriptionJob:
        job = db.get(TranscriptionJob, job_id)
        if job is None:
            raise ApiErrorException(ErrorCode.JOB_NOT_FOUND, details={"job_id": job_id})
        return job

    def stage_message(self, job: TranscriptionJob) -> str:
        return _STAGE_MESSAGES.get(job.stage.value, "任務狀態已更新。")

    def error_payload(self, job: TranscriptionJob) -> dict[str, str | None] | None:
        if not job.error_code and not job.error_message and not job.error_stage:
            return None
        return {
            "code": job.error_code,
            "message": job.error_message,
            "stage": job.error_stage,
        }
