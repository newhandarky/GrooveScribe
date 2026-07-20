# Scripts

本目錄保留本地開發與 pipeline POC scripts。

## 品質驗證政策

GrooveScribe 的產品品質 gate 採 automation-only：repo 內 generated fixtures 用於快速 regression，repo 外授權音檔與 ground-truth MIDI manifest 用於 True-AI benchmark。人工評分、人工校準與 manual-eval CSV 僅保留為 legacy diagnostics，不可用來通過或放寬產品品質 gate。

## 已建立

- `run_local_pipeline.py`：串接本地 POC pipeline；支援 dry-run 與 `--mock-ai` smoke test。
- `run_normalize_audio.py`：使用 ffmpeg 將 MP3/WAV 轉成 `normalized.wav`。
- `run_demucs_separation.py`：使用 Demucs 將 `normalized.wav` 分離成穩定輸出 `drums.wav` 與可選 `no_drums.wav` 伴奏 stem。
- `run_adtof_transcription.py`：透過可配置 ADTOF command 將 `drums.wav` 轉成 `raw_drum.mid`。
- `run_midi_postprocess.py`：將 `raw_drum.mid` 後處理為 `processed_drum.mid` 與 `drum_events.json`。
- `generate_score.py`：從 `drum_events.json` 產生 `score.musicxml`，可選用 MuseScore CLI 轉出 PDF。
- `run_musescore_visual_qa.py`：從 MusicXML 產生 PDF 與第一頁 PNG。Linux headless CI 可執行：
  `python scripts/run_musescore_visual_qa.py --musicxml /path/to/score.musicxml --output-dir /tmp/score-visual-qa --renderer musescore`。
  macOS agent 若無 GUI session，會回報 `musescore_gui_session_unavailable`，不代表 MusicXML 失敗。
- `generate_test_fixtures.py`：產生 Phase 1 pipeline smoke test 用的合成音檔與 manifest。
- `check_ai_runtime.py`：輸出本機 ffmpeg、Demucs、ADTOF command/template、MuseScore、Python package 可用性，並列出真 AI local pipeline 缺口。
- `prepare_adtof_verify_input.py`：用 full mix fixture 執行 normalize + Demucs，產生 ADTOF verification 所需的 `drums.wav`；支援 `--dry-run`。
- `inspect_midi.py`：讀 raw / processed MIDI，輸出 note histogram、mapped drum counts、event count、duration / measure estimate 與 quality flags。
- `inspect_pipeline_artifacts.py`：合併 raw / processed MIDI inspection，輸出 manual eval 與 result API 可重用的 quality summary。
- `run_true_ai_smoke_baseline.py`：opt-in 執行 true-AI preflight / pipeline smoke，並輸出 `baseline.json`；runtime degraded 時保存 blocked reason。
- `run_true_ai_quality_matrix.py`：對多個 fixture 與 ADTOF threshold 跑 true-AI baseline matrix，彙整 raw note histogram、processed drum counts、quality flags、MusicXML validation 與最低可用性門檻。
- `check_v1_true_ai_setup.py`：套用 V1 true-AI 本機預設 env，驗證 ADTOF CLI / verify input / raw MIDI note events，輸出 public-safe setup report。
- `run_v1_real_audio_pilot.py`：對 repo 外授權真實音檔跑 true-AI eval 與 threshold matrix，輸出 repo 外 pilot report / handoff / manual eval seed。
- `generate_manual_eval_row.py`：從 `baseline.json` 產生一列符合 `tests/manual_eval/manual_eval_template.csv` 的 CSV row；artifact ref 只輸出 redacted label。
- `check_manual_eval_gate.py`：驗證 manual eval CSV schema、blocked/completed row contract 與 redaction。
- `cleanup_storage.py`：檢查 repo-local `storage/local` 狀態；目前只支援 dry-run，不刪檔。
- `plan_local_reset.py`：列出 local reset 會影響的 storage / DB 目標；dry-run only，不刪檔。
- `check_v1_local_setup.py`：檢查 V1 localhost 啟動條件，包含 venv、backend import、frontend dependencies、Playwright Chromium、port 與 artifact hygiene；輸出 redacted JSON。
- `run_v1_local_dev.py`：一個命令啟動 backend uvicorn 與 frontend Vite；Ctrl-C 會停止子程序，不刪 storage / DB。
- `export_review_packet.py`：從 completed job 匯出 repo 外 review packet JSON / Markdown，可選 ZIP；不輸出本機絕對路徑或 raw diagnostics。
- `run_v1_release_gate.py`：聚合 deterministic V1 release gate，輸出 redacted JSON report。
- `generate_v1_release_evidence.py`：產生 repo 外 V1 release evidence JSON / Markdown，彙整 release gate、runtime、manual eval、browser smoke、cleanup/reset、artifact hygiene 與 true-AI opt-in 狀態。
- `run_v1_rc_pilot.py`：產生 repo 外 RC pilot handoff bundle，彙整 release gate、evidence、git hygiene、manual eval、browser smoke 與 optional review packet。
- `check_v1_rc_handoff.py`：驗證 RC handoff manifest / Markdown schema 與 redaction。
- `read_pipeline_snapshot.py`：internal/debug CLI，用 `job_id` 從 backend DB 與 `jobs/{job_id}/logs/pipeline.json` 讀取 pipeline snapshot；不改正式前端 API。

## Runtime gate

真 AI smoke 前先執行：

```bash
export PYTHON="$(pwd)/.venv-ai/bin/python"
PYTHONPATH=. "$PYTHON" scripts/check_ai_runtime.py
```

若 `runtime_checks.local_pipeline.true_ai_ready` 不是 `true`，不要宣告 true-AI smoke 完成；依輸出的 `missing_requirements` 與 `runtime_checks.adtof_pytorch.status_code` 補安裝 Demucs/PyTorch、設定 `GROOVESCRIBE_ADTOF_COMMAND_TEMPLATE`，或提供 `GROOVESCRIBE_ADTOF_VERIFY_INPUT`。

V1 true-AI setup doctor：

```bash
npm run check:true-ai
```

true-AI local app：

```bash
npm run dev:true-ai -- --backend-port 8001 --frontend-port 5174
```

ADTOF verification input 必須是已存在的 drums stem，不是完整歌曲。可先執行：

```bash
PYTHONPATH=. "$PYTHON" scripts/run_normalize_audio.py \
  --input tests/pipeline/fixtures/audio/synthetic_clean_drum_pattern.wav \
  --output-dir /tmp/groovescribe-normalized

PYTHONPATH=. "$PYTHON" scripts/run_demucs_separation.py \
  --input /tmp/groovescribe-normalized/normalized.wav \
  --output-dir /tmp/groovescribe-stems \
  --model-name htdemucs \
  --device cpu

export GROOVESCRIBE_ADTOF_VERIFY_INPUT="/tmp/groovescribe-stems/drums.wav"
```

或用 helper 串起同一流程：

```bash
PYTHONPATH=. "$PYTHON" scripts/prepare_adtof_verify_input.py \
  --input tests/pipeline/fixtures/audio/synthetic_clean_drum_pattern.wav \
  --device cpu
```

true-AI smoke 是 opt-in，不是一般 CI 必跑：

```bash
RUN_TRUE_AI_SMOKE=1 \
GROOVESCRIBE_ADTOF_COMMAND_TEMPLATE="$GROOVESCRIBE_ADTOF_COMMAND_TEMPLATE" \
GROOVESCRIBE_ADTOF_VERIFY_INPUT="$GROOVESCRIBE_ADTOF_VERIFY_INPUT" \
backend/.venv/bin/python -m pytest backend/tests/test_pipeline_service_true_ai_smoke.py

RUN_TRUE_AI_SMOKE=1 .venv-ai/bin/python -m pytest tests/pipeline -k true_ai_smoke
```

若需要保存 artifact inspection baseline：

```bash
PYTHONPATH=. "$PYTHON" scripts/run_true_ai_smoke_baseline.py \
  --input tests/pipeline/fixtures/audio/synthetic_clean_drum_pattern.wav \
  --output-root /tmp/groovescribe-true-ai-baseline \
  --demucs-device cpu \
  --adtof-command-template "$GROOVESCRIBE_ADTOF_COMMAND_TEMPLATE" \
  --adtof-device cpu \
  --adtof-threshold 0.5
```

`baseline.json` 可能是 `completed`、`failed` 或 `blocked`。`blocked` 代表 true-AI runtime 尚未 ready，應保留 blocked reason，不要填入假 manual eval 分數。

baseline report v2 會包含 raw/processed MIDI inspection、MusicXML validation、PDF optional status、pipeline quality 與 `baseline:<run-id>` ref。PDF unavailable 不阻塞 baseline；MusicXML validation 會標出 parseable / warning code，供 result review 與 manual eval 判讀。

從 baseline 產出 manual eval row：

```bash
PYTHONPATH=. "$PYTHON" scripts/generate_manual_eval_row.py \
  /tmp/groovescribe-true-ai-baseline/<run>/baseline.json
```

若要比較多組 ADTOF threshold 與固定 fixture 品質，可跑 matrix：

```bash
PYTHONPATH=. "$PYTHON" scripts/run_true_ai_quality_matrix.py \
  --output-dir /tmp/groovescribe-true-ai-quality-matrix \
  --thresholds 0.2,0.3,0.4,0.5,0.6 \
  --demucs-device cpu \
  --adtof-command-template "$GROOVESCRIBE_ADTOF_COMMAND_TEMPLATE" \
  --adtof-device cpu
```

若有 repo 外授權真實鼓聲片段，使用環境變數加入 matrix；script 只會在 report 中記錄 redacted label，不會提交音檔或 artifact：

```bash
export GROOVESCRIBE_AUTHORIZED_REAL_DRUM_FIXTURE="/path/to/authorized_real_drum.wav"
```

## 自動化 ground-truth benchmark

使用 repo 外、已授權的音檔與對應 MIDI ground truth manifest，可全自動比較每個 `0.3 / 0.4 / 0.5 / 0.6` 候選。每個項目只執行一次前處理與 Demucs；報告會輸出候選的整體／各鼓件 F1、時序誤差、core-groove 對齊、譜面 performance gate 與推薦是否未劣於 ground-truth 最佳候選。

```bash
PYTHONPATH=. "$PYTHON" scripts/run_performance_benchmark.py \
  --manifest /path/outside-repo/performance_manifest.json \
  --output-dir /tmp/groovescribe-performance-benchmark \
  --candidate-thresholds 0.3,0.4,0.5,0.6 \
  --demucs-device cpu \
  --adtof-command-template "$GROOVESCRIBE_ADTOF_COMMAND_TEMPLATE" \
  --adtof-device cpu
```

未設定 manifest 時，工具會明確回報 `skipped`，不影響一般 CI。設定 manifest 後，缺少可量測 ground truth、未通過參考 acceptance，或推薦候選的品質劣於同組最佳候選時，工具會以非零結束碼失敗。音檔、MIDI、manifest 與 reports 必須留在 repo 外；JSON/CSV 僅輸出固定白名單欄位，不含本機路徑或 raw command。

真實音檔 pilot 會同時產出 V1 eval 與 threshold matrix 摘要：

```bash
.venv-ai/bin/python scripts/run_v1_real_audio_pilot.py \
  --input /path/to/your-authorized-audio.wav \
  --output-dir /tmp/groovescribe-v1-real-audio-pilot
```

輸出包含 `pilot_report.json`、`pilot_handoff.md`、`v1_eval/v1_eval_report.json`、`quality_matrix/matrix_report.json`。若結果是 `completed_with_blockers`，代表 artifacts 產生了但還不建議交付；請依 `primary_blocker` 與 `candidate_thresholds` 調整來源音檔或 threshold。真實音檔與 pilot outputs 不進 git。

也可以針對既有 artifact 產出 inspection JSON：

```bash
PYTHONPATH=. "$PYTHON" scripts/inspect_pipeline_artifacts.py \
  --raw-midi /tmp/groovescribe-true-ai-baseline/<run>/midi/raw_drum.mid \
  --processed-midi /tmp/groovescribe-true-ai-baseline/<run>/midi/processed_drum.mid
```

詳細修復流程見 `docs/本機AI Runtime診斷與True AI啟用指南.md`。

## Internal pipeline snapshot debug

工程師查詢 job pipeline snapshot 可先使用 CLI：

```bash
backend/.venv/bin/python scripts/read_pipeline_snapshot.py \
  --job-id <job_id> \
  --pretty
```

可用 `--database-url` 與 `--storage-root` 指向非預設環境。輸出包含 `job_id`、`status`、`failed_stage`、`artifacts`、`stage_reports`、`warnings`、`completed_with_warning`、`error`、`mock_ai` / `pipeline_mode` 與 `pipeline_log_found`。

若需要遠端查詢，backend 也提供預設關閉的 internal route：

```bash
INTERNAL_API_ENABLED=true
INTERNAL_API_TOKEN=<token>
curl -H "Authorization: Bearer <token>" \
  http://localhost:8000/internal/jobs/<job_id>/pipeline-snapshot
```

此 route 不掛在 `/api/v1/transcriptions/*`，不出現在公開 OpenAPI，且 response 會遮蔽本機路徑、command template、checkpoint path、stderr/stdout、stack trace 與 secret-like 欄位。

## 預期後續 script

- storage cleanup execute mode，必須另做安全設計與人工確認，不能在 V1 預設自動刪檔。

## Mock browser smoke path

V1 release 前至少重跑一次 deterministic browser smoke：

```bash
npx playwright install chromium
npm run test:e2e
```

此 smoke 使用 Playwright 啟動 localhost frontend，並以 mocked `/api/v1/*` contract 驗證 upload -> completed -> result page、MIDI/MusicXML download 可見、MusicXML preview/fallback 可見、PDF optional unavailable / failed 狀態可見。true-AI 與 PDF renderer 仍不得成為一般 CI 必跑條件，也不得提交 `frontend/dist`、`storage/`、DB 或 Playwright report artifacts。

## V1 local launch

檢查本機啟動條件：

```bash
npm run check:local
```

啟動 localhost backend / frontend：

```bash
npm run dev:local
```

若 port 8000 或 5173 已被占用，可直接呼叫 script 指定 port：

```bash
.venv-ai/bin/python scripts/run_v1_local_dev.py \
  --backend-port 8010 \
  --frontend-port 5174
```

`run_v1_local_dev.py` 是長駐開發程序，不放進 release gate；`check_v1_local_setup.py` 才會進 deterministic gate。release gate 會用 `--skip-port-check`，避免已開啟的 localhost backend / frontend 讓 sign-off 誤失敗；手動 `npm run check:local` 預設仍會檢查 8000 / 5173。

## V1 review packet export

Completed job 可匯出 review packet，交給 reviewer 做人工修譜或 manual eval：

```bash
backend/.venv/bin/python scripts/export_review_packet.py \
  --job-id <job_id> \
  --output-dir /tmp/groovescribe-review-packet \
  --zip
```

輸出包含：

- `review_packet.json`
- `review_notes.md`
- `review_packet.zip`，若加 `--zip`

`--output-dir` 必須在 repo 外；script 會拒絕 repo 內輸出。review packet 不包含 storage key、本機絕對路徑、traceback、stdout/stderr、raw command 或 command template。PDF unavailable 不阻塞 packet 產生。

## V1 release gate

重跑完整 deterministic release gate：

```bash
.venv-ai/bin/python scripts/run_v1_release_gate.py
```

若要保存 report，請寫到 repo 外：

```bash
.venv-ai/bin/python scripts/run_v1_release_gate.py \
  --output /tmp/groovescribe-v1-release-gate/report.json
```

manual eval 與 reset / cleanup 可單獨檢查：

```bash
.venv-ai/bin/python scripts/check_manual_eval_gate.py
.venv-ai/bin/python scripts/cleanup_storage.py
.venv-ai/bin/python scripts/plan_local_reset.py
```

`run_v1_release_gate.py` 預設不跑 true-AI；只有明確加 `--include-true-ai` 才會執行 opt-in tests。PDF renderer 不是一般 gate blocker。

## V1 release evidence

產生 final sign-off evidence，預設寫到 repo 外：

```bash
.venv-ai/bin/python scripts/generate_v1_release_evidence.py \
  --output-dir /tmp/groovescribe-v1-release-evidence
```

輸出 `evidence.json` 與 `evidence.md`。內容只包含 public-safe 摘要，不輸出本機絕對路徑、traceback、stdout/stderr、raw command 或 command template。

若已先保存 release gate report：

```bash
.venv-ai/bin/python scripts/generate_v1_release_evidence.py \
  --gate-report /tmp/groovescribe-v1-release-gate/report.json \
  --output-dir /tmp/groovescribe-v1-release-evidence
```

true-AI 仍是 opt-in：

True-AI job 內建會依序比較 `0.3`、`0.4`、`0.5`、`0.6` 候選，重用同一次 Demucs 分離。候選輸出只存在 local storage，Result API 只提供受控 download URL；不得把候選 storage key、本機路徑、stems 或原始子程序輸出帶入文件、API 或 git。

```bash
.venv-ai/bin/python scripts/generate_v1_release_evidence.py \
  --include-true-ai \
  --output-dir /tmp/groovescribe-v1-release-evidence
```

`--include-true-ai` 只適合 runtime 已 ready 時使用；一般 deterministic sign-off 不要求 true-AI 或 PDF renderer。

## V1 RC pilot handoff

產生最終 RC 交接包：

```bash
.venv-ai/bin/python scripts/run_v1_rc_pilot.py \
  --output-dir /tmp/groovescribe-v1-rc-pilot
```

驗證交接包：

```bash
.venv-ai/bin/python scripts/check_v1_rc_handoff.py \
  /tmp/groovescribe-v1-rc-pilot/rc_manifest.json
```

若要附帶 completed job 的 review packet：

```bash
.venv-ai/bin/python scripts/run_v1_rc_pilot.py \
  --output-dir /tmp/groovescribe-v1-rc-pilot \
  --review-job-id <job_id>
```

RC outputs 必須在 repo 外；不得提交 `rc_manifest.json`、`rc_handoff.md`、release evidence、review packet、`frontend/dist`、`storage/`、SQLite/DB、tmp 或 Playwright reports。true-AI 仍只有 `--include-true-ai` 時 opt-in，PDF renderer 仍不是一般 gate blocker。

## V1 product pilot

Product pilot 是功能可用性檢查，不是 tag 或發布流程。它聚焦使用者實際路徑：上傳、完成結果、下載 MIDI/MusicXML、review packet、job history、completed rerun、failed/interrupted retry 與 local data dry-run 狀態。

```bash
.venv-ai/bin/python scripts/run_v1_product_pilot.py \
  --output-dir /tmp/groovescribe-v1-product-pilot
```

輸出：

- `product_pilot_report.json`
- `product_pilot_handoff.md`

Product pilot 預設會跑 browser e2e，因此需要本機 localhost bind 與 Playwright Chromium。true-AI 仍是 opt-in 之外的手動流程；PDF renderer 仍不是 blocker。輸出必須在 repo 外；不得提交 generated pilot reports、`frontend/dist`、storage、DB、tmp 或 Playwright reports。

## V1 final release notes / tag prep

Final release candidate 文件入口：

- `docs/V1_Release_Notes.md`
- `docs/V1_Tag_Prep_Checklist.md`
- `docs/V1_Release_Artifact_Index.md`

tag 前最後 sign-off 入口仍是 RC pilot：

```bash
.venv-ai/bin/python scripts/run_v1_rc_pilot.py \
  --output-dir /tmp/groovescribe-v1-rc-pilot
.venv-ai/bin/python scripts/check_v1_rc_handoff.py \
  /tmp/groovescribe-v1-rc-pilot/rc_manifest.json
```

release notes / tag prep 是 docs-only finalization；不要在這一步改 public API、UI、pipeline behavior 或新增 dependency。true-AI 仍是 opt-in，PDF renderer 仍不是一般 tag blocker。
