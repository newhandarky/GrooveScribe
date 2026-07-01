# GrooveScribe

GrooveScribe 是一個 MVP 專案，目標是讓使用者上傳單首 MP3 / WAV 音檔，透過背景 AI pipeline 產生基本鼓 MIDI、MusicXML、PDF 與網頁預覽。

目前狀態：Phase 1 runtime POC 已收尾；ffmpeg preprocessing、Demucs/ADTOF adapter 邊界、MIDI post-processing、MusicXML/PDF generation、mock local runner 與 fixture tests 已建立。Phase 1 已在獨立 `.venv-ai` 內完成 generated synthetic fixtures 與授權真實鼓聲 fixture 的真 Demucs + ADTOF 非 mock smoke，並產出 MIDI、MusicXML 與 PDF artifact；PDF smoke 目前為 `completed_with_warning`，因 MuseScore CLI 可能在產生非空 PDF 後以非零狀態結束。ADTOF 品質限制仍保留：真實音檔 kick/snare 改善，但 hi-hat recall、更多授權音檔與 ground-truth/manual eval criteria 留待後續品質驗證。backend API、database model、storage adapter、Celery enqueue 與 worker mock pipeline 也已有測試覆蓋；前端仍只有 scaffold。

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
export BACKEND_PYTHON="$(pwd)/backend/.venv/bin/python"
export AI_PYTHON="$(pwd)/.venv-ai/bin/python"
"$BACKEND_PYTHON" -m compileall backend/app ai_pipeline worker/app scripts
PYTHONPATH=. "$AI_PYTHON" scripts/check_ai_runtime.py
PYTHONPATH=. "$AI_PYTHON" scripts/run_local_pipeline.py --dry-run --output-dir storage/local/jobs/dev-smoke
PYTHONPATH=. "$AI_PYTHON" scripts/run_local_pipeline.py --input tests/pipeline/fixtures/audio/synthetic_clean_drum_pattern.wav --output-dir /tmp/groovescribe-fixture-run --mock-ai
PYTHONPATH=. "$AI_PYTHON" scripts/run_normalize_audio.py --input /path/to/audio.wav --output-dir /tmp/groovescribe-normalized
```

也提供 `Makefile` 包裝常用指令；若本機 `make` 環境不可用，直接執行上方 Python 指令即可。

`backend-test` 需要先安裝 backend dev dependencies，包含 `fastapi`、`pytest`、`httpx`。

真 AI local pipeline 使用獨立 `.venv-ai`；命令、版本、artifacts 與限制記錄於 `ai_pipeline/RUNTIME.md`。
