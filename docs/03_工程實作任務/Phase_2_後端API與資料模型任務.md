# Phase 2：後端 API 與資料模型任務

> Level 3 工程實作任務文件。本文只拆解開發 ticket，不取代 Level 1 / Level 2 規格。

## Phase 目標

建立 FastAPI 後端、資料模型、migration、storage abstraction 與 MVP API，讓前端與 worker 能以穩定 contract 串接。

## 前置條件

- Phase 1 已確認 artifact 命名與 pipeline 需要的輸入輸出。
- 已決定 Python / FastAPI / SQLAlchemy / Alembic / PostgreSQL。
- Redis / Celery 可先在 Phase 3 接上，Phase 2 可先 mock enqueue。

## 需參考的 Level 1 / Level 2 文件

- Level 1：API設計.md
- Level 1：資料模型設計.md
- Level 1：模組設計.md
- Level 2：音檔上傳功能規格.md
- Level 2：檔案儲存與Artifact規格.md
- Level 2：錯誤處理與使用者提示規格.md

## 任務清單

- `GS-P2-001`：建立 FastAPI 專案骨架
- `GS-P2-002`：建立 database models
- `GS-P2-003`：建立 Alembic migrations
- `GS-P2-004`：建立 Storage Adapter interface
- `GS-P2-005`：建立 LocalStorageAdapter
- `GS-P2-006`：建立 Upload API
- `GS-P2-007`：建立 Job Status API
- `GS-P2-008`：建立 Result API
- `GS-P2-009`：建立 Download API
- `GS-P2-010`：建立 API error response 格式

> Phase 2 開工順序提醒：`GS-P2-010` 是錯誤 response 基礎，應在 `GS-P2-006`、`GS-P2-007`、`GS-P2-008`、`GS-P2-009` 前完成，即使票號排在後面。

## 目前銜接狀態（2026-07-01）

- Phase 1 local pipeline artifact contract 已與 backend storage key 對齊，`drum_events` 使用 `jobs/{job_id}/midi/drum_events.json`。
- 正式前端 API contract 維持不變：`GET /api/v1/transcriptions/{job_id}` 不外露 `pipeline_log` 或 `stage_reports`。
- backend 已新增 internal job detail read path：`InternalJobDetailService.get_pipeline_snapshot(db, job_id)`。此 service 可用 job id 組出 backend/worker 內部 snapshot，包含 job status、failed_stage、artifact keys、stage_reports、warnings、`completed_with_warning`、error code/message、`pipeline_log_found` 與 mock/true pipeline mode。
- pipeline log 缺失時不視為正式 API failure；internal snapshot 會回傳 `pipeline_log_found=false`、`stage_reports=[]`，並保留 DB 已知 artifact keys。
- 專案目前沒有 internal/admin API router；工程師查詢 pipeline snapshot 先使用 `backend/.venv/bin/python scripts/read_pipeline_snapshot.py --job-id <job_id> --pretty`。此 CLI 使用 backend DB/session/settings/storage/service pattern，不新增正式前端 API。

## Ticket 詳細內容

### GS-P2-001 — 建立 FastAPI 專案骨架

**Ticket ID**
GS-P2-001

**Ticket 名稱**
建立 FastAPI 專案骨架

**背景與目的**
建立後端 API server 的最小骨架，提供後續 models、storage、API routes 實作基礎。

**實作範圍**
- 建立 backend app structure。
- 建立 health check endpoint。
- 建立 config loading。
- 建立測試框架基本設定。

**不包含範圍**
- 不實作 transcriptions API。
- 不接 Celery。

**主要修改位置或建議目錄**
- backend/app/
- backend/tests/
- backend/pyproject.toml

**輸入**
- 技術選型與 API base path。

**輸出**
- 可啟動 FastAPI app。
- health check response。

**API / Data Model / Storage 關聯**
- API base path 預留 `/api/v1`。無 Data Model / Storage。

**驗收標準**
- 本機可啟動 API server。
- health check 測試通過。

**測試要求**
- API smoke test。

**相依任務**
無

**風險與注意事項**
- 保持 MVP 範圍，避免順手實作多人協作、即時轉譜或線上修譜。

### GS-P2-002 — 建立 database models

**Ticket ID**
GS-P2-002

**Ticket 名稱**
建立 database models

**背景與目的**
建立 MVP 所需 SQLAlchemy models 與 enum，讓 job、audio、export 可持久化。

**實作範圍**
- 建立 User、AudioFile、TranscriptionJob、DrumTrack、ExportFile models。
- 建立 JobStatus、Stage、ExportFileType、ExportFileStatus enum。
- 定義關聯與 nullable 策略。

**不包含範圍**
- 不做登入流程。
- 不做複雜權限模型。

**主要修改位置或建議目錄**
- backend/app/models/
- backend/app/db/

**輸入**
- Level 1 資料模型設計。

**輸出**
- SQLAlchemy models。
- model unit tests。

**API / Data Model / Storage 關聯**
- 對應 `AudioFile`、`TranscriptionJob`、`DrumTrack`、`ExportFile`。Storage 只存 key。

**驗收標準**
- models 可建立與查詢。
- enum 與 Level 1 一致。

**測試要求**
- model creation tests。
- status enum tests。

**相依任務**
GS-P2-001

**風險與注意事項**
- 保持 MVP 範圍，避免順手實作多人協作、即時轉譜或線上修譜。

### GS-P2-003 — 建立 Alembic migrations

**Ticket ID**
GS-P2-003

**Ticket 名稱**
建立 Alembic migrations

**背景與目的**
建立 database migration 流程，讓開發與 staging 可一致建立 schema。

**實作範圍**
- 初始化 Alembic。
- 建立初版 migration。
- 確認 upgrade / downgrade 可執行。
- 補 migration README 或 command。

**不包含範圍**
- 不做 production migration automation。

**主要修改位置或建議目錄**
- backend/migrations/
- backend/alembic.ini

**輸入**
- GS-P2-002 models。

**輸出**
- 初版 schema migration。

**API / Data Model / Storage 關聯**
- Data Model schema 持久化。無直接 API / Storage。

**驗收標準**
- 空資料庫可跑 migration 建 schema。
- migration 不依賴本機絕對路徑。

**測試要求**
- migration upgrade test。

**相依任務**
GS-P2-002

**風險與注意事項**
- 保持 MVP 範圍，避免順手實作多人協作、即時轉譜或線上修譜。

### GS-P2-004 — 建立 Storage Adapter interface

**Ticket ID**
GS-P2-004

**Ticket 名稱**
建立 Storage Adapter interface

**背景與目的**
定義 storage 抽象，確保 local filesystem 未來可替換成 S3-compatible storage。

**實作範圍**
- 定義 `ArtifactRef`。
- 定義 put/get/exists/create_download_url 或 stream interface。
- 定義 artifact type 與 content type mapping。
- 定義 key sanitizer。

**不包含範圍**
- 不實作真 S3 client。
- 不做 signed URL。

**主要修改位置或建議目錄**
- backend/app/storage/
- backend/app/schemas/artifacts.py

**輸入**
- Level 2 artifact 規格。

**輸出**
- StorageAdapter contract。
- ArtifactRef schema。

**API / Data Model / Storage 關聯**
- Storage key 對應 AudioFile、DrumTrack、ExportFile 欄位。

**驗收標準**
- 業務層可只依賴 interface。
- path traversal 被拒絕。

**測試要求**
- unit tests：key sanitizer、ArtifactRef。

**相依任務**
GS-P2-001

**風險與注意事項**
- 保持 MVP 範圍，避免順手實作多人協作、即時轉譜或線上修譜。

### GS-P2-005 — 建立 LocalStorageAdapter

**Ticket ID**
GS-P2-005

**Ticket 名稱**
建立 LocalStorageAdapter

**背景與目的**
實作 MVP local filesystem storage，供 upload、worker、download 使用。

**實作範圍**
- 實作 put/get/exists。
- 以 configured local root + storage key 讀寫。
- 禁止 `../` path traversal。
- 回傳 ArtifactRef metadata。

**不包含範圍**
- 不實作 S3。
- 不做 lifecycle cleanup。

**主要修改位置或建議目錄**
- backend/app/storage/local.py
- tests/unit/storage/

**輸入**
- StorageAdapter interface。
- local root config。

**輸出**
- LocalStorageAdapter。
- storage tests。

**API / Data Model / Storage 關聯**
- 支援 original、normalized、stems、midi、events、notation、exports、logs keys。

**驗收標準**
- 可保存與讀取檔案。
- 不暴露絕對路徑到 API response。

**測試要求**
- unit tests：put/get/exists。
- security tests：unsafe key。

**相依任務**
GS-P2-004

**風險與注意事項**
- 保持 MVP 範圍，避免順手實作多人協作、即時轉譜或線上修譜。

### GS-P2-006 — 建立 Upload API

**Ticket ID**
GS-P2-006

**Ticket 名稱**
建立 Upload API

**背景與目的**
實作 `POST /api/v1/transcriptions`，建立 AudioFile、TranscriptionJob 並 enqueue。

**實作範圍**
- 支援 multipart file + optional title。
- 驗證副檔名、MIME、100MB 限制、duration metadata。
- 寫入 original artifact。
- 建立 `status=queued` job。
- 呼叫 queue enqueue interface；Phase 2 可先 stub。

**不包含範圍**
- 不執行 ffmpeg、Demucs、ADTOF。
- 不回傳分析結果。

**主要修改位置或建議目錄**
- backend/app/api/transcriptions.py
- backend/app/services/upload_service.py

**輸入**
- MP3/WAV file。
- title optional。

**輸出**
- 202 response：job_id、status_url、result_url。
- AudioFile / TranscriptionJob rows。
- original artifact。

**API / Data Model / Storage 關聯**
- API：`POST /api/v1/transcriptions`；Data：AudioFile、TranscriptionJob；Storage：original_audio。

**驗收標準**
- 合法 MP3 / WAV 回 `202 Accepted`，response 包含 `job_id`、`status_url`、`result_url`。
- 非法格式回 `INVALID_FILE_TYPE`。
- 超過 100 MB 回 `FILE_TOO_LARGE`。
- 音檔超過 10 分鐘回 `AUDIO_TOO_LONG`。
- metadata 不可讀回 `AUDIO_METADATA_UNREADABLE`。
- original artifact 寫入失敗回 `STORAGE_WRITE_FAILED`。
- Phase 2 stub enqueue 失敗時回 `QUEUE_ENQUEUE_FAILED` 或 rollback，不留下不可追蹤 orphan job。
- API response 不等待 ffmpeg、Demucs、ADTOF 或任何 pipeline stage。

**測試要求**
- integration test：合法 upload 建立 `AudioFile`、`TranscriptionJob` 與 original artifact。
- error test：`INVALID_FILE_TYPE`。
- error test：`FILE_TOO_LARGE`。
- error test：`AUDIO_TOO_LONG`。
- error test：`AUDIO_METADATA_UNREADABLE`。
- error test：`STORAGE_WRITE_FAILED`。
- error test：stub enqueue failure 不留下 orphan job。

**相依任務**
GS-P2-002, GS-P2-005, GS-P2-010

**風險與注意事項**
- 保持 MVP 範圍，避免順手實作多人協作、即時轉譜或線上修譜。

### GS-P2-007 — 建立 Job Status API

**Ticket ID**
GS-P2-007

**Ticket 名稱**
建立 Job Status API

**背景與目的**
實作狀態查詢 API，讓前端輪詢 job 狀態與進度。

**實作範圍**
- 建立 `GET /api/v1/transcriptions/{job_id}/status`。
- 讀取 TranscriptionJob status/stage/progress/timestamps/error。
- 提供 stage-to-message mapping。
- 處理 job not found。

**不包含範圍**
- 不查 storage。
- 不執行任何 pipeline。

**主要修改位置或建議目錄**
- backend/app/api/transcriptions.py
- backend/app/services/job_query_service.py

**輸入**
- job_id。

**輸出**
- status JSON。

**API / Data Model / Storage 關聯**
- API：status endpoint；Data：TranscriptionJob。

**驗收標準**
- queued / processing / completed / failed 都有穩定 response。
- not found 回 `JOB_NOT_FOUND`。

**測試要求**
- integration tests：各 status response。

**相依任務**
GS-P2-002, GS-P2-010

**風險與注意事項**
- 保持 MVP 範圍，避免順手實作多人協作、即時轉譜或線上修譜。

### GS-P2-008 — 建立 Result API

**Ticket ID**
GS-P2-008

**Ticket 名稱**
建立 Result API

**背景與目的**
實作 completed job 的結果 metadata API。

**實作範圍**
- 建立 `GET /api/v1/transcriptions/{job_id}`。
- completed 時組合 AudioFile、DrumTrack、ExportFile。
- processing 時回 `409 JOB_NOT_COMPLETED`。
- 回傳 preview.musicxml_url 與 exports download_url。

**不包含範圍**
- 不產生檔案。
- 不直接讀 storage 內容。

**主要修改位置或建議目錄**
- backend/app/api/transcriptions.py
- backend/app/services/result_service.py

**輸入**
- job_id。

**輸出**
- result JSON。

**API / Data Model / Storage 關聯**
- API：result endpoint；Data：AudioFile、DrumTrack、ExportFile。

**驗收標準**
- completed job 回傳 exports。
- 非 completed job 回 409。

**測試要求**
- integration tests：completed result、processing conflict。

**相依任務**
GS-P2-002, GS-P2-007, GS-P2-010

**風險與注意事項**
- 保持 MVP 範圍，避免順手實作多人協作、即時轉譜或線上修譜。

### GS-P2-009 — 建立 Download API

**Ticket ID**
GS-P2-009

**Ticket 名稱**
建立 Download API

**背景與目的**
實作 MIDI / MusicXML / PDF 下載 API，透過 StorageAdapter 回傳已產生 export。

**實作範圍**
- 建立三個 download route 或共用 route。
- 檢查 job completed。
- 檢查 ExportFile status available。
- 透過 StorageAdapter stream 檔案。
- 設定 content type 與 filename。

**不包含範圍**
- 不提供 raw MIDI download。
- 不暴露 storage key / local path。

**主要修改位置或建議目錄**
- backend/app/api/transcriptions.py
- backend/app/services/download_service.py

**輸入**
- job_id、export type。

**輸出**
- file response。
- 錯誤 response。

**API / Data Model / Storage 關聯**
- API：download endpoints；Data：ExportFile；Storage：processed MIDI、MusicXML、PDF。

**驗收標準**
- available export 可下載。
- missing export 回 404。
- not ready 回 409。

**測試要求**
- integration tests：download midi/musicxml/pdf。
- error tests：EXPORT_NOT_FOUND、EXPORT_NOT_READY。

**相依任務**
GS-P2-005, GS-P2-008, GS-P2-010

**風險與注意事項**
- 保持 MVP 範圍，避免順手實作多人協作、即時轉譜或線上修譜。

### GS-P2-010 — 建立 API error response 格式

**Ticket ID**
GS-P2-010

**Ticket 名稱**
建立 API error response 格式

**背景與目的**
建立統一錯誤模型與例外映射，避免 API 回傳 stack trace。

**實作範圍**
- 定義 error schema。
- 建立 exception handlers。
- 建立 error catalog。
- 映射 upload、job、export、storage 常見錯誤。

**不包含範圍**
- 不做完整 observability dashboard。

**主要修改位置或建議目錄**
- backend/app/core/errors.py
- backend/app/api/error_handlers.py
- backend/tests/

**輸入**
- 錯誤碼與 Level 1/2 error catalog。

**輸出**
- 統一 `{ error: { code, message, retriable, details } }` response。

**API / Data Model / Storage 關聯**
- 所有 API 共用錯誤格式；Data Model failed fields 由 worker ticket 處理。

**驗收標準**
- 所有已知錯誤符合格式。
- response 不含 traceback。

**測試要求**
- API error format tests。
- snapshot / contract tests。

**相依任務**
GS-P2-001

**風險與注意事項**
- 保持 MVP 範圍，避免順手實作多人協作、即時轉譜或線上修譜。

## Phase 完成標準

- Upload / status / result / download API contract 完成。
- Database models 與 migration 可建立 schema。
- LocalStorageAdapter 可保存與讀取檔案。
- API error response 符合統一格式。
