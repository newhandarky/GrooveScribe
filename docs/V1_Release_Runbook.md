# GrooveScribe V1 Release Runbook

本 runbook 是 local-first V1 release gate 的重跑流程。它不啟用 cloud / SaaS，不要求 Tauri / Electron，不把 true-AI 或 PDF renderer 放進一般 CI 必跑。

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

report 會包含 command status、artifact hygiene、redaction、manual eval、browser smoke、cleanup dry-run 與 true-AI opt-in 狀態。預設 true-AI 是 `skipped_opt_in`。

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
