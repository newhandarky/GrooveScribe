# Scripts

本目錄保留本地開發與 pipeline POC scripts。

## 已建立

- `run_local_pipeline.py`：串接本地 POC pipeline；支援 dry-run 與 `--mock-ai` smoke test。
- `run_normalize_audio.py`：使用 ffmpeg 將 MP3/WAV 轉成 `normalized.wav`。
- `run_demucs_separation.py`：使用 Demucs 將 `normalized.wav` 分離成穩定輸出 `drums.wav`。
- `run_adtof_transcription.py`：透過可配置 ADTOF command 將 `drums.wav` 轉成 `raw_drum.mid`。
- `run_midi_postprocess.py`：將 `raw_drum.mid` 後處理為 `processed_drum.mid` 與 `drum_events.json`。
- `generate_score.py`：從 `drum_events.json` 產生 `score.musicxml`，可選用 MuseScore CLI 轉出 PDF。
- `generate_test_fixtures.py`：產生 Phase 1 pipeline smoke test 用的合成音檔與 manifest。
- `check_ai_runtime.py`：輸出本機 ffmpeg、Demucs、ADTOF command/template、MuseScore、Python package 可用性，並列出真 AI local pipeline 缺口。
- `prepare_adtof_verify_input.py`：用 full mix fixture 執行 normalize + Demucs，產生 ADTOF verification 所需的 `drums.wav`；支援 `--dry-run`。
- `inspect_midi.py`：讀 raw / processed MIDI，輸出 note histogram、mapped drum counts、event count、duration / measure estimate 與 quality flags。
- `inspect_pipeline_artifacts.py`：合併 raw / processed MIDI inspection，輸出 manual eval 與 result API 可重用的 quality summary。
- `run_true_ai_smoke_baseline.py`：opt-in 執行 true-AI preflight / pipeline smoke，並輸出 `baseline.json`；runtime degraded 時保存 blocked reason。
- `cleanup_storage.py`：檢查 repo-local `storage/local` 狀態；目前只支援 dry-run，不刪檔。
- `read_pipeline_snapshot.py`：internal/debug CLI，用 `job_id` 從 backend DB 與 `jobs/{job_id}/logs/pipeline.json` 讀取 pipeline snapshot；不改正式前端 API。

## Runtime gate

真 AI smoke 前先執行：

```bash
export PYTHON="$(pwd)/.venv-ai/bin/python"
PYTHONPATH=. "$PYTHON" scripts/check_ai_runtime.py
```

若 `runtime_checks.local_pipeline.true_ai_ready` 不是 `true`，不要宣告 true-AI smoke 完成；依輸出的 `missing_requirements` 與 `runtime_checks.adtof_pytorch.status_code` 補安裝 Demucs/PyTorch、設定 `GROOVESCRIBE_ADTOF_COMMAND_TEMPLATE`，或提供 `GROOVESCRIBE_ADTOF_VERIFY_INPUT`。

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
