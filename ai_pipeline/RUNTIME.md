# AI Runtime Notes

本文記錄 Phase 1 POC 所需的本地 AI runtime 與重現方式。這不是 production Docker 文件；正式部署仍由 Phase 8 處理。

## 目標

- 讓工程師能確認 ffmpeg、Demucs、ADTOF-pytorch、MIDI / notation 相關套件是否可用。
- 記錄模型與 adapter 的責任邊界，避免把模型 runtime 與業務邏輯耦合。
- 在尚未安裝真模型時，仍可用 `--mock-ai` 驗證 runner、artifact 與後處理流程。

## Runtime 檢查

```bash
PYTHONPATH=. python scripts/check_ai_runtime.py
```

目前本機 spot check（2026-06-25）：

- Python：`3.14.4`
- ffmpeg：`ffmpeg version 8.0`
- Python packages：`torch`、`torchaudio`、`demucs`、`mido`、`pretty_midi`、`music21`、`fastapi`、`celery` 尚未安裝於目前 Python 環境。

以上是當前開發機狀態，不是專案支援矩陣。建立正式 POC 環境時，請依實際 PyTorch / Demucs / ADTOF-pytorch wheel 支援選擇 Python 版本。

## Phase 1 最小 runtime

- Python：repo 目前宣告 `>=3.11`。
- ffmpeg：需要在 PATH 中可執行，用於 `run_normalize_audio.py` 與 local runner preprocessing stage。
- Demucs：由 `DemucsSourceSeparator` adapter 呼叫，預設命令為 `python -m demucs`。
- ADTOF-pytorch：由 `AdtofDrumTranscriber` adapter 呼叫；因實際 CLI 尚未鎖定，現階段透過 command template 配置。
- MuseScore CLI：可選，用於 PDF export；缺少時 MusicXML 仍應可產生。

## 安裝建議

在乾淨環境中先建立虛擬環境，再安裝各子專案依賴：

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ./ai_pipeline[dev]
python -m pip install -e ./backend[dev]
python -m pip install -e ./worker[dev]
```

若 PyTorch / torchaudio 需要特定 CPU、CUDA、MPS wheel，請依目標機器重新安裝對應版本；不要把本機硬體假設寫進 adapter。

## Smoke Commands

### ffmpeg

```bash
ffmpeg -version
PYTHONPATH=. python scripts/run_normalize_audio.py --input tests/pipeline/fixtures/audio/synthetic_clean_drum_pattern.wav --output-dir /tmp/groovescribe-normalized
```

### Local Pipeline Without AI Models

```bash
PYTHONPATH=. python scripts/run_local_pipeline.py --input tests/pipeline/fixtures/audio/synthetic_clean_drum_pattern.wav --output-dir /tmp/groovescribe-fixture-run --mock-ai
```

### Demucs

```bash
PYTHONPATH=. python scripts/run_demucs_separation.py --input /tmp/groovescribe-normalized/normalized.wav --output-dir /tmp/groovescribe-stems --model-name htdemucs
```

### ADTOF-pytorch

ADTOF 實際命令尚未鎖定。現階段 runner 支援 command template：

```bash
PYTHONPATH=. python scripts/run_adtof_transcription.py   --input /tmp/groovescribe-stems/drums.wav   --output-dir /tmp/groovescribe-midi   --command-template "python -m adtof transcribe --input {input} --output {output} --device {device} --threshold {threshold}"
```

若確認真實 CLI 不同，只需調整 command template 或 `AdtofDrumTranscriber` adapter，不應修改 worker orchestration 或 API 層。

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

## 已知限制

- 目前尚未在本機實跑真 Demucs / ADTOF-pytorch。
- `--mock-ai` 只驗證 pipeline orchestration，不代表模型準確度。
- PDF export 依賴 MuseScore CLI；缺少 renderer 時應回報明確錯誤。
- ADTOF-pytorch CLI 尚待 runtime spike 確認，已用 adapter / command template 隔離風險。
