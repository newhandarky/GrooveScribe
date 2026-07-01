# Phase 3：背景 Worker 與 Queue 任務

> Level 3 工程實作任務文件。本文只拆解開發 ticket，不取代 Level 1 / Level 2 規格。

## Phase 目標

建立 Redis / Celery 背景任務系統，讓 transcription job 可由 worker 非同步處理並更新狀態。

## 前置條件

- Phase 2 已有 TranscriptionJob model、StorageAdapter interface 與 API 基礎。
- Redis 可在本地啟動。
- Phase 4 的真 pipeline 可尚未完成，Phase 3 可先用 mock pipeline。

## 需參考的 Level 1 / Level 2 文件

- Level 1：系統架構.md
- Level 1：技術選型.md
- Level 2：背景任務與Job狀態規格.md
- Level 2：AI_Pipeline執行規格.md
- Level 2：錯誤處理與使用者提示規格.md

## 任務清單

- `GS-P3-001`：建立 Redis / Celery 設定
- `GS-P3-002`：建立 transcription job task
- `GS-P3-003`：建立 job status update service
- `GS-P3-004`：建立 pipeline stage orchestration
- `GS-P3-005`：建立 retry / timeout / failed handling
- `GS-P3-006`：建立 worker logging
- `GS-P3-007`：建立 Queue enqueue interface 與 Upload API 實際派送整合

## Ticket 詳細內容

### GS-P3-001 — 建立 Redis / Celery 設定

**Ticket ID**
GS-P3-001

**Ticket 名稱**
建立 Redis / Celery 設定

**背景與目的**
建立 queue broker 與 Celery worker 基礎設定，支援長時間背景任務。

**實作範圍**
- 加入 Celery app config。
- 設定 Redis broker / result backend 或只用 broker。
- 建立 worker 啟動命令。
- 設定 queue name、concurrency、task timeout 預設。

**不包含範圍**
- 不做 autoscaling。
- 不拆多隊列。

**主要修改位置或建議目錄**
- worker/app/celery_app.py
- backend/app/queue/
- infra/env/

**輸入**
- Redis URL、worker config。

**輸出**
- 可啟動 Celery worker。
- 可送出 smoke task。

**API / Data Model / Storage 關聯**
- API 透過 queue interface enqueue；無直接 Storage。

**驗收標準**
- 本地 Redis + worker 可跑 smoke task。

**測試要求**
- queue smoke test。

**相依任務**
GS-P2-001

**風險與注意事項**
- 保持 MVP 範圍，避免順手實作多人協作、即時轉譜或線上修譜。

### GS-P3-002 — 建立 transcription job task

**Ticket ID**
GS-P3-002

**Ticket 名稱**
建立 transcription job task

**背景與目的**
建立 worker task 入口，只接受 `job_id` 並由 database 讀取完整 job。

**實作範圍**
- 定義 `transcribe_audio(job_id, pipeline_config_id=None)`。
- 從 database 讀取 job 與 AudioFile。
- 呼叫 pipeline runner interface；初期可 mock。
- 處理 job not found。

**不包含範圍**
- 不在 task payload 傳完整檔案路徑。
- 不在 API request 內呼叫 task function。

**主要修改位置或建議目錄**
- worker/app/tasks/transcription.py
- worker/app/pipeline_runner.py

**輸入**
- job_id。
- pipeline_config_id optional。

**輸出**
- job started / completed / failed 狀態更新。

**API / Data Model / Storage 關聯**
- Data：TranscriptionJob、AudioFile；Storage：由 pipeline runner 使用。

**驗收標準**
- task 可被 enqueue 並消費。
- payload 不信任除 job_id 外的資料。

**測試要求**
- worker integration test with mock pipeline。

**相依任務**
GS-P3-001, GS-P2-002

**風險與注意事項**
- 保持 MVP 範圍，避免順手實作多人協作、即時轉譜或線上修譜。

### GS-P3-003 — 建立 job status update service

**Ticket ID**
GS-P3-003

**Ticket 名稱**
建立 job status update service

**背景與目的**
集中處理 job status、stage、progress、timestamps 與狀態轉移。

**實作範圍**
- 建立 service：mark_processing、update_stage、mark_completed、mark_failed。
- 驗證合法狀態轉移。
- 寫入 started_at、completed_at、failed_at。
- failed 必填 error_code、error_message、error_stage。

**不包含範圍**
- 不做 cancel API。
- 不做 watchdog。

**主要修改位置或建議目錄**
- worker/app/services/job_status_service.py
- backend/app/domain/job_status.py

**輸入**
- job_id、target status/stage/progress、error。

**輸出**
- 更新後的 TranscriptionJob。

**API / Data Model / Storage 關聯**
- Data：TranscriptionJob status/stage/progress/error fields。

**驗收標準**
- 非法轉移被拒絕。
- status API 可讀到 worker 更新。

**測試要求**
- unit tests：狀態轉移。
- integration test：worker update 後 API status 可查。

**相依任務**
GS-P3-002, GS-P2-007

**風險與注意事項**
- 保持 MVP 範圍，避免順手實作多人協作、即時轉譜或線上修譜。

### GS-P3-004 — 建立 pipeline stage orchestration

**Ticket ID**
GS-P3-004

**Ticket 名稱**
建立 pipeline stage orchestration

**背景與目的**
建立 worker 端 stage orchestration，先用 mock stage 串出完整流程。

**實作範圍**
- 定義 stage list 與 progress mapping。
- 每個 stage 前後呼叫 status update。
- 以 mock pipeline 產生假 artifacts metadata。
- 保留 Phase 4 接真 pipeline 的介面。

**不包含範圍**
- 不整合真 Demucs / ADTOF。
- 不產生真 MIDI。

**主要修改位置或建議目錄**
- worker/app/pipeline_runner.py
- worker/app/stages/

**輸入**
- job_id。
- stage config。

**輸出**
- stage progress updates。
- mock artifacts。

**API / Data Model / Storage 關聯**
- Data：TranscriptionJob；Storage：可先用 mock keys。

**驗收標準**
- queued → processing → completed 流程可跑通。
- 任一 mock stage 失敗會 failed。

**測試要求**
- orchestration tests。
- failure path tests。

**相依任務**
GS-P3-003

**風險與注意事項**
- 保持 MVP 範圍，避免順手實作多人協作、即時轉譜或線上修譜。

### GS-P3-005 — 建立 retry / timeout / failed handling

**Ticket ID**
GS-P3-005

**Ticket 名稱**
建立 retry / timeout / failed handling

**背景與目的**
定義 worker 長任務失敗策略，避免 job 永遠卡在 processing。

**實作範圍**
- 設定 Celery soft/hard timeout。
- 定義哪些錯誤 retriable。
- 捕捉 timeout、storage、pipeline exception。
- 將錯誤映射到 job failed。

**不包含範圍**
- 不做 UI retry button。
- 不做自動多次重跑整條 pipeline，除非是 queue 層短暫錯誤。

**主要修改位置或建議目錄**
- worker/app/error_handling.py
- worker/app/tasks/transcription.py

**輸入**
- exception、stage、job_id。

**輸出**
- failed job fields。
- worker logs。

**API / Data Model / Storage 關聯**
- Data：TranscriptionJob.error_*；API：status failed response。

**驗收標準**
- timeout job 會 failed。
- exception 不會洩漏到 API response。

**測試要求**
- timeout test。
- stage exception test。

**相依任務**
GS-P3-003, GS-P3-004, GS-P2-010

**風險與注意事項**
- 保持 MVP 範圍，避免順手實作多人協作、即時轉譜或線上修譜。

### GS-P3-006 — 建立 worker logging

**Ticket ID**
GS-P3-006

**Ticket 名稱**
建立 worker logging

**背景與目的**
建立可追蹤 job、stage、artifact 與錯誤的 worker log 格式。

**實作範圍**
- 每筆 log 包含 job_id、stage、event、duration optional。
- pipeline error 寫入 internal_error_ref 或 log artifact。
- 避免 log 中輸出敏感 token 或過長 stack。

**不包含範圍**
- 不做集中式 log 平台。
- 不做 metrics dashboard。

**主要修改位置或建議目錄**
- worker/app/logging.py
- worker/app/pipeline_runner.py

**輸入**
- job_id、stage、event metadata。

**輸出**
- structured logs。
- pipeline log artifact optional。

**API / Data Model / Storage 關聯**
- Storage：`jobs/{job_id}/logs/pipeline.json`；Data：internal_error_ref optional。

**驗收標準**
- 可從 log 追蹤每個 job 的 stage。
- failed job 有 error ref。
- Mock worker 的 `jobs/{job_id}/logs/pipeline.json` 需包含 internal `stage_reports` read model，至少能表達 stage name/status/artifacts/report/warnings/error，並保留既有 event log。
- Backend internal `InternalJobDetailService.get_pipeline_snapshot(db, job_id)` 可讀取 mock worker 寫出的 `stage_reports`，並將 PDF `completed_with_warning`、stage warnings 與 failed stage error 組成內部查詢 snapshot；正式前端 Result API 暫不外露此欄位。
- 在 internal/admin route pattern 尚未建立前，工程師使用 `scripts/read_pipeline_snapshot.py --job-id <job_id>` 查詢 pipeline snapshot；這是 debug CLI，不代表 production worker 已接真 Demucs / ADTOF。
- Integration smoke 已覆蓋 mock worker 跑完 job 後，用同一個 `job_id` 透過 `scripts/read_pipeline_snapshot.py` 讀到 completed snapshot、artifact keys、`stage_reports`、PDF `completed_with_warning` 與 `pipeline_log_found=true`。

**測試要求**
- unit test：log context。
- manual test：跑 mock job 檢查 log。

**相依任務**
GS-P3-002, GS-P3-004, GS-P2-005

**風險與注意事項**
- 保持 MVP 範圍，避免順手實作多人協作、即時轉譜或線上修譜。

### GS-P3-007 — 建立 Queue enqueue interface 與 Upload API 實際派送整合

**Ticket ID**
GS-P3-007

**Ticket 名稱**
建立 Queue enqueue interface 與 Upload API 實際派送整合

**背景與目的**
Phase 2 的 Upload API 可先使用 stub enqueue；本 ticket 負責把 stub 換成實際 Celery task 派送，確保 `POST /api/v1/transcriptions` 真的會 enqueue `transcribe_audio(job_id)`，避免 API 與 worker 串接責任不清。

**實作範圍**
- 建立 backend queue enqueue interface，例如 `enqueue_transcription_job(job_id, pipeline_config_id=None)`。
- 將 Upload API 的 stub enqueue 改為呼叫實際 Celery task。
- 確認 task payload 只包含 `job_id` 與 optional config id。
- enqueue 成功後維持 `TranscriptionJob.status=queued`。
- enqueue 失敗時依 Level 2 規格 rollback 或標記 failed，並回傳穩定錯誤。

**不包含範圍**
- 不執行 Demucs / ADTOF-pytorch。
- 不在 API request 中等待 worker 完成。
- 不實作任務取消或優先級。

**主要修改位置或建議目錄**
- backend/app/queue/
- backend/app/services/upload_service.py
- worker/app/tasks/transcription.py
- backend/tests/integration/

**輸入**
- Upload API 建立出的 `job_id`。
- optional `pipeline_config_id`。

**輸出**
- 已送入 Celery / Redis queue 的 transcription task。
- 可被 worker 消費的 `transcribe_audio(job_id)`。

**API / Data Model / Storage 關聯**
- API：`POST /api/v1/transcriptions`。
- Data：`TranscriptionJob.status=queued`、`stage=queued`。
- Storage：已存在 original audio artifact；此 ticket 不新增 artifact。

**驗收標準**
- 呼叫 Upload API 後，Celery queue 中可觀察到對應 job task。
- Worker 可消費 Upload API 建立的 job。
- API response 仍立即回傳 `202 Accepted`，不等待 pipeline。
- enqueue 失敗時不留下不可追蹤的 orphan job。

**測試要求**
- integration test：Upload API 成功後呼叫 enqueue interface。
- worker integration test：enqueue 後 mock worker 可消費 job。
- error test：enqueue exception 轉成穩定錯誤或 failed job。

**相依任務**
GS-P2-006, GS-P3-001, GS-P3-002, GS-P2-010

**風險與注意事項**
- 此 ticket 是 API 與 worker 的關鍵銜接點；不可把 pipeline 執行塞回 API request。

## Phase 完成標準

- Upload 後可 enqueue job。
- Worker 可消費 job 並更新 stage / progress。
- 失敗、timeout、retry 會轉成 failed 狀態。
- Worker log 可追蹤 job id 與 stage。
