# GrooveScribe

GrooveScribe 是一個 MVP 專案，目標是讓使用者上傳單首 MP3 / WAV 音檔，透過背景 AI pipeline 產生基本鼓 MIDI、MusicXML、PDF 與網頁預覽。

目前狀態：專案骨架與規劃文件已建立，已開始實作 Phase 1 / Phase 2 的基礎骨架與 ffmpeg 音訊標準化。尚未整合 Demucs、ADTOF-pytorch、資料庫、Queue 與前端流程。

## 專案結構

```text
frontend/     Web app，上傳頁、結果頁、譜面預覽
backend/      FastAPI API server，負責 upload/status/result/download API
worker/       Background worker，負責 queue task 與 pipeline orchestration
ai_pipeline/  音訊處理、Demucs / ADTOF adapter、MIDI / notation modules
storage/      本地 artifacts 儲存目錄，未來可替換為 S3-compatible storage
tests/        跨模組測試、pipeline fixtures、E2E、人工評估
scripts/      本地開發與 pipeline POC scripts
infra/        Docker、compose、env、部署設定
docs/         Level 1 / 2 / 3 專案文件
```

## 開發原則

- API request 不執行 ffmpeg、Demucs、ADTOF-pytorch 或長時間音訊處理。
- 長任務一律由 background worker 執行。
- AI 模型透過 interface / adapter 整合，不與業務邏輯強耦合。
- 檔案存取透過 Storage Adapter，MVP 使用 local filesystem，保留 S3-compatible storage 擴充性。
- 第一版只支援單首音檔，不做多人協作、不做即時轉譜。

## 文件入口

- `docs/專案總覽.md`
- `docs/02_功能細部設計/README.md`
- `docs/03_工程實作任務/README.md`
- `docs/03_工程實作任務/MVP_Ticket總表.md`
- `ai_pipeline/RUNTIME.md`

## 本地服務

目前 `docker-compose.yml` 只提供 Postgres、Redis 與 local storage volume，供後續 backend / worker 開發使用。

```bash
docker compose up -d postgres redis
```

套件尚未安裝。正式開發時請依各子目錄的 `pyproject.toml` 或 `package.json` 建立環境。

## 目前可用指令

```bash
python -m compileall backend/app ai_pipeline worker/app scripts
PYTHONPATH=. python scripts/run_local_pipeline.py --output-dir storage/local/jobs/dev-smoke
PYTHONPATH=. python scripts/run_normalize_audio.py --input /path/to/audio.wav --output-dir /tmp/groovescribe-normalized
```

也提供 `Makefile` 包裝常用指令；若本機 `make` 環境不可用，直接執行上方 Python 指令即可。

`backend-test` 需要先安裝 backend dev dependencies，包含 `fastapi`、`pytest`、`httpx`。
