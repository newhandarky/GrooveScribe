# AI Runtime Notes

本文記錄 Phase 1 POC 所需的本地 AI runtime 與重現方式。這不是 production Docker 文件；正式部署仍由 Phase 8 處理。

## 目標

- 讓工程師能確認 ffmpeg、Demucs、ADTOF-pytorch、MIDI / notation 相關套件是否可用。
- 記錄模型與 adapter 的責任邊界，避免把模型 runtime 與業務邏輯耦合。
- 在尚未安裝真模型時，仍可用 `--mock-ai` 驗證 runner、artifact 與後處理流程。

## Runtime 檢查

```bash
export PYTHON="$(pwd)/.venv-ai/bin/python"
PYTHONPATH=. "$PYTHON" scripts/check_ai_runtime.py
```

目前本機 spot check（2026-06-30，使用 `.venv-ai/bin/python`）：

- Python：`3.11.15`
- ffmpeg：`ffmpeg version 8.0`
- MuseScore / PDF renderer：`/opt/homebrew/bin/mscore` 可用；PDF artifact smoke 已產生 `/tmp/groovescribe-score/score.pdf`。
- Python packages：`torch==2.12.1`、`torchaudio==2.11.0`、`torchcodec==0.14.0`、`demucs==4.0.1`、`mido==1.3.3`、`pretty_midi==0.2.11`、`music21==10.5.0`。
- ADTOF-pytorch：由官方 GitHub repo 安裝，commit `85c192e78f716ea0b111cc8a5ee4a8f6a3a4f8a9`，package version `0.1.0`。
- Demucs probe：`.venv-ai/bin/python -m demucs --help` 成功。
- ADTOF verification：使用 `.venv-ai/bin/adtof --audio {input} --out {output} --device {device} --threshold {threshold}`，對 `/tmp/groovescribe-stems/drums.wav` 產出可解析 `raw_drum.mid`，`event_count=7`。
- Local pipeline readiness：`runtime_checks.local_pipeline.true_ai_ready=true`；已完成兩個 generated fixtures 與一個授權真實鼓聲 fixture 的不使用 `--mock-ai` local runner smoke。

以上是當前開發機狀態，不是專案支援矩陣。建立正式 POC 環境時，請依實際 PyTorch / Demucs / ADTOF-pytorch wheel 支援選擇 Python 版本。

## Phase 1 最小 runtime

- Python：repo 目前宣告 `>=3.11`；AI runtime 使用 Python 3.11。
- ffmpeg：需要在 PATH 中可執行，用於 `run_normalize_audio.py` 與 local runner preprocessing stage。
- Demucs：由 `DemucsSourceSeparator` adapter 呼叫，預設使用目前 Python interpreter 執行 `-m demucs`。
- ADTOF-pytorch：由 `AdtofDrumTranscriber` adapter 呼叫；實際 CLI 透過 command template 配置。
- MuseScore CLI：可選，用於 PDF export；缺少時 MusicXML 仍應可產生。

## Runtime 設定

`scripts/check_ai_runtime.py` 會讀取 ADTOF 相關環境變數；`run_local_pipeline.py` 目前不直接讀取這些環境變數，只接受 CLI 參數。因此若範例使用 env，必須用 shell 展開後傳入 `--adtof-command-template`。

template 必須支援 `{input}` 與 `{output}` placeholder，並可選擇支援 `{device}`、`{threshold}`、`{checkpoint}`。

```bash
export GROOVESCRIBE_ADTOF_COMMAND_TEMPLATE="$(pwd)/.venv-ai/bin/adtof --audio {input} --out {output} --device {device} --threshold {threshold}"
export GROOVESCRIBE_ADTOF_CHECKPOINT=''
export GROOVESCRIBE_ADTOF_VERIFY_INPUT='/tmp/groovescribe-stems/drums.wav'
```

`scripts/check_ai_runtime.py` 只有在 ADTOF command 實際產生可解析且包含 note-on event 的 `raw_drum.mid` 後，才會將 `runtime_checks.adtof_pytorch.ready` 標示為 `true`。任意可執行命令或只會 echo path 的 template 不算 ADTOF ready。

`runtime_checks.adtof_pytorch.status_code` 會提供固定診斷碼：`ready`、`not_configured`、`template_invalid`、`executable_missing`、`verify_input_missing`、`verify_input_not_found`、`command_failed`、`output_missing`、`output_unparseable`、`output_no_events`。完整修復流程見 `docs/本機AI Runtime診斷與True AI啟用指南.md`。

## 安裝建議

在乾淨環境中先建立 AI 專用虛擬環境，再安裝 Phase 1 runtime 依賴：

```bash
python3.11 -m venv .venv-ai
source .venv-ai/bin/activate
python -m pip install --upgrade pip setuptools wheel
python -m pip install librosa soundfile torchaudio torch torchcodec pretty_midi mido music21 demucs pytest ruff mypy
python -m pip install 'git+https://github.com/xavriley/ADTOF-pytorch.git'
python -m pip install -e './ai_pipeline[dev]'
```

若 PyTorch / torchaudio 需要特定 CPU、CUDA、MPS wheel，請依目標機器重新安裝對應版本；不要把本機硬體假設寫進 adapter。

## Smoke Commands

### ffmpeg

```bash
ffmpeg -version
export PYTHON="$(pwd)/.venv-ai/bin/python"
PYTHONPATH=. "$PYTHON" scripts/run_normalize_audio.py --input tests/pipeline/fixtures/audio/synthetic_clean_drum_pattern.wav --output-dir /tmp/groovescribe-normalized
```

### Local Pipeline Without AI Models

```bash
export PYTHON="$(pwd)/.venv-ai/bin/python"
PYTHONPATH=. "$PYTHON" scripts/run_local_pipeline.py --input tests/pipeline/fixtures/audio/synthetic_clean_drum_pattern.wav --output-dir /tmp/groovescribe-fixture-run --mock-ai
```

### Demucs

```bash
export PYTHON="$(pwd)/.venv-ai/bin/python"
PYTHONPATH=. "$PYTHON" scripts/run_demucs_separation.py --input /tmp/groovescribe-normalized/normalized.wav --output-dir /tmp/groovescribe-stems --model-name htdemucs --device cpu
```

### ADTOF-pytorch

```bash
export PYTHON="$(pwd)/.venv-ai/bin/python"
export GROOVESCRIBE_ADTOF_COMMAND_TEMPLATE="$(pwd)/.venv-ai/bin/adtof --audio {input} --out {output} --device {device} --threshold {threshold}"
PYTHONPATH=. "$PYTHON" scripts/run_adtof_transcription.py \
  --input /tmp/groovescribe-stems/drums.wav \
  --output-dir /tmp/groovescribe-midi \
  --command-template "$GROOVESCRIBE_ADTOF_COMMAND_TEMPLATE" \
  --device cpu \
  --threshold 0.5
```

### Local Pipeline With True AI Runtime

只有在 `scripts/check_ai_runtime.py` 回報 `runtime_checks.local_pipeline.true_ai_ready=true` 後，才執行不帶 `--mock-ai` 的 runner。ADTOF verification 需要先有 Demucs 產出的 drums stem，並設定 `GROOVESCRIBE_ADTOF_VERIFY_INPUT`：

```bash
export PYTHON="$(pwd)/.venv-ai/bin/python"
export GROOVESCRIBE_ADTOF_COMMAND_TEMPLATE="$(pwd)/.venv-ai/bin/adtof --audio {input} --out {output} --device {device} --threshold {threshold}"
export GROOVESCRIBE_ADTOF_VERIFY_INPUT="/tmp/groovescribe-stems/drums.wav"
PYTHONPATH=. "$PYTHON" scripts/check_ai_runtime.py

PYTHONPATH=. "$PYTHON" scripts/run_local_pipeline.py \
  --input tests/pipeline/fixtures/audio/synthetic_clean_drum_pattern.wav \
  --output-dir /tmp/groovescribe-true-ai-run \
  --demucs-device cpu \
  --adtof-command-template "$GROOVESCRIBE_ADTOF_COMMAND_TEMPLATE" \
  --adtof-device cpu \
  --adtof-threshold 0.5
```

Opt-in pytest smoke：

```bash
RUN_TRUE_AI_SMOKE=1 \
GROOVESCRIBE_ADTOF_COMMAND_TEMPLATE="$GROOVESCRIBE_ADTOF_COMMAND_TEMPLATE" \
GROOVESCRIBE_ADTOF_VERIFY_INPUT="$GROOVESCRIBE_ADTOF_VERIFY_INPUT" \
backend/.venv/bin/python -m pytest backend/tests/test_pipeline_service_true_ai_smoke.py

RUN_TRUE_AI_SMOKE=1 .venv-ai/bin/python -m pytest tests/pipeline -k true_ai_smoke
```

這些 smoke 不屬於一般 CI 必跑條件；PDF 維持 optional，MIDI、MusicXML 與 pipeline log 是 true-AI smoke 的核心輸出。

Artifact inspection baseline：

```bash
PYTHONPATH=. "$PYTHON" scripts/run_true_ai_smoke_baseline.py \
  --input tests/pipeline/fixtures/audio/synthetic_clean_drum_pattern.wav \
  --output-root /tmp/groovescribe-true-ai-baseline \
  --demucs-device cpu \
  --adtof-command-template "$GROOVESCRIBE_ADTOF_COMMAND_TEMPLATE" \
  --adtof-device cpu \
  --adtof-threshold 0.5
```

此 command 會先跑 `scripts/check_ai_runtime.py`。若 true-AI runtime 還是 degraded，會寫出 `baseline.json` 並標記 `status=blocked`；若 ready，才會執行不帶 `--mock-ai` 的 local pipeline，並記錄 raw / processed MIDI inspection、MusicXML / PDF export 狀態與 pipeline warnings。

### PDF Export

MuseScore CLI 已安裝於 `/opt/homebrew/bin/mscore`。PDF artifact smoke command：

```bash
export PYTHON="$(pwd)/.venv-ai/bin/python"
PYTHONPATH=. "$PYTHON" scripts/generate_score.py \
  --events-json /tmp/groovescribe-true-ai-run/midi/drum_events.json \
  --output-dir /tmp/groovescribe-score \
  --export-pdf
test -s /tmp/groovescribe-score/score.pdf
```

2026-06-30 smoke result:

- `score.musicxml` generated at `/tmp/groovescribe-score/score.musicxml`.
- `score.pdf` generated at `/tmp/groovescribe-score/score.pdf`, size `29K`.
- `test -s /tmp/groovescribe-score/score.pdf` passed.
- `file /tmp/groovescribe-score/score.pdf` reports `PDF document, version 1.4, 1 pages`.

Known caveat: MuseScore 4.7.3 can produce the PDF artifact but return a non-zero status during CLI shutdown. `MuseScorePdfExporter` now reports this as `completed_with_warning` when `score.pdf` exists and is non-empty; missing or empty PDF output remains `failed`.

## 授權真實鼓聲 Fixture

目前 repo 內音檔只有 `tests/pipeline/fixtures/audio/` 下的 generated synthetic fixtures 與 invalid-audio fixture；授權真實鼓聲 smoke fixture 目前位於 repo 外：

- `/Users/zhangzhipeng/MyProject/files/audio/authorized_real_drum_smoke_60s_12s.wav`

這個外部 fixture 已完成 true AI smoke，可用於目前開發機的品質檢查；若要讓其他開發機重現，仍需將授權來源、取得方式或可提交副本整理進 fixture 流程。

建議放置路徑：

- `tests/pipeline/fixtures/audio/authorized_real_drum_smoke.wav`

音檔要求：

- 5-15 秒、WAV 或可由 ffmpeg 解碼的格式。
- 來源需可提交或可在本機保存並記錄授權；不要使用未授權商用歌曲或 loop library。
- 儘量包含清楚 kick、snare、closed hi-hat，避免完整商用混音。

本次授權 fixture true AI smoke command：

```bash
export PYTHON="$(pwd)/.venv-ai/bin/python"
export GROOVESCRIBE_ADTOF_COMMAND_TEMPLATE="$(pwd)/.venv-ai/bin/adtof --audio {input} --out {output} --device {device} --threshold {threshold}"

PYTHONPATH=. "$PYTHON" scripts/run_local_pipeline.py \
  --input /Users/zhangzhipeng/MyProject/files/audio/authorized_real_drum_smoke_60s_12s.wav \
  --output-dir /tmp/groovescribe-authorized-real-drum-run \
  --demucs-device cpu \
  --adtof-command-template "$GROOVESCRIBE_ADTOF_COMMAND_TEMPLATE" \
  --adtof-device cpu \
  --adtof-threshold 0.5
```

## Artifact 命名

Phase 1 local runner 使用下列固定 artifact 名稱：

- `audio/normalized.wav`
- `stems/drums.wav`
- `midi/raw_drum.mid`
- `midi/processed_drum.mid`
- `midi/drum_events.json`
- `notation/score.musicxml`
- `exports/score.pdf`，僅在 PDF renderer 可用且要求 export 時產生
- `logs/pipeline.json`

## 2026-06-30 True AI Fixture Smoke

Input fixtures:

- `tests/pipeline/fixtures/audio/synthetic_clean_drum_pattern.wav`
- `tests/pipeline/fixtures/audio/synthetic_separated_kick_snare_hat_pattern.wav`
- `/Users/zhangzhipeng/MyProject/files/audio/authorized_real_drum_smoke_60s_12s.wav`

Clean fixture artifacts:

- `/tmp/groovescribe-true-ai-run/audio/normalized.wav`
- `/tmp/groovescribe-true-ai-run/stems/drums.wav`
- `/tmp/groovescribe-true-ai-run/midi/raw_drum.mid`
- `/tmp/groovescribe-true-ai-run/midi/processed_drum.mid`
- `/tmp/groovescribe-true-ai-run/midi/drum_events.json`
- `/tmp/groovescribe-true-ai-run/notation/score.musicxml`
- `/tmp/groovescribe-true-ai-run/logs/pipeline.json`

Separated fixture artifacts:

- `/tmp/groovescribe-separated-ksh-run/audio/normalized.wav`
- `/tmp/groovescribe-separated-ksh-run/stems/drums.wav`
- `/tmp/groovescribe-separated-ksh-run/midi/raw_drum.mid`
- `/tmp/groovescribe-separated-ksh-run/midi/processed_drum.mid`
- `/tmp/groovescribe-separated-ksh-run/midi/drum_events.json`
- `/tmp/groovescribe-separated-ksh-run/notation/score.musicxml`
- `/tmp/groovescribe-separated-ksh-run/logs/pipeline.json`

Authorized real-drum fixture artifacts:

- `/tmp/groovescribe-authorized-real-drum-run/audio/normalized.wav`
- `/tmp/groovescribe-authorized-real-drum-run/stems/drums.wav`
- `/tmp/groovescribe-authorized-real-drum-run/midi/raw_drum.mid`
- `/tmp/groovescribe-authorized-real-drum-run/midi/processed_drum.mid`
- `/tmp/groovescribe-authorized-real-drum-run/midi/drum_events.json`
- `/tmp/groovescribe-authorized-real-drum-run/notation/score.musicxml`
- `/tmp/groovescribe-authorized-real-drum-run/logs/pipeline.json`

Result summary:

- Demucs `htdemucs` CPU separation completed, `drums.wav` duration `2.0s`, sample rate `44100`, channels `2`.
- ADTOF raw MIDI completed, `event_count=7`, threshold `0.5`, CPU device.
- MIDI post-processing completed, `output_event_count=7`, no dropped events.
- MusicXML generation completed, `measure_count=1`.
- Second true AI fixture `synthetic_separated_kick_snare_hat_pattern.wav` completed end to end without `--mock-ai`; ADTOF emitted `event_count=4` and MusicXML generation completed with `measure_count=2`.
- Authorized real-drum fixture completed end to end without `--mock-ai`; ADTOF emitted `event_count=14`, MIDI post-processing kept all 14 events, and MusicXML generation completed with `measure_count=6`.
- PDF artifact smoke completed after MuseScore CLI install; `/tmp/groovescribe-score/score.pdf` exists, is non-empty, and is a one-page PDF.
- Manual eval recorded at `tests/manual_eval/2026-06-30_true_ai_fixture_eval.csv`; output quality is low for both synthetic fixtures and medium for the authorized real-drum fixture.

ADTOF quality diagnosis:

- `synthetic_clean_drum_pattern.wav` raw MIDI notes were six `47` events and one `35` event. The postprocessor maps `47` to GM tom and `35` to kick, so the mostly-tom result comes from ADTOF raw output rather than a postprocessor mapping bug.
- `synthetic_separated_kick_snare_hat_pattern.wav` raw MIDI notes were four `47` events. The pipeline correctly preserved these as tom events after quantization.
- `authorized_real_drum_smoke_60s_12s.wav` raw MIDI notes were eight `35` events and six `38` events. The postprocessor maps them to kick and snare with no dropped events, so mapping is working for these GM notes.
- Current evidence points to synthetic timbre mismatch for the generated fixtures. On the authorized real-drum fixture, ADTOF performs materially better for kick/snare but still misses hi-hat entirely, so model quality is improved but not fully validated for MVP drum transcription.

## 已知限制

- `--mock-ai` 只驗證 pipeline orchestration，不代表模型準確度。
- MuseScore CLI 已安裝且 PDF artifact smoke 已產生非空 PDF；MuseScore 非零 return code + 非空 PDF 目前回報為 `completed_with_warning`。
- ADTOF-pytorch CLI 已確認，且授權真實鼓聲 fixture 已跑通；仍需要更多授權測試音檔與 ground-truth / manual eval criteria 才能判定 MVP 品質門檻。
- 這次 true AI smoke 證明 pipeline 可跑通；manual eval 顯示 synthetic fixture 輸出品質偏低，真實鼓聲 fixture 的 kick/snare 明顯改善，但 hi-hat 仍缺失。

## 2026-07-03 V1 True AI Baseline

本輪使用 local-first V1 baseline runner，目標是驗證目前 main 狀態下 true-AI runtime 是否 ready，並保存 artifact inspection baseline。true AI 仍是 opt-in，不是一般 CI 必跑條件。

Runtime:

- Python：`.venv-ai/bin/python`，`3.11.15`
- Demucs：`htdemucs`，CPU
- ADTOF：CLI template `.venv-ai/bin/adtof --audio {input} --out {output} --device {device} --threshold {threshold}`，CPU，threshold `0.5`
- ADTOF checkpoint：未設定
- Preflight：`runtime_checks.local_pipeline.true_ai_ready=true`
- ADTOF verification：`status_code=ready`，`event_count=7`

Baseline command:

```bash
PYTHONPATH=. GROOVESCRIBE_DEMUCS_DEVICE=cpu GROOVESCRIBE_ADTOF_DEVICE=cpu GROOVESCRIBE_ADTOF_THRESHOLD=0.5 \
GROOVESCRIBE_ADTOF_COMMAND_TEMPLATE="$(pwd)/.venv-ai/bin/adtof --audio {input} --out {output} --device {device} --threshold {threshold}" \
GROOVESCRIBE_ADTOF_VERIFY_INPUT=/tmp/groovescribe-stems/drums.wav \
GROOVESCRIBE_ADTOF_VERIFY_OUTPUT_DIR=/tmp/groovescribe-adtof-verify \
.venv-ai/bin/python scripts/run_true_ai_smoke_baseline.py \
  --input tests/pipeline/fixtures/audio/synthetic_clean_drum_pattern.wav \
  --output-root /tmp/groovescribe-true-ai-baseline \
  --run-id 20260703Ttrue-ai-baseline \
  --demucs-device cpu \
  --adtof-command-template "$(pwd)/.venv-ai/bin/adtof --audio {input} --out {output} --device {device} --threshold {threshold}" \
  --adtof-device cpu \
  --adtof-threshold 0.5
```

Baseline result:

- Baseline report：`/tmp/groovescribe-true-ai-baseline/20260703Ttrue-ai-baseline/baseline.json`
- Status：`completed`
- MIDI export：available
- MusicXML export：available
- PDF export：unavailable，但 optional，未阻塞 baseline
- Pipeline warnings：`hihat_missing_likely`、`mostly_tom_output`
- Raw MIDI inspection：`event_count=7`，note histogram `{35: 1, 47: 6}`，mapped drum counts `{kick: 1, tom: 6}`
- Processed MIDI inspection：`event_count=7`，note histogram `{36: 1, 45: 6}`，mapped drum counts `{kick: 1, tom: 6}`
- Manual eval：`tests/manual_eval/2026-07-03_true_ai_baseline_eval.csv`

Opt-in smoke cross-check:

- `RUN_TRUE_AI_SMOKE=1 .venv-ai/bin/python -m pytest tests/pipeline -k true_ai_smoke` passed.
- `RUN_TRUE_AI_SMOKE=1 backend/.venv/bin/python -m pytest backend/tests/test_pipeline_service_true_ai_smoke.py` passed when run from `backend/` with `PYTHONPATH=..`.

Quality conclusion:

- True-AI runtime and artifact contract are ready enough for continued V1 validation.
- Synthetic fixture transcription quality remains low: ADTOF output is mostly tom events and misses snare / hi-hat.
- This is a quality baseline, not a V1 quality pass. Next quality work should focus on better authorized real-drum fixtures and postprocessing / model-output diagnosis, not on changing the local-first runtime default.
