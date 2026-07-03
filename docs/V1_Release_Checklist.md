# GrooveScribe Local-first V1 Release Checklist

本文定義 local-first V1 的驗收 gate。V1 不是只要「能跑通一次」，而是要能在本機重現、診斷、檢查 artifact，並清楚標示 true AI 與 PDF 的限制。

## Runtime Readiness

- [ ] `GET /api/v1/runtime/preflight` 回傳 `ready`、`degraded`、`not_ready` 或 `error`，不 crash。
- [ ] mock-ai ready 時，upload flow 可用。
- [ ] true AI 若尚未 ready，ADTOF diagnostics 有 structured `status_code`、summary、next steps。
- [ ] response 不暴露 `/Users/`、`/tmp/`、traceback、raw command secret。
- [ ] `.env.true-ai.example` 與 runtime guide 可讓開發者逐步修到 `true_ai_ready=true` 或取得明確 blocked reason。

## Mock Flow Gate

- [ ] Local backend 使用 SQLite + local queue + local filesystem storage。
- [ ] Local frontend 可開啟 localhost app。
- [ ] 上傳 WAV/MP3 後 job 可到 `completed`。
- [ ] Result 顯示 DrumTrack metadata、warnings、exports。
- [ ] MIDI、MusicXML 可下載。
- [ ] PDF available / failed / unavailable 狀態清楚；PDF 不阻塞 MIDI / MusicXML。

## True AI Opt-in Gate

- [ ] `GROOVESCRIBE_ADTOF_COMMAND_TEMPLATE` 已設定且包含 `{input}`、`{output}`。
- [ ] `GROOVESCRIBE_ADTOF_VERIFY_INPUT` 指向 Demucs 產出的 drums stem。
- [ ] `scripts/check_ai_runtime.py` 回 `runtime_checks.local_pipeline.true_ai_ready=true`。
- [ ] `RUN_TRUE_AI_SMOKE=1 backend/.venv/bin/python -m pytest backend/tests/test_pipeline_service_true_ai_smoke.py` 可完成或記錄 blocked reason。
- [ ] `RUN_TRUE_AI_SMOKE=1 .venv-ai/bin/python -m pytest tests/pipeline -k true_ai_smoke` 可完成或記錄 blocked reason。

## Artifact Quality Inspection

- [ ] `scripts/inspect_midi.py` 可讀 raw MIDI 與 processed MIDI。
- [ ] 記錄 raw note histogram、processed drum counts、event count。
- [ ] MusicXML 可 parse / 開啟。
- [ ] PDF 若產出，可開啟；若沒有，狀態是 optional failure。
- [ ] pipeline log 含 stage reports 且已 redacted。
- [ ] frontend result review 顯示 mock / true AI、stage summary、warnings、export 狀態。

## Local Reliability

- [ ] app restart 後遺留 `processing` job 會標成 `interrupted`。
- [ ] `queued/completed/failed/canceled` 不被 startup recovery 誤改。
- [ ] interrupted / failed job 在 UI 有下一步建議。
- [ ] `scripts/cleanup_storage.py` dry-run 不刪檔，且不越過 local storage root。
- [ ] README / runtime guide 說明 DB、artifacts、cleanup 與 reset 的本機資料位置。

## Manual Evaluation

- [ ] 至少一輪 mock-ai browser smoke 有記錄。
- [ ] 至少一輪 true-AI opt-in smoke 有 artifact inspection 記錄，或有明確 blocked reason。
- [ ] `tests/manual_eval` CSV 記錄 pipeline version、runtime version、artifact ref、reviewer。
- [ ] 若使用 repo 外授權音檔，記錄授權與不可提交原因。
- [ ] 評分不要求出版級；V1 目標是可檢查、可下載、可人工修正的鼓譜草稿。

## Non-goals For V1

- Cloud deployment / SaaS。
- Redis / Celery / PostgreSQL 作為 V1 預設主線。
- Tauri / Electron desktop shell 實作。
- true AI 作為一般 CI 必跑條件。
- PDF renderer 問題阻塞 MIDI / MusicXML 主流程。
