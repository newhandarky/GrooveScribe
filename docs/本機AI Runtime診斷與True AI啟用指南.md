# 本機 AI Runtime 診斷與 True AI 啟用指南

本文說明 local-first V1 如何從 `degraded` runtime 狀態逐步啟用 true AI smoke。true AI 是 opt-in 驗證，不是 V1 預設必跑條件；預設 upload flow 仍使用 mock-ai pipeline。

## Runtime 狀態

| status | 意義 | 使用者可做什麼 |
|---|---|---|
| `ready` | mock pipeline 與 true AI runtime 都可用 | 可執行 opt-in true-AI smoke |
| `degraded` | mock pipeline 可用，但 true AI 尚未 ready | 可繼續跑 mock-ai upload / result / download flow |
| `not_ready` | mock pipeline 也不可用 | 先修復 ffmpeg / AI Python 等基礎 runtime |
| `error` | preflight 本身失敗 | 先修復 AI Python path 或 diagnostics script 執行問題 |

## ADTOF 設定格式

`GROOVESCRIBE_ADTOF_COMMAND_TEMPLATE` 是 shell-style command string，會用 `shlex.split` 解析。template 必須包含：

- `{input}`：Demucs 產出的 `drums.wav`
- `{output}`：ADTOF 應寫出的 `raw_drum.mid`

可選 placeholder：

- `{device}`
- `{threshold}`
- `{checkpoint}`

ADTOF CLI 範例：

```bash
export GROOVESCRIBE_ADTOF_COMMAND_TEMPLATE="$(pwd)/.venv-ai/bin/adtof --audio {input} --out {output} --device {device} --threshold {threshold}"
```

Python module 範例：

```bash
export AI_PYTHON="$(pwd)/.venv-ai/bin/python"
export GROOVESCRIBE_ADTOF_COMMAND_TEMPLATE="$AI_PYTHON -m adtof transcribe --input {input} --output {output} --device {device} --threshold {threshold}"
```

若使用 checkpoint：

```bash
export GROOVESCRIBE_ADTOF_CHECKPOINT="/path/to/model.ckpt"
```

如果 template 不含 `{checkpoint}`，pipeline adapter 會在有 checkpoint 設定時自動補 `--checkpoint <path>`。

## 準備 Verification Input

`GROOVESCRIBE_ADTOF_VERIFY_INPUT` 必須指向已存在的 drums stem，不是完整歌曲音檔。可用 fixture 先建立：

```bash
export PYTHON="$(pwd)/.venv-ai/bin/python"

PYTHONPATH=. "$PYTHON" scripts/prepare_adtof_verify_input.py \
  --input tests/pipeline/fixtures/audio/synthetic_clean_drum_pattern.wav \
  --device cpu

export GROOVESCRIBE_ADTOF_VERIFY_INPUT="/tmp/groovescribe-stems/drums.wav"
```

等同於手動執行 normalize 與 Demucs：

```bash
export PYTHON="$(pwd)/.venv-ai/bin/python"

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

輸入與輸出角色請固定區分：

- full song input：原始 WAV/MP3，用於 normalize。
- normalized wav：`normalized.wav`，用於 Demucs。
- Demucs drums stem：`drums.wav`，用於 `GROOVESCRIBE_ADTOF_VERIFY_INPUT`。
- ADTOF raw MIDI output：preflight 驗證時產出的 `raw_drum.mid`。

## Preflight 與狀態碼

執行：

```bash
PYTHONPATH=. "$PYTHON" scripts/check_ai_runtime.py
```

Backend API：

```bash
curl http://127.0.0.1:8000/api/v1/runtime/preflight
```

`checks.adtof.status_code` 會回傳：

| status_code | 意義 |
|---|---|
| `ready` | 已產出可解析且含 note-on events 的 `raw_drum.mid` |
| `not_configured` | 尚未設定 `GROOVESCRIBE_ADTOF_COMMAND_TEMPLATE` |
| `template_invalid` | template 無法解析或缺 `{input}` / `{output}` |
| `executable_missing` | ADTOF executable 或 module 不可用 |
| `verify_input_missing` | 尚未設定 `GROOVESCRIBE_ADTOF_VERIFY_INPUT` |
| `verify_input_not_found` | verify input 路徑不存在 |
| `command_failed` | ADTOF verification command 非 0 exit |
| `output_missing` | command 沒有產出 `raw_drum.mid` |
| `output_unparseable` | `raw_drum.mid` 無法被 MIDI parser 解析 |
| `output_no_events` | MIDI 可解析但沒有 note-on events |

API response 只應提供 redacted diagnostics，不暴露完整本機路徑、raw stderr 或 traceback。

## Opt-in True AI Smoke

只有在 preflight 顯示 `true_ai_ready=true` 後才執行：

```bash
RUN_TRUE_AI_SMOKE=1 \
GROOVESCRIBE_ADTOF_COMMAND_TEMPLATE="$GROOVESCRIBE_ADTOF_COMMAND_TEMPLATE" \
GROOVESCRIBE_ADTOF_VERIFY_INPUT="$GROOVESCRIBE_ADTOF_VERIFY_INPUT" \
backend/.venv/bin/python -m pytest backend/tests/test_pipeline_service_true_ai_smoke.py
```

Pipeline-level smoke：

```bash
RUN_TRUE_AI_SMOKE=1 .venv-ai/bin/python -m pytest tests/pipeline -k true_ai_smoke
```

通過條件：

- Job / local pipeline completed
- MIDI available
- MusicXML available
- pipeline log 存在
- PDF optional；PDF failed / unavailable 不阻塞 true-AI smoke

## Artifact Inspection

true-AI smoke 完成後，先不要直接判定品質通過。請逐項檢查：

1. `raw_drum.mid` 可解析，且 note-on events 大於 0。
2. `processed_drum.mid` 可解析，且 postprocess report 沒有 `no usable events` 類錯誤。
3. `drum_events.json` 包含 `raw_note_histogram`、`processed_drum_counts`、warnings。
4. `score.musicxml` 可被 MusicXML parser 或 notation tool 開啟。
5. `score.pdf` 若存在可開啟；若 failed / unavailable，確認 MIDI 與 MusicXML 沒被阻塞。
6. `pipeline.json` 不暴露完整本機路徑、traceback 或 raw stderr。

可用 MIDI inspection helper：

```bash
PYTHONPATH=. "$PYTHON" scripts/inspect_midi.py /path/to/raw_drum.mid
PYTHONPATH=. "$PYTHON" scripts/inspect_midi.py /path/to/processed_drum.mid
```

本機 storage cleanup 第一版只做 dry-run：

```bash
backend/.venv/bin/python scripts/cleanup_storage.py
```

它只列出 local storage 狀態，不會刪除檔案。

## 明確不在本切片處理

- 不做 Tauri / Electron
- 不做 cloud
- 不改 worker / Celery
- 不把 true AI 設成預設必跑
- 不要求每台開發機 true AI ready
