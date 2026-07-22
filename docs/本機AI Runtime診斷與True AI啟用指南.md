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

V1 true-AI setup doctor 會套用本機預設 env 並輸出 public-safe 摘要：

```bash
npm run check:true-ai
```

若 8000 被占用，true-AI local app 可改用 8001 / 5174：

```bash
npm run dev:true-ai -- --backend-port 8001 --frontend-port 5174
```

`dev:true-ai` 預設帶入：

- ADTOF CLI：`.venv-ai/bin/adtof --audio {input} --out {output} --device {device} --threshold {threshold}`
- verify input：`/tmp/groovescribe-stems/drums.wav`
- verify output：`/tmp/groovescribe-adtof-verify`
- Demucs / ADTOF device：`cpu`
- scalar threshold：`0.5`
- product preset：`separated_v1`
- tom filter：`tom_guard_v1`

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

## 多候選轉譜與自動化品質驗證

UI 的 True-AI V1 preset 預設依序比較 threshold `0.3`、`0.4`、`0.5`、`0.6`。Demucs 只執行一次；每組候選會各自執行 ADTOF、後處理、notation 與 MusicXML 驗證，因此 CPU 執行時間會比單次分析增加。

推薦規則固定先拒絕未完成、MusicXML 不可讀、kick/snare 缺失及阻擋性品質旗標，再依分離鼓聲 onset 對齊、鼓件比例、每小節密度、譜面可讀性與 performance gate 排序。真實使用者音檔不是 ground truth，不會用來調整門檻。

要以合法的配對音訊與 ground-truth MIDI 驗證候選推薦，使用 repository 內的工具在 repo 外建立或指定 private manifest。每個 item 會共用 preprocessing 與 Demucs，再比較 `0.3,0.4,0.5,0.6` 候選的 overall/per-drum F1、timing、core groove、MusicXML、可讀性與 performance gate：

```bash
PYTHONPATH=. .venv-ai/bin/python scripts/generate_realistic_performance_benchmark.py \
  --output-dir /tmp/groovescribe-candidate-calibration \
  --soundfont "$GROOVESCRIBE_BENCHMARK_SOUNDFONT"
PYTHONPATH=. .venv-ai/bin/python scripts/run_performance_benchmark.py \
  --manifest /tmp/groovescribe-candidate-calibration/realistic_performance_benchmark_manifest.json \
  --output-dir /tmp/groovescribe-candidate-calibration/results \
  --candidate-thresholds 0.3,0.4,0.5,0.6
```

品質 profile 為版本化且決定性的規則；未通過結構驗證的候選不可被推薦。設定 manifest 後，缺少 artifact、checksum/provenance 失敗、reference acceptance 未通過或推薦劣於同組最佳候選都會以非零結束。未設定 manifest 時只會回報 `skipped`，不影響一般 CI。benchmark 預設會安全重用「已完成、四個 threshold 完整匹配，且每個成功候選的 MIDI／timeline 都存在」的項目；明確記錄的候選失敗也會保留為量測結果，讓中斷後續跑不會重做前處理、Demucs 或 ADTOF。傳入 `--no-resume` 才會強制重跑。private manifest、SoundFont、音訊、MIDI、stems 與報告均必須留在 repo 外，也不進 git。

### Raw-model attribution 與實驗前提

`scripts/run_raw_model_attribution.py` 只量測既有 benchmark artifact，不會重新跑 Demucs／ADTOF。報告固定輸出每個 threshold 的 raw、processed、chart MIDI 指標與候選 failure category；不會輸出路徑、command 或 diagnostics。

raw MIDI F1 低只代表「Demucs 或 raw model」尚未被分離，不能單獨判定 Demucs 有問題。只有 manifest 提供 repo 外、可驗證的 `reference_drums_audio_path`，且具備 reference-drums → ADTOF、Demucs-drums → ADTOF、full-mix → Demucs → ADTOF 的配對結果時，才可比較分離造成的損失；SNR 同樣僅在這種 reference drum audio 存在時量測。否則 report 必須為 `reference_drums_audio_unavailable`。

manifest 也必須用 `benchmark_split: development | holdout` 區隔調整依據與最終 acceptance。缺少任一 split 時固定回報 `holdout_insufficient`，不會阻擋一般 CI，但不能宣告泛化品質已驗證。任何 Demucs／ADTOF 實驗 preset 都必須保持 True-AI opt-in，並先通過 generated fixtures 與 public benchmark 的非回歸比較；目前沒有因 attribution 不足而保留模型 preset。

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

## True AI Baseline Runner

若要同時保存 runtime blocked reason、pipeline result 與 artifact inspection，可使用 baseline runner。它仍是 opt-in，不會讓一般 CI 必跑 true AI：

```bash
PYTHONPATH=. "$PYTHON" scripts/run_true_ai_smoke_baseline.py \
  --input tests/pipeline/fixtures/audio/synthetic_clean_drum_pattern.wav \
  --output-root /tmp/groovescribe-true-ai-baseline \
  --demucs-device cpu \
  --adtof-command-template "$GROOVESCRIBE_ADTOF_COMMAND_TEMPLATE" \
  --adtof-device cpu \
  --adtof-threshold 0.5
```

行為：

- preflight 若仍是 `degraded`，會寫出 `baseline.json`，`status=blocked`，並記錄 `blocked_reason`、`missing_requirements`、`checks.adtof.status_code` 摘要。
- preflight 若 `true_ai_ready=true`，才執行不帶 `--mock-ai` 的 `run_local_pipeline.py`。
- completed baseline 會記錄 raw / processed MIDI inspection、`drum_events.json` warnings、MusicXML / PDF artifact 狀態與 pipeline stage summary。
- PDF 維持 optional；`pdf.status=unavailable` 不阻塞 MIDI / MusicXML baseline。

## Real Audio Pilot

使用者提供的授權音檔請走 real audio pilot，不要用 Demo/mock 結果判斷品質：

```bash
.venv-ai/bin/python scripts/run_v1_real_audio_pilot.py \
  --input /path/to/your-authorized-audio.wav \
  --output-dir /tmp/groovescribe-v1-real-audio-pilot
```

pilot 預設會：

- 檢查 true-AI setup 是否 ready，blocked 時保留明確 reason。
- 用 `separated_v1` + `tom_guard_v1` 跑 V1 true-AI eval。
- 跑 threshold matrix：`0.3`、`0.4`、`0.5`、`0.6`。
- 輸出 `pilot_report.json`、`pilot_handoff.md`、`v1_eval/v1_eval_report.json`、`quality_matrix/matrix_report.json`。
- legacy manual-eval seed 可供診斷；它不參與 automation-only 品質驗收，也不能用來調整或放寬候選規則。

如果 report 顯示 `completed_with_blockers`，代表 pipeline 有完成 artifacts，但還不能交付。請看 `primary_blocker`，常見情況：

- `sparse_transcription`：偵測事件過少，先換更乾淨鼓聲或檢查 threshold matrix。
- `hihat_missing_likely`：hi-hat 證據不足，優先檢查分離鼓聲與 ADTOF threshold。
- `mostly_tom_output`：tom 誤判偏多，檢查 `tom_guard_v1` 是否改善。

真實音檔、pilot outputs、review packet、storage、DB、tmp 與 Playwright reports 都不可提交。

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

Baseline report 裡至少應包含：

- `status`：`completed`、`blocked` 或 `failed`
- `runtime`：AI Python、Demucs device、ADTOF template 是否設定、threshold、checkpoint 是否設定
- `preflight`：mock / true AI readiness、missing requirements、ADTOF status code、verification event count
- `artifacts`：normalized audio、drums stem、raw MIDI、processed MIDI、drum events、MusicXML、PDF、pipeline log
- `inspection.raw_midi` 與 `inspection.processed_midi`：event count、note histogram、mapped drum counts
- `inspection.drum_events`：processed drum counts、raw note histogram、warnings
- `blocked_reason`：只有 blocked baseline 必填

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
