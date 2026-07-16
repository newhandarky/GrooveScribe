# Tests

測試目錄依 Level 3 規劃拆分：

- `unit/`：純邏輯單元測試
- `integration/`：API、database、queue、storage 整合測試
- `pipeline/`：pipeline fast / slow fixture tests
- `e2e/`：瀏覽器端 smoke tests
- `manual_eval/`：人工準確度評估表與結果

## Fixture 與人工評估

- `pipeline/fixtures/`：Phase 1 pipeline smoke test 使用的合成音檔與 manifest。
- `manual_eval/manual_eval_template.csv`：人工準確度與可用性評估表。
- `manual_eval/2026-06-30_true_ai_fixture_eval.csv`：目前真 Demucs + ADTOF generated fixture smoke 的人工評估結果；記錄為低品質，不代表轉譜準確度達標。

重新產生合成 fixture：

```bash
export PYTHON="$(pwd)/.venv-ai/bin/python"
PYTHONPATH=. "$PYTHON" scripts/generate_test_fixtures.py
```

使用 fixture 跑 local runner smoke：

```bash
export PYTHON="$(pwd)/.venv-ai/bin/python"
PYTHONPATH=. "$PYTHON" scripts/run_local_pipeline.py --input tests/pipeline/fixtures/audio/synthetic_clean_drum_pattern.wav --output-dir /tmp/groovescribe-fixture-run --mock-ai
```

真 AI fixture smoke 需先通過 runtime gate：

```bash
export PYTHON="$(pwd)/.venv-ai/bin/python"
export GROOVESCRIBE_ADTOF_COMMAND_TEMPLATE="$(pwd)/.venv-ai/bin/adtof --audio {input} --out {output} --device {device} --threshold {threshold}"
export GROOVESCRIBE_ADTOF_VERIFY_INPUT="/tmp/groovescribe-stems/drums.wav"
PYTHONPATH=. "$PYTHON" scripts/check_ai_runtime.py
PYTHONPATH=. "$PYTHON" scripts/run_local_pipeline.py --input tests/pipeline/fixtures/audio/synthetic_clean_drum_pattern.wav --output-dir /tmp/groovescribe-true-ai-run --demucs-device cpu --adtof-command-template "$GROOVESCRIBE_ADTOF_COMMAND_TEMPLATE" --adtof-device cpu --adtof-threshold 0.5
```

建立 true-AI artifact inspection baseline：

```bash
PYTHONPATH=. "$PYTHON" scripts/run_true_ai_smoke_baseline.py \
  --input tests/pipeline/fixtures/audio/synthetic_clean_drum_pattern.wav \
  --output-root /tmp/groovescribe-true-ai-baseline \
  --demucs-device cpu \
  --adtof-command-template "$GROOVESCRIBE_ADTOF_COMMAND_TEMPLATE" \
  --adtof-device cpu \
  --adtof-threshold 0.5
```

若 Demucs 或 ADTOF runtime 尚未 ready，保留 `manual_eval/manual_eval_template.csv`，不要填入假結果。
可保存 `baseline.json` 的 `status=blocked` 與 `blocked_reason`，等 runtime ready 後再填分數。

## Browser Smoke / Visual QA

V1 mock browser smoke 使用 Playwright 啟動 localhost frontend，並在測試內 mock `/api/v1/*` response；不啟動 true-AI、不依賴 PDF renderer，也不寫入 repo-local storage / SQLite。

首次執行或 Chromium browser cache 不存在時：

```bash
npx playwright install chromium
```

重跑 browser smoke：

```bash
npm run test:e2e
```

此 gate 覆蓋 desktop / mobile viewport、upload -> completed -> result page、MIDI / MusicXML download 可見、MusicXML preview/fallback 可見、PDF optional unavailable / failed 狀態，以及 rendered page 不暴露本機路徑、traceback、stdout/stderr、raw command 或 `command_template`。

browser smoke 也覆蓋 local-first workflow：近期任務顯示、local data dry-run summary、failed/interrupted retry 建立新 job、completed result 顯示 review packet JSON / ZIP handoff actions。這些路徑使用 mocked API，不寫入 repo-local storage / SQLite。

手動 localhost smoke 請依 `docs/V1_Local_Quickstart.md` 啟動 backend / frontend。手動紀錄不提交 screenshots、Playwright reports 或 generated evidence。

## Local Job History / Retry Tests

Backend focused gate：

```bash
cd backend && .venv/bin/python -m pytest tests/test_job_history_and_retry_api.py
```

Frontend focused gate：

```bash
npm --prefix frontend run test -- App.test.tsx frontend/src/services/api.test.ts
```

驗收重點：

- `GET /api/v1/transcriptions` 只回傳 summary，不含 storage key、本機路徑或 raw pipeline log。
- `POST /api/v1/transcriptions/{job_id}/retry` 僅允許 failed / interrupted / completed；active job 回 409。
- retry 建立新 queued job，不改舊 job 狀態，不刪 artifact。
- `GET /api/v1/local-data/summary` 是 dry-run visibility only，不提供刪檔 API。

## V1 Release Gate

檢查 localhost 啟動前置條件：

```bash
npm run check:local
```

預設 release gate 聚合 backend targeted tests、pipeline fast tests、frontend test/lint/build、browser smoke、manual eval CSV validation 與 cleanup dry-run：

```bash
.venv-ai/bin/python scripts/run_v1_release_gate.py
```

產生 V1 release evidence：

```bash
.venv-ai/bin/python scripts/generate_v1_release_evidence.py \
  --output-dir /tmp/groovescribe-v1-release-evidence
```

此 evidence 會輸出 repo 外 `evidence.json` 與 `evidence.md`，彙整 release gate、runtime readiness、manual eval、browser smoke、cleanup/reset dry-run、artifact hygiene 與 true-AI opt-in 狀態。測試覆蓋：
release gate 也會執行 `scripts/check_v1_local_setup.py --skip-port-check`；`scripts/run_v1_local_dev.py` 是手動長駐 launcher，不進 deterministic gate。手動 `npm run check:local` 預設仍會檢查 8000 / 5173 port availability。

```bash
.venv-ai/bin/python -m pytest tests/pipeline/test_release_gate_scripts.py
.venv-ai/bin/python -m pytest tests/pipeline/test_local_launch_scripts.py
.venv-ai/bin/python -m pytest tests/pipeline/test_review_packet_export.py
.venv-ai/bin/python -m pytest tests/pipeline/test_rc_pilot_handoff.py
```

Review packet CLI 可單獨檢查：

```bash
backend/.venv/bin/python scripts/export_review_packet.py --help
```

實際匯出必須指定 repo 外 output dir，例如 `/tmp/groovescribe-review-packet`；不要提交 generated JSON、Markdown、ZIP 或 artifacts。

manual eval CSV 可單獨驗證：

```bash
.venv-ai/bin/python scripts/check_manual_eval_gate.py
```

true-AI 仍是 opt-in；不要放進一般 CI 必跑，也不要提交 `frontend/dist`、`storage/`、SQLite/DB、tmp 或 Playwright report artifacts。

## V1 True-AI Real Audio Pilot

true-AI runtime setup focused tests：

```bash
.venv-ai/bin/python -m pytest tests/pipeline/test_true_ai_runtime_real_audio_pilot.py tests/pipeline/test_local_launch_scripts.py
```

本機 true-AI doctor：

```bash
npm run check:true-ai
```

真實音檔 pilot：

```bash
.venv-ai/bin/python scripts/run_v1_real_audio_pilot.py \
  --input /path/to/your-authorized-audio.wav \
  --output-dir /tmp/groovescribe-v1-real-audio-pilot
```

pilot 使用 true-AI opt-in，不進一般 CI 必跑。輸出必須在 repo 外；不得提交真實音檔、pilot reports、review packet、storage、DB、tmp、`frontend/dist` 或 Playwright reports。

## V1 RC Pilot / Handoff

最終 RC 交接包可重跑：

```bash
.venv-ai/bin/python scripts/run_v1_rc_pilot.py \
  --output-dir /tmp/groovescribe-v1-rc-pilot
.venv-ai/bin/python scripts/check_v1_rc_handoff.py \
  /tmp/groovescribe-v1-rc-pilot/rc_manifest.json
```

Focused tests：

```bash
.venv-ai/bin/python -m pytest tests/pipeline/test_rc_pilot_handoff.py
```

RC pilot 會呼叫 deterministic release gate 並輸出 repo 外 `rc_manifest.json` / `rc_handoff.md`。測試使用 mocked command runner，不會在 unit test 內真跑完整 gate。不得提交 generated RC outputs、evidence、review packet、storage、DB、tmp、`frontend/dist` 或 Playwright reports。

## V1 Product Pilot

Product pilot 用來驗證功能流程是否真的可用，不是 release/tag gate：

```bash
.venv-ai/bin/python scripts/run_v1_product_pilot.py \
  --output-dir /tmp/groovescribe-v1-product-pilot
```

Focused tests：

```bash
.venv-ai/bin/python -m pytest tests/pipeline/test_product_pilot_runner.py
npm run test:e2e
```

預設 product pilot 會跑 browser e2e，覆蓋 upload -> completed result、review packet、MIDI/MusicXML links、PDF optional status、job history、completed rerun、failed/interrupted retry 與 local data dry-run visibility。輸出必須在 repo 外；不得提交 product pilot reports、storage、DB、tmp、`frontend/dist` 或 Playwright reports。

## V1 Final Tag Prep

tag 前最小驗證：

```bash
git status --short --branch
git diff --check
.venv-ai/bin/python scripts/run_v1_rc_pilot.py --output-dir /tmp/groovescribe-v1-rc-pilot
.venv-ai/bin/python scripts/check_v1_rc_handoff.py /tmp/groovescribe-v1-rc-pilot/rc_manifest.json
rg -n "/Users/|/tmp/|/private/tmp/|/var/folders/|Traceback|stdout|stderr|raw command|command_template|output_tail|diagnostic_tail" /tmp/groovescribe-v1-rc-pilot
```

若需要 broader confidence：

```bash
.venv-ai/bin/python -m pytest tests/pipeline/test_rc_pilot_handoff.py tests/pipeline/test_release_gate_scripts.py
npm run test:e2e
```

`RUN_TRUE_AI_SMOKE=1` 仍是 opt-in，不是一般 tag blocker。PDF renderer 仍是 optional，不是一般 tag blocker。
