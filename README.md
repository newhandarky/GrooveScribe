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

Local-first V1 主線已收斂到 SQLite + local job queue + local filesystem storage。FastAPI backend 已提供 runtime preflight、upload、job status、result、download、job history、retry/rerun 與 local data summary API；React localhost UI 已可上傳音檔、查看近期任務、追蹤 queued / processing / completed / failed / interrupted、重試或重新執行 job、預覽 MusicXML fallback、下載 MIDI / MusicXML，並清楚標示 PDF optional 狀態。

Release readiness 也已建立 deterministic gate：backend targeted tests、pipeline fast tests、frontend test/lint/build、Playwright desktop/mobile browser smoke、manual eval CSV gate、cleanup/reset dry-run、artifact hygiene 與 redaction matrix。`scripts/generate_v1_release_evidence.py` 可產生 repo 外 JSON / Markdown evidence，`scripts/run_v1_rc_pilot.py` 與 `scripts/check_v1_rc_handoff.py` 可產生並驗證 final RC handoff bundle。

true AI runtime 仍是 opt-in。若 Demucs / ADTOF 尚未 ready，V1 仍可使用 mock flow 完成 upload -> result -> download；true AI blocked reason 與 baseline 流程記錄於 runtime guide。

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

- `docs/V1_Local_Quickstart.md`
- `docs/V1_Release_Notes.md`
- `docs/V1_Release_Runbook.md`
- `docs/V1_Release_Checklist.md`
- `docs/V1_Tag_Prep_Checklist.md`
- `docs/V1_Release_Artifact_Index.md`
- `docs/專案總覽.md`
- `docs/產品完整度標準.md`
- `docs/系統架構.md`
- `docs/技術選型.md`
- `docs/架構決策/ADR-001-介面型態與執行模式.md`
- `docs/02_功能細部設計/README.md`
- `docs/03_工程實作任務/README.md`
- `docs/03_工程實作任務/V1_Ticket總表.md`
- `ai_pipeline/RUNTIME.md`

## 本地執行

```bash
npm run check:local
npm run dev:local
```

開啟：

```text
http://127.0.0.1:5173
```

完整流程見 `docs/V1_Local_Quickstart.md`。既有 `docker-compose.yml` 只提供 Postgres、Redis 與 local storage volume，屬於 optional server-style 開發輔助，不是 V1 預設主線。

## 目前可用指令

```bash
export BACKEND_PYTHON="$(pwd)/backend/.venv/bin/python"
export AI_PYTHON="$(pwd)/.venv-ai/bin/python"
"$BACKEND_PYTHON" -m compileall backend/app ai_pipeline worker/app scripts
PYTHONPATH=. "$AI_PYTHON" scripts/check_ai_runtime.py
npm run check:local
npm run dev:local
PYTHONPATH=. "$AI_PYTHON" scripts/run_local_pipeline.py --dry-run --output-dir storage/local/jobs/dev-smoke
PYTHONPATH=. "$AI_PYTHON" scripts/run_local_pipeline.py --input tests/pipeline/fixtures/audio/synthetic_clean_drum_pattern.wav --output-dir /tmp/groovescribe-fixture-run --mock-ai
PYTHONPATH=. "$AI_PYTHON" scripts/run_normalize_audio.py --input /path/to/audio.wav --output-dir /tmp/groovescribe-normalized
npm run test:e2e
PYTHONPATH=. "$AI_PYTHON" scripts/run_v1_release_gate.py
PYTHONPATH=. "$AI_PYTHON" scripts/generate_v1_release_evidence.py --output-dir /tmp/groovescribe-v1-release-evidence
PYTHONPATH=. "$AI_PYTHON" scripts/run_v1_rc_pilot.py --output-dir /tmp/groovescribe-v1-rc-pilot
PYTHONPATH=. "$AI_PYTHON" scripts/check_v1_rc_handoff.py /tmp/groovescribe-v1-rc-pilot/rc_manifest.json
```

`backend-test` 需要先安裝 backend dev dependencies，包含 `fastapi`、`pytest`、`httpx`。真 AI local pipeline 使用獨立 `.venv-ai`；命令、版本、artifacts 與限制記錄於 `ai_pipeline/RUNTIME.md` 與 `docs/本機AI Runtime診斷與True AI啟用指南.md`。V1 tag 前請看 `docs/V1_Tag_Prep_Checklist.md`。不要提交 `frontend/dist`、`storage/`、SQLite/DB、tmp、Playwright reports、release evidence、review packets 或 RC handoff outputs。
