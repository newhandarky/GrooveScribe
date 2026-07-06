# GrooveScribe V1 Local Quickstart

本文是使用者與 reviewer 跑一次 local-first V1 的最短流程。V1 預設使用 SQLite、local job queue、local filesystem artifacts 與 mock pipeline；true AI 是 opt-in，不是一般 release gate 必跑。

## 1. 檢查本機啟動條件

先在 repo root 執行 setup doctor：

```bash
npm run check:local
```

doctor 會檢查 Python venv、backend import、frontend dependencies、Playwright Chromium、runtime policy、預設 port 與 artifact hygiene。輸出是 public-safe JSON；若需要保存，請寫到 repo 外，例如：

```bash
.venv-ai/bin/python scripts/check_v1_local_setup.py \
  --output /tmp/groovescribe-v1-local-setup/setup.json
```

## 2. 啟動 Local V1

預設用單一 launcher 啟動 backend 與 frontend：

```bash
npm run dev:local
```

開啟：

```text
http://127.0.0.1:5173
```

Ctrl-C 會停止 backend / frontend 子程序。

若需要手動分開啟動，可使用：

```bash
cd backend
.venv/bin/python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Backend 預設使用：

- Database：`storage/local/groovescribe.db`
- Storage root：`storage/local`
- Job queue：local single-process queue
- PDF renderer：optional

另開一個 terminal：

```bash
npm --prefix frontend run dev
```

開啟：

```text
http://127.0.0.1:5173
```

Vite 會將 `/api/*` proxy 到 `http://127.0.0.1:8000`。

## 3. 跑一次 Mock Flow

1. 在 Runtime 區確認 `Mock pipeline` 是 `ready`。
2. true AI 若顯示 `not ready`，仍可繼續使用 mock flow。
3. 在 Upload 區選擇 MP3 或 WAV。
4. 點選「開始本機分析」。
5. 等待 job 從 `queued` / `processing` 到 `completed`。
6. 在結果區確認：
   - MIDI download 可見。
   - MusicXML download 可見。
   - MusicXML preview 或 fallback 可見。
   - PDF 若 failed / unavailable，會顯示 optional，不阻塞 MIDI / MusicXML。

## 4. 使用近期任務與 Retry

- 「近期任務」會列出最近 jobs。
- `failed` / `interrupted` 可按「重試」，系統會建立新 job，不覆寫舊 job。
- `completed` 可按「重新執行」，同樣建立新 job。
- 舊 artifacts 不會被 UI 刪除。

## 5. 本機資料與 Reset

Runtime / Local data 區只顯示 public-safe dry-run 統計：

- storage root name
- job dir count
- DB status
- orphan count

UI 不提供刪除資料功能。工程檢查請使用：

```bash
.venv-ai/bin/python scripts/cleanup_storage.py
.venv-ai/bin/python scripts/plan_local_reset.py
```

`--execute` 目前必須拒絕；V1 不自動刪除 storage 或 DB。

## 6. Release Sign-off

一般 deterministic gate：

```bash
.venv-ai/bin/python scripts/run_v1_release_gate.py
```

產生 repo 外 evidence：

```bash
.venv-ai/bin/python scripts/generate_v1_release_evidence.py \
  --output-dir /tmp/groovescribe-v1-release-evidence
```

輸出：

- `/tmp/groovescribe-v1-release-evidence/evidence.json`
- `/tmp/groovescribe-v1-release-evidence/evidence.md`

不要提交 generated evidence、`frontend/dist`、`storage/`、SQLite/DB、tmp 或 Playwright reports。

## 7. True AI Opt-in

true AI 需另外設定 Demucs / ADTOF runtime。流程見：

- `docs/本機AI Runtime診斷與True AI啟用指南.md`
- `.env.true-ai.example`

true AI degraded 時，請保存 blocked reason，不要填假 manual eval 分數。PDF renderer 仍是 optional，不是一般 sign-off blocker。
