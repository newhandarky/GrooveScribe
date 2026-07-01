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
- `read_pipeline_snapshot.py`：internal/debug CLI，用 `job_id` 從 backend DB 與 `jobs/{job_id}/logs/pipeline.json` 讀取 pipeline snapshot；不改正式前端 API。

## Runtime gate

真 AI smoke 前先執行：

```bash
export PYTHON="$(pwd)/.venv-ai/bin/python"
PYTHONPATH=. "$PYTHON" scripts/check_ai_runtime.py
```

若 `runtime_checks.local_pipeline.true_ai_ready` 不是 `true`，不要宣告 `GS-P1-003` / `GS-P1-004` / 非 mock `GS-P1-007` 完成；依輸出的 `missing_requirements` 補安裝 Demucs/PyTorch 或設定 `GROOVESCRIBE_ADTOF_COMMAND_TEMPLATE`。

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

- `inspect_midi.py`
- `cleanup_storage.py`
