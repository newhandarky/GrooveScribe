# GrooveScribe V1 Release Runbook

本 runbook 是 local-first V1 release gate 的重跑流程。它不啟用 cloud / SaaS，不要求 Tauri / Electron，不把 true-AI 或 PDF renderer 放進一般 CI 必跑。

若要跑一次使用者流程，先看 `docs/V1_Local_Quickstart.md`；本文件聚焦 release sign-off 與 evidence。

## Release candidate 順序

RC sign-off 建議順序：

```bash
npm run check:local
npm run test:e2e
backend/.venv/bin/python scripts/export_review_packet.py --help
.venv-ai/bin/python scripts/run_v1_release_gate.py
.venv-ai/bin/python scripts/generate_v1_release_evidence.py \
  --output-dir /tmp/groovescribe-v1-release-evidence
.venv-ai/bin/python scripts/run_v1_rc_pilot.py \
  --output-dir /tmp/groovescribe-v1-rc-pilot
.venv-ai/bin/python scripts/check_v1_rc_handoff.py \
  /tmp/groovescribe-v1-rc-pilot/rc_manifest.json
git status --short --branch
git diff --check
```

`npm run dev:local` 是手動 localhost 驗證用的長駐程序，不放進 deterministic release gate。release gate 會執行 setup doctor，但會跳過 8000 / 5173 port availability，避免 reviewer 已開著本機服務時誤傷 sign-off。

## 預設 release gate

首次跑 browser smoke 前安裝 Chromium cache：

```bash
npx playwright install chromium
```

重跑 deterministic release gate：

```bash
.venv-ai/bin/python scripts/run_v1_release_gate.py
```

若需要保存 report，請寫到 `/tmp` 或其他 repo 外位置：

```bash
.venv-ai/bin/python scripts/run_v1_release_gate.py \
  --output /tmp/groovescribe-v1-release-gate/report.json
```

report 會包含 command status、local setup doctor、artifact hygiene、redaction、manual eval、browser smoke、cleanup dry-run 與 true-AI opt-in 狀態。預設 true-AI 是 `skipped_opt_in`。

產生 repo 外 release evidence：

```bash
.venv-ai/bin/python scripts/generate_v1_release_evidence.py \
  --output-dir /tmp/groovescribe-v1-release-evidence
```

輸出：

- `/tmp/groovescribe-v1-release-evidence/evidence.json`
- `/tmp/groovescribe-v1-release-evidence/evidence.md`

evidence 會彙整 release gate、local setup、runtime readiness、manual eval、browser smoke、cleanup/reset dry-run、artifact hygiene 與 true-AI opt-in 狀態。若已先保存 gate report，也可重用：

```bash
.venv-ai/bin/python scripts/generate_v1_release_evidence.py \
  --gate-report /tmp/groovescribe-v1-release-gate/report.json \
  --output-dir /tmp/groovescribe-v1-release-evidence
```

`evidence.status=passed` 才可視為 deterministic V1 sign-off 通過。true-AI 未啟用時應顯示 `skipped_opt_in`，不是一般 release blocker。

## RC pilot handoff

最終 RC 交接可用單一 runner 產生 repo 外 handoff bundle：

```bash
.venv-ai/bin/python scripts/run_v1_rc_pilot.py \
  --output-dir /tmp/groovescribe-v1-rc-pilot
```

輸出：

- `/tmp/groovescribe-v1-rc-pilot/rc_manifest.json`
- `/tmp/groovescribe-v1-rc-pilot/rc_handoff.md`
- `/tmp/groovescribe-v1-rc-pilot/release_gate_report.json`
- `/tmp/groovescribe-v1-rc-pilot/release_evidence/evidence.json`
- `/tmp/groovescribe-v1-rc-pilot/release_evidence/evidence.md`

交接包驗證：

```bash
.venv-ai/bin/python scripts/check_v1_rc_handoff.py \
  /tmp/groovescribe-v1-rc-pilot/rc_manifest.json
```

若要把 completed job 的 review packet 一起納入交接包：

```bash
.venv-ai/bin/python scripts/run_v1_rc_pilot.py \
  --output-dir /tmp/groovescribe-v1-rc-pilot \
  --review-job-id <job_id>
```

`--review-job-id` 是 optional；job 不存在或尚未 completed 時，RC runner 只會記錄 `skipped_or_unavailable`，不會輸出本機路徑或 traceback。true-AI 仍只有在 `--include-true-ai` 時 opt-in。

## Local job workflow gate

V1 localhost UI 應可在本機完成：

- 上傳音檔並進入 queued / processing / completed。
- 在「近期任務」看到最近 job summary，並可回到 active result。
- 對 `failed` / `interrupted` job 使用 retry，對 `completed` job 使用 rerun；retry 會建立新 job，不覆寫舊 job、不刪舊 artifacts。
- 在 Runtime / Local data 區看到 public-safe dry-run 摘要；UI 不提供刪除 storage 或 DB 的動作。

Focused backend gate：

```bash
cd backend && .venv/bin/python -m pytest tests/test_job_history_and_retry_api.py tests/test_local_job_recovery.py
```

Focused frontend/browser gate：

```bash
npm --prefix frontend run test -- App.test.tsx
npm run test:e2e
```

手動 smoke 可依 `docs/V1_Local_Quickstart.md` 啟動 backend / frontend，使用 synthetic fixture 或授權音檔確認：

- Runtime 區 mock pipeline ready。
- Upload 可建立 queued job。
- Result 可顯示 MIDI / MusicXML download。
- Result 可顯示 Review packet JSON / ZIP handoff actions。
- MusicXML preview 或 fallback 可見。
- PDF failed / unavailable 顯示 optional。
- History 可回到 completed job，failed/interrupted 可 retry。

若 backend 尚未啟動，frontend Runtime 區會提示先執行 `npm run dev:local` 或 `npm run check:local`。

## Review packet handoff

Completed job 應可取得：

- `GET /api/v1/transcriptions/{job_id}/review-packet`
- `GET /api/v1/transcriptions/{job_id}/download/review-packet`

review packet 只包含 public-safe 摘要、quality diagnostics、validation、review checklist、manual eval seed 與可用 artifacts。ZIP entry 固定為 `review_packet.json`、`review_notes.md`、`drums.mid`、`score.musicxml`、`score.pdf`；PDF 不可用時不阻塞 ZIP 產生。

CLI export 必須寫到 repo 外：

```bash
backend/.venv/bin/python scripts/export_review_packet.py \
  --job-id <job_id> \
  --output-dir /tmp/groovescribe-review-packet \
  --zip
```

不得提交 generated review packet、ZIP 或任何本機 artifact。

## Opt-in true-AI

只有 runtime 已準備好時才跑：

```bash
RUN_TRUE_AI_SMOKE=1 .venv-ai/bin/python -m pytest tests/pipeline -k true_ai_smoke
RUN_TRUE_AI_SMOKE=1 backend/.venv/bin/python -m pytest backend/tests/test_pipeline_service_true_ai_smoke.py
.venv-ai/bin/python scripts/run_v1_release_gate.py --include-true-ai
```

true-AI degraded 時應保存 blocked reason，不填假 manual eval 分數。

## Artifact hygiene

release 前確認：

```bash
git status --short --branch
git diff --check
```

不得提交 `frontend/dist`、`storage/`、`backend/storage/`、`worker/storage/`、SQLite/DB、tmp artifacts、`playwright-report/`、`test-results/`、`blob-report/`。

## Local cleanup / reset

只允許 dry-run：

```bash
.venv-ai/bin/python scripts/cleanup_storage.py
.venv-ai/bin/python scripts/plan_local_reset.py
```

`--execute` 目前必須拒絕；不得在 V1 release gate 自動刪除 storage 或 DB。

release evidence 中的 `cleanup_reset.cleanup.execute_supported=false` 與 `cleanup_reset.reset.execute_supported=false` 是 sign-off 必要條件。

## Sign-off hygiene

每次跑完 build、browser smoke 或 evidence 後確認：

```bash
git status --short --branch
git diff --check
```

若本機產生 `frontend/dist`、`test-results`、`playwright-report`、`blob-report`，只能清理這些 generated outputs；不得刪除使用者本機 `storage/` 或 SQLite/DB。
