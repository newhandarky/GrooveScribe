# Phase 8：部署與環境設定任務

> Level 3 工程實作任務文件。本文只拆解開發 ticket，不取代 Level 1 / Level 2 規格。

## Phase 目標

建立本地與 staging 可重現的部署環境，包含 backend、worker、frontend、Redis、Postgres、local storage volume 與 GPU worker 注意事項。

## 前置條件

- Phase 2-6 主要服務可本機啟動。
- 已知道 Demucs / ADTOF runtime 對 CPU/GPU 的需求。

- `GS-P8-003`、`GS-P8-004`、`GS-P8-005` 可提前於 Phase 7 前完成，供 integration / E2E 測試使用。

## 需參考的 Level 1 / Level 2 文件

- Level 1：技術選型.md
- Level 1：專案目錄結構.md
- Level 1：開發計畫.md
- Level 2：檔案儲存與Artifact規格.md
- Level 2：背景任務與Job狀態規格.md

## 任務清單

- `GS-P8-001`：建立 Dockerfile
- `GS-P8-002`：建立 docker-compose.yml
- `GS-P8-003`：建立 backend / worker / frontend env config
- `GS-P8-004`：建立 local storage volume
- `GS-P8-005`：建立 Redis / Postgres service
- `GS-P8-006`：建立 GPU worker 部署注意事項
- `GS-P8-007`：建立 staging deployment checklist

> Phase 8 開工順序提醒：`GS-P8-003`、`GS-P8-004`、`GS-P8-005` 應先於 `GS-P8-002` 完成，讓 docker-compose 可以引用明確 env、storage volume、Redis / Postgres 設定。

## Ticket 詳細內容

### GS-P8-001 — 建立 Dockerfile

**Ticket ID**
GS-P8-001

**Ticket 名稱**
建立 Dockerfile

**背景與目的**
建立 backend、worker、frontend 的 Dockerfile 或分層 image 策略。

**實作範圍**
- 建立 backend Dockerfile。
- 建立 worker Dockerfile，包含 ffmpeg 與 AI runtime 需求說明。
- 建立 frontend Dockerfile。
- 處理 Python/Node dependency cache。

**不包含範圍**
- 不做 production Kubernetes。
- 不最佳化 image 到極致。

**主要修改位置或建議目錄**
- infra/docker/
- backend/
- worker/
- frontend/

**輸入**
- 服務依賴。
- runtime 需求。

**輸出**
- Docker images。

**API / Data Model / Storage 關聯**
- Worker image 必須可執行 ffmpeg；Demucs/ADTOF runtime 可在 GPU image 說明。

**驗收標準**
- 三個 image 可 build。

**測試要求**
- docker build tests。

**相依任務**
GS-P2-001, GS-P3-001, GS-P5-001, GS-P4-003, GS-P4-005

**風險與注意事項**
- 保持 MVP 範圍，避免順手實作多人協作、即時轉譜或線上修譜。

### GS-P8-002 — 建立 docker-compose.yml

**Ticket ID**
GS-P8-002

**Ticket 名稱**
建立 docker-compose.yml

**背景與目的**
建立本地一鍵啟動 frontend、backend、worker、redis、postgres、storage volume 的 compose。

**實作範圍**
- 定義 services。
- 設定 ports、env、depends_on。
- 掛載 local storage volume。
- 提供啟動與關閉指令。

**不包含範圍**
- 不做 production compose。
- 不處理 autoscaling。

**主要修改位置或建議目錄**
- docker-compose.yml
- infra/compose/

**輸入**
- Docker images。
- env config。

**輸出**
- 可啟動完整本地 stack。

**API / Data Model / Storage 關聯**
- Services：frontend/backend/worker/redis/postgres/storage。

**驗收標準**
- compose up 後 health check 通過。
- API 可連 database/redis。

**測試要求**
- compose smoke test。

**相依任務**
GS-P8-001, GS-P8-003, GS-P8-004, GS-P8-005

**風險與注意事項**
- 保持 MVP 範圍，避免順手實作多人協作、即時轉譜或線上修譜。

### GS-P8-003 — 建立 backend / worker / frontend env config

**Ticket ID**
GS-P8-003

**Ticket 名稱**
建立 backend / worker / frontend env config

**背景與目的**
定義各服務必要環境變數與範例檔，避免隱性本機設定。

**實作範圍**
- 建立 `.env.example`。
- 定義 DATABASE_URL、REDIS_URL、STORAGE_ROOT、API_BASE_URL、WORKER_CONCURRENCY、PIPELINE_VERSION。
- 分開 backend、worker、frontend 所需 env。

**不包含範圍**
- 不提交真 secrets。

**主要修改位置或建議目錄**
- infra/env/
- .env.example
- backend/app/core/config.py
- frontend/src/config/

**輸入**
- 服務設定需求。

**輸出**
- env example 與 config loader。

**API / Data Model / Storage 關聯**
- Storage root、database、redis、API base URL。

**驗收標準**
- 新工程師可依 example 建立本地 env。
- 缺必要 env 有清楚錯誤。

**測試要求**
- config unit tests。

**相依任務**
GS-P2-001, GS-P3-001, GS-P5-001

**風險與注意事項**
- 保持 MVP 範圍，避免順手實作多人協作、即時轉譜或線上修譜。

### GS-P8-004 — 建立 local storage volume

**Ticket ID**
GS-P8-004

**Ticket 名稱**
建立 local storage volume

**背景與目的**
定義本地檔案儲存 volume 與目錄權限，支援 upload、worker、download 共享 artifacts。

**實作範圍**
- 在 compose 掛載 storage volume。
- 建立 `storage/local/jobs` 結構。
- 確認 backend 與 worker 使用同一 root。
- 避免 storage 檔案被 commit。

**不包含範圍**
- 不做 S3。
- 不做 lifecycle cleanup。

**主要修改位置或建議目錄**
- storage/
- docker-compose.yml
- .gitignore

**輸入**
- STORAGE_ROOT。

**輸出**
- local storage volume。

**API / Data Model / Storage 關聯**
- Storage key 對應 local filesystem；API 不暴露路徑。

**驗收標準**
- backend upload 後 worker 可讀同一檔案。
- download API 可讀 worker 輸出。

**測試要求**
- integration smoke test：shared volume。

**相依任務**
GS-P2-005, GS-P8-003

**風險與注意事項**
- 保持 MVP 範圍，避免順手實作多人協作、即時轉譜或線上修譜。

### GS-P8-005 — 建立 Redis / Postgres service

**Ticket ID**
GS-P8-005

**Ticket 名稱**
建立 Redis / Postgres service

**背景與目的**
在 compose 中加入 Redis 與 Postgres，並設定健康檢查與資料 volume。

**實作範圍**
- 設定 postgres image、database、user、password env。
- 設定 redis image。
- 建立 healthcheck。
- 設定 persistent volume for postgres。

**不包含範圍**
- 不做 managed DB。
- 不做 backup 策略。

**主要修改位置或建議目錄**
- docker-compose.yml
- infra/compose/

**輸入**
- DB/Redis env。

**輸出**
- 可用 Redis / Postgres services。

**API / Data Model / Storage 關聯**
- Data：PostgreSQL schema；Queue：Redis broker。

**驗收標準**
- backend migration 可連 Postgres。
- worker 可連 Redis。

**測試要求**
- compose healthcheck。
- migration smoke test。

**相依任務**
GS-P8-003

**風險與注意事項**
- 保持 MVP 範圍，避免順手實作多人協作、即時轉譜或線上修譜。

### GS-P8-006 — 建立 GPU worker 部署注意事項

**Ticket ID**
GS-P8-006

**Ticket 名稱**
建立 GPU worker 部署注意事項

**背景與目的**
文件化 GPU worker 的部署風險與設定，避免 MVP 在 CPU/GPU 環境差異下不可預期。

**實作範圍**
- 說明 CUDA / PyTorch / Demucs / ADTOF 版本注意事項。
- 建議 GPU worker concurrency=1。
- 說明 CPU fallback 成本與速度。
- 列出模型檔與 cache 位置。

**不包含範圍**
- 不實作 GPU autoscaling。
- 不購買或配置雲端 GPU。

**主要修改位置或建議目錄**
- docs/03_工程實作任務/
- infra/docker/worker.Dockerfile notes

**輸入**
- 模型 runtime 資訊。

**輸出**
- GPU worker deployment notes。

**API / Data Model / Storage 關聯**
- Worker：Demucs/ADTOF runtime；Storage：model cache 可獨立於 artifacts。

**驗收標準**
- 工程師知道 staging GPU worker 怎麼配置。
- 風險與限制明確。

**測試要求**
- 文件 review。
- 手動驗證 GPU/CPU 啟動命令。

**相依任務**
GS-P4-003, GS-P4-005, GS-P8-001

**風險與注意事項**
- 保持 MVP 範圍，避免順手實作多人協作、即時轉譜或線上修譜。

### GS-P8-007 — 建立 staging deployment checklist

**Ticket ID**
GS-P8-007

**Ticket 名稱**
建立 staging deployment checklist

**背景與目的**
建立 staging 部署前後檢查表，確保可從瀏覽器完成端到端 MVP。

**實作範圍**
- 列出 build、migration、env、storage、queue、worker、frontend、test upload 檢查。
- 加入 rollback / log 檢查提示。
- 加入測試音檔端到端驗收。

**不包含範圍**
- 不做 production runbook。
- 不做監控 dashboard。

**主要修改位置或建議目錄**
- docs/03_工程實作任務/
- infra/

**輸入**
- 部署環境資訊。
- MVP 驗收 checklist。

**輸出**
- staging deployment checklist。

**API / Data Model / Storage 關聯**
- 涵蓋 API、DB、Redis、Storage、Worker、Frontend。

**驗收標準**
- 照 checklist 可完成 staging smoke test。

**測試要求**
- staging dry-run review。

**相依任務**
GS-P8-002, GS-P7-006

**風險與注意事項**
- 保持 MVP 範圍，避免順手實作多人協作、即時轉譜或線上修譜。

## Phase 完成標準

- Docker Compose 可啟動完整 MVP 服務。
- 環境變數與 storage volume 設定清楚。
- staging deployment checklist 可被工程師照表執行。
