# GrooveScribe Local-first V1 Release Checklist

本文定義 local-first V1 的驗收 gate。V1 不是只要「能跑通一次」，而是要能在本機重現、診斷、檢查 artifact，並清楚標示 true AI 與 PDF 的限制。

## Runtime Readiness

- [x] `GET /api/v1/runtime/preflight` 回傳 `ready`、`degraded`、`not_ready` 或 `error`，不 crash。Evidence：`cd backend && .venv/bin/python -m pytest tests/test_runtime_preflight_api.py`。
- [x] mock-ai ready 時，upload flow 可用。Evidence：`npm run test:e2e` 與 `.venv-ai/bin/python scripts/generate_v1_release_evidence.py`。
- [x] true AI 若尚未 ready，ADTOF diagnostics 有 structured `status_code`、summary、next steps。Evidence：`.venv-ai/bin/python scripts/run_v1_release_gate.py`；true-AI 為 opt-in。
- [x] response 不暴露 `/Users/`、`/tmp/`、traceback、raw command secret。Evidence：release gate / evidence report 的 `redaction.status=passed`。
- [x] `.env.true-ai.example` 與 runtime guide 可讓開發者逐步修到 `true_ai_ready=true` 或取得明確 blocked reason。Evidence：runtime guide + true-AI opt-in baseline report。

## Mock Flow Gate

- [x] Local backend 使用 SQLite + local queue + local filesystem storage。
- [x] Local frontend 可開啟 localhost app。
- [x] `npm run check:local` 可檢查 V1 本機啟動條件，包含 venv、backend import、frontend dependencies、Playwright Chromium、port availability 與 artifact hygiene；report 不暴露本機絕對路徑或 raw diagnostics。
- [x] `npm run dev:local` 可同時啟動 backend / frontend 作為手動 localhost 驗證入口；此命令是長駐程序，不放進 deterministic release gate。
- [x] 上傳 WAV/MP3 後 job 可到 `completed`。
- [x] Result 顯示 DrumTrack metadata、warnings、exports。
- [x] MIDI、MusicXML 可下載。
- [x] Completed result 可提供 review packet JSON / ZIP，包含 public-safe quality diagnostics、validation、review checklist 與 manual eval seed。
- [x] Review packet ZIP 使用固定安全檔名；PDF unavailable 不阻塞 MIDI / MusicXML handoff。
- [x] PDF available / failed / unavailable 狀態清楚；PDF 不阻塞 MIDI / MusicXML。
- [x] Mock browser smoke 可重跑：`npm run test:e2e` 覆蓋 desktop / mobile localhost UI、upload -> completed -> result page、history、failed/interrupted retry、MIDI / MusicXML download、MusicXML preview/fallback 與 PDF optional unavailable / failed 狀態。
- [x] Deterministic API / component smoke 可重跑：`cd backend && .venv/bin/python -m pytest tests/test_transcription_api_integration.py tests/test_runtime_preflight_api.py tests/test_transcription_apis.py`、`npm --prefix frontend run test`。
- [x] Release gate orchestrator 可重跑：`.venv-ai/bin/python scripts/run_v1_release_gate.py`，包含 local setup doctor，report 不暴露本機路徑或 raw diagnostics。
- [x] Release evidence 可重跑：`.venv-ai/bin/python scripts/generate_v1_release_evidence.py --output-dir /tmp/groovescribe-v1-release-evidence`，JSON / Markdown 均寫在 repo 外，並彙整 local setup 狀態。

## True AI Opt-in Gate

true AI 是 opt-in，不是 deterministic release blocker。一般 sign-off 可接受 `skipped_opt_in`；若要驗證 true AI，需在該機器完成下列條件。

- [x] `.env.true-ai.example` 與 runtime guide 文件化 `GROOVESCRIBE_ADTOF_COMMAND_TEMPLATE`，且 template 必須包含 `{input}`、`{output}`。
- [x] runtime guide 文件化 `GROOVESCRIBE_ADTOF_VERIFY_INPUT` 必須指向 Demucs 產出的 drums stem。
- [x] `scripts/check_ai_runtime.py` 可回報 `runtime_checks.local_pipeline.true_ai_ready=true` 或可診斷 blocked reason。
- [x] `scripts/run_true_ai_smoke_baseline.py` 產出 baseline report v2；若 blocked，需包含 `status=blocked`、blocked reason、ADTOF `status_code`、`baseline:<run-id>` ref。
- [x] `RUN_TRUE_AI_SMOKE=1 backend/.venv/bin/python -m pytest backend/tests/test_pipeline_service_true_ai_smoke.py` 可完成或記錄 blocked reason。
- [x] `RUN_TRUE_AI_SMOKE=1 .venv-ai/bin/python -m pytest tests/pipeline -k true_ai_smoke` 可完成或記錄 blocked reason。

2026-07-03 baseline note：synthetic fixture true-AI baseline completed，MIDI / MusicXML available，PDF unavailable but optional；manual eval 記錄於 `tests/manual_eval/2026-07-03_true_ai_baseline_eval.csv`。品質仍偏低，主要 warning 為 `hihat_missing_likely` 與 `mostly_tom_output`。

## Artifact Quality Inspection

- [x] `scripts/inspect_midi.py` 可讀 raw MIDI 與 processed MIDI。
- [x] `scripts/inspect_pipeline_artifacts.py` 可合併 raw / processed MIDI inspection。
- [x] 記錄 raw note histogram、processed drum counts、event count。
- [x] pipeline log 與 result API 可暴露 `pipeline.quality`，包含 raw / processed event count、drum counts、duration / tempo / measure estimate 與 quality flags。
- [x] pipeline log 與 result API 可暴露 optional `pipeline.validation`，包含 MusicXML parseable 與 PDF optional/openable status。
- [x] MusicXML 可 parse / 開啟檢查；validation 失敗以 warning code 呈現，不暴露本機路徑。
- [x] PDF 若產出，可做 `%PDF` header 檢查；若沒有，狀態是 optional failure。
- [x] pipeline log 含 stage reports 且已 redacted。
- [x] frontend result review 顯示 mock / true AI、stage summary、warnings、quality flags、event counts、drum counts、MusicXML preview/fallback、validation 與 export 狀態。
- [x] frontend result review 顯示 review packet handoff actions，讓 reviewer 可下載 JSON / ZIP 進行人工修譜與評分。

## Local Reliability

- [x] app restart 後遺留 `processing` job 會標成 `interrupted`。
- [x] `queued/completed/failed/canceled` 不被 startup recovery 誤改。
- [x] `GET /api/v1/transcriptions` 可列出近期 job summary，不暴露 storage key、本機路徑或 raw pipeline log。
- [x] `POST /api/v1/transcriptions/{job_id}/retry` 可讓 `failed` / `interrupted` / `completed` 建立新 queued job；`queued` / `processing` 回 409。
- [x] interrupted / failed job 在 UI 有下一步建議與 retry action；completed job 可 rerun。
- [x] `GET /api/v1/local-data/summary` 只回傳 dry-run public-safe 統計；不提供刪檔 API。
- [x] `scripts/cleanup_storage.py` dry-run 不刪檔，且 report 含 storage root name、job dir count、orphan dirs、DB missing/unreadable/readable 狀態；`--execute` 繼續拒絕。
- [x] README / runtime guide 說明 DB、artifacts、cleanup 與 reset 的本機資料位置。Evidence：`README.md`、`docs/V1_Local_Quickstart.md`、`docs/V1_Release_Runbook.md` 與 `scripts/README.md`。
- [x] `scripts/plan_local_reset.py` 只輸出 dry-run reset plan；`--execute` 維持拒絕。Evidence：`.venv-ai/bin/python scripts/generate_v1_release_evidence.py` 的 `cleanup_reset.reset.execute_supported=false`。

## Manual Evaluation

- [x] 至少一輪 mock-ai browser smoke 有記錄；預設使用 Playwright mocked API，不啟動 true-AI，也不依賴 PDF renderer。Evidence：release evidence Markdown。
- [x] 至少一輪 true-AI opt-in smoke 有 artifact inspection 記錄，或有明確 blocked reason。
- [x] `tests/manual_eval` CSV 記錄 date、fixture、runtime mode、baseline report ref、pipeline/runtime version、event counts、drum counts、quality flags、artifact ref、reviewer。
- [x] `scripts/generate_manual_eval_row.py` 可從 completed / blocked `baseline.json` 產生 schema-compatible CSV row，且不輸出本機絕對路徑。
- [x] Review packet `manual_eval_seed` 與 CSV template 核心欄位對齊，但不自動填人工分數。
- [x] `scripts/check_manual_eval_gate.py` 可驗證 manual eval CSV schema、blocked/completed row contract 與 redaction。Evidence：`.venv-ai/bin/python -m pytest tests/pipeline/test_release_gate_scripts.py` 與 release evidence `manual_eval.status=passed`。
- [x] 若使用 repo 外授權音檔，記錄授權與不可提交原因。
- [x] 評分不要求出版級；V1 目標是可檢查、可下載、可人工修正的鼓譜草稿。

## Artifact / DB Hygiene

- [x] `git status --short` 不包含 `storage/`、SQLite/DB、`frontend/dist`、tmp artifacts。Evidence：release gate / evidence `artifact_hygiene.status=passed`。
- [x] `playwright-report/`、`test-results/`、`blob-report/` 只作為本機測試輸出，不提交。Evidence：release gate / evidence `generated_artifacts_present=[]`。
- [x] public API、frontend rendered HTML、baseline report、manual eval row 不含 `/Users/`、`/tmp/`、`/private/tmp/`、`/var/folders/`、`Traceback`、`stdout`、`stderr`、raw command 或 command template。
- [x] release gate report 與 release evidence 不含 `/Users/`、`/tmp/`、`/private/tmp/`、`/var/folders/`、`Traceback`、`stdout`、`stderr`、raw command 或 command template。
- [x] local setup doctor report 不含 `/Users/`、`/tmp/`、`/private/tmp/`、`/var/folders/`、`Traceback`、`stdout`、`stderr`、raw command 或 command template。
- [x] review packet API、ZIP manifest、CLI export 與 frontend rendered HTML 不含 `/Users/`、`/tmp/`、`/private/tmp/`、`/var/folders/`、`Traceback`、`stdout`、`stderr`、raw command 或 command template。

## Non-goals For V1

- Cloud deployment / SaaS。
- Redis / Celery / PostgreSQL 作為 V1 預設主線。
- Tauri / Electron desktop shell 實作。
- true AI 作為一般 CI 必跑條件。
- PDF renderer 問題阻塞 MIDI / MusicXML 主流程。
