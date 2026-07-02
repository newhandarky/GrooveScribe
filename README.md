# GrooveScribe

GrooveScribe 是一個 local-first 的完整 V1 產品，目標是在使用者自己的電腦上完成音訊轉鼓譜流程。使用者啟動本機服務後，透過瀏覽器開啟 `localhost` 介面，上傳單首 MP3 / WAV 音檔，系統在本機執行 ffmpeg、Demucs、ADTOF-pytorch、MIDI 後處理、MusicXML 與 PDF export，產生可預覽、可下載、可人工修正的鼓譜草稿。

V1 不以「先快速跑通 MVP」為目標，而是以 production-ready local-first app 為目標：安裝與啟動流程要可重現，任務狀態要可追蹤，失敗要可診斷，artifact 要可管理，輸出品質要有 fixture test 與人工評估支撐。

## V1 產品方向

- 介面型態：Local Web App。使用者在本機啟動 backend / frontend，再用瀏覽器操作。
- 前端：React + TypeScript，可使用 Vite 與 TanStack Query。
- 後端：本機 FastAPI service，負責 upload、job、status、result、download API。
- Pipeline：本機 Python AI runtime，執行 ffmpeg、Demucs、ADTOF、MIDI post-processing、MusicXML / PDF export。
- Database：V1 預設 SQLite，方便單機安裝、備份與除錯。
- Job system：V1 預設本機 job manager，不把 Redis / Celery 作為主線依賴。
- Storage：V1 預設本機 filesystem artifacts。
- 未來擴充：Tauri / Electron desktop shell、cloud sync、server deployment、S3-compatible storage、Redis / Celery worker、PostgreSQL 與 SaaS 化都保留為 optional future，不列入 V1 預設。

## 目前狀態

Phase 1 runtime POC 已收尾；ffmpeg preprocessing、Demucs / ADTOF adapter 邊界、MIDI post-processing、MusicXML / PDF generation、mock local runner 與 fixture tests 已建立。先前已在獨立 `.venv-ai` 內完成 generated synthetic fixtures 與授權真實鼓聲 fixture 的真 Demucs + ADTOF 非 mock smoke，並產出 MIDI、MusicXML 與 PDF artifact；PDF smoke 目前為 `completed_with_warning`，因 MuseScore CLI 可能在產生非空 PDF 後以非零狀態結束。

目前程式碼中也已有 FastAPI API、database model、storage adapter、Celery enqueue 與 worker mock pipeline 測試覆蓋。這些是既有工程資產；後續 V1 方向會把預設主線調整為 SQLite + 本機 job manager + local storage，Redis / Celery / PostgreSQL 則保留為未來 server mode 或 cloud mode 的可選能力。前端目前仍只有 scaffold，需要依 local-first V1 重新建完整操作介面。

## 專案結構

```text
frontend/     Local Web App，上傳頁、結果頁、譜面預覽與下載操作
backend/      本機 FastAPI service，負責 upload/status/result/download API
worker/       既有 worker / orchestration 實作；V1 需收斂成本機 job manager 主線
ai_pipeline/  音訊處理、Demucs / ADTOF adapter、MIDI / notation modules
storage/      本機 artifacts 儲存目錄
tests/        跨模組測試、pipeline fixtures、人工評估
scripts/      本地開發與 pipeline runtime scripts
infra/        optional deployment / packaging / environment references
docs/         產品、架構、規格、任務與決策文件
```

## 開發原則

- V1 預設在單機執行，不依賴雲端服務。
- API request 不直接執行長時間音訊處理；長任務交由本機 job manager 管理。
- AI 模型透過 interface / adapter 整合，不與 API 或資料模型強耦合。
- 檔案存取透過 storage adapter，V1 預設 local filesystem。
- Database 預設 SQLite，schema 與資料遷移需支援本機升級。
- 第一版只支援單首音檔，不做多人協作、不做 cloud sync、不做 SaaS 帳號系統。

## 文件入口

- `docs/專案總覽.md`
- `docs/產品完整度標準.md`
- `docs/系統架構.md`
- `docs/技術選型.md`
- `docs/架構決策/ADR-001-介面型態與執行模式.md`
- `docs/02_功能細部設計/README.md`
- `docs/03_工程實作任務/README.md`
- `docs/03_工程實作任務/V1_Ticket總表.md`
- `ai_pipeline/RUNTIME.md`

## 本地執行方向

V1 最終目標是一條本機啟動路徑：

```bash
# target shape, exact command may change during V1 implementation
groovescribe start
open http://localhost:5173
```

目前既有 `docker-compose.yml` 只提供 Postgres、Redis 與 local storage volume，屬於既有 server-style 開發輔助，不再是 V1 預設主線。後續應新增 SQLite + local job manager 的本機啟動流程，並將 Redis / Celery / PostgreSQL 標成 optional server mode。

## 目前可用指令

```bash
export BACKEND_PYTHON="$(pwd)/backend/.venv/bin/python"
export AI_PYTHON="$(pwd)/.venv-ai/bin/python"
"$BACKEND_PYTHON" -m compileall backend/app ai_pipeline worker/app scripts
PYTHONPATH=. "$AI_PYTHON" scripts/check_ai_runtime.py
PYTHONPATH=. "$AI_PYTHON" scripts/run_local_pipeline.py --dry-run --output-dir storage/local/jobs/dev-smoke
PYTHONPATH=. "$AI_PYTHON" scripts/run_local_pipeline.py --input tests/pipeline/fixtures/audio/synthetic_clean_drum_pattern.wav --output-dir /tmp/groovescribe-fixture-run --mock-ai
PYTHONPATH=. "$AI_PYTHON" scripts/run_normalize_audio.py --input /path/to/audio.wav --output-dir /tmp/groovescribe-normalized
```

`backend-test` 需要先安裝 backend dev dependencies，包含 `fastapi`、`pytest`、`httpx`。真 AI local pipeline 使用獨立 `.venv-ai`；命令、版本、artifacts 與限制記錄於 `ai_pipeline/RUNTIME.md`。
