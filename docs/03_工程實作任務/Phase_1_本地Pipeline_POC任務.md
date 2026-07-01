# Phase 1：本地 Pipeline POC 任務

> Level 3 工程實作任務文件。本文只拆解開發 ticket，不取代 Level 1 / Level 2 規格。

## Phase 目標

在不依賴 API、database、queue、frontend 的情況下，先證明單首音檔可以從 MP3/WAV 跑到 normalized WAV、drums stem、raw MIDI、processed MIDI、MusicXML、PDF。

## 前置條件

- 可在開發機安裝 Python 與 ffmpeg。
- 已確認 Demucs 與 ADTOF-pytorch 的授權、安裝方式與模型檔來源。
- 已準備至少一個短音檔供 smoke test。

## 需參考的 Level 1 / Level 2 文件

- Level 1：開發計畫.md
- Level 1：AI音訊處理流程.md
- Level 2：AI_Pipeline執行規格.md
- Level 2：ffmpeg音訊標準化規格.md
- Level 2：Demucs鼓軌分離規格.md
- Level 2：ADTOF鼓MIDI轉寫規格.md
- Level 2：MIDI後處理與量化規格.md
- Level 2：鼓譜預覽與匯出規格.md

## 任務清單

- `GS-P1-001`：建立 Python 專案骨架
- `GS-P1-002`：建立 ffmpeg 音訊標準化 script
- `GS-P1-003`：整合 Demucs 鼓軌分離
- `GS-P1-004`：整合 ADTOF-pytorch 鼓 MIDI 轉寫
- `GS-P1-005`：建立 MIDI 後處理初版
- `GS-P1-006`：建立 MusicXML / PDF 輸出初版
- `GS-P1-007`：建立本地 pipeline runner
- `GS-P1-008`：準備測試音檔與人工檢查表
- `GS-P1-009`：鎖定 AI runtime 與安裝重現紀錄

## 目前專案狀態（2026-06-30）

- Closeout（2026-07-01）：Phase 1 runtime POC 可視為收尾完成；runtime、artifact、PDF smoke 與 manual eval 已有可重現紀錄。剩餘 ADTOF hi-hat recall、更多授權音檔與 ground-truth/manual eval criteria 屬品質門檻 backlog，不阻塞 runtime POC closeout。
- `GS-P1-001` / `GS-P1-002` / `GS-P1-005` / `GS-P1-006`：已有 POC code 與 fast tests；ffmpeg normalization、MIDI post-processing、MusicXML generation 可用。
- `GS-P1-003`：Demucs adapter、mock-command tests 與一次真 Demucs fixture smoke 已完成；`.venv-ai` 使用 Demucs `4.0.1`、model `htdemucs`、CPU device，輸出 `/tmp/groovescribe-stems/drums.wav`。
- `GS-P1-004`：ADTOF adapter、command template、MIDI validation tests 與一次真 ADTOF fixture smoke 已完成；使用 `adtof-pytorch` GitHub commit `85c192e78f716ea0b111cc8a5ee4a8f6a3a4f8a9`，CLI template 為 `.venv-ai/bin/adtof --audio {input} --out {output} --device {device} --threshold {threshold}`。
- `GS-P1-007`：local runner 可用 `--mock-ai` 完成，也已用不帶 `--mock-ai` 的真 Demucs + ADTOF pipeline 跑通兩個 generated synthetic fixtures 與一個授權真實鼓聲 fixture，產出 normalized WAV、drums stem、raw/processed MIDI、drum events、MusicXML；MuseScore CLI 已安裝後，PDF artifact smoke 產出 `/tmp/groovescribe-score/score.pdf`。
- `GS-P1-008`：已有 generated fixture manifest、人工評估 CSV template，並新增兩筆 synthetic true AI 評估與一筆授權真實鼓聲 true AI 評估；synthetic fixtures 輸出品質偏低，授權真實鼓聲 fixture 的 kick/snare 明顯改善但 hi-hat 缺失。
- `GS-P1-009`：`ai_pipeline/RUNTIME.md` 與 `scripts/check_ai_runtime.py` 已能列出 ffmpeg、Demucs、ADTOF template/output verification、MuseScore 與 Python package 狀態；`.venv-ai` runtime check 已回報 true AI pipeline ready，PDF artifact smoke 已產生非空 PDF。

### 2026-06-30 Phase 1 收尾盤點

- PDF smoke：passed with warning。`/opt/homebrew/bin/mscore` 已在 PATH；執行 `scripts/generate_score.py --export-pdf` 後，`/tmp/groovescribe-score/score.pdf` 存在、非空，且 `file` 回報為 1 頁 PDF。若 MuseScore 4.7.3 產生 PDF 後仍以非零狀態結束，`MuseScorePdfExporter` 目前回報 `completed_with_warning`；缺檔或空 PDF 仍是 `failed`。
- Fixture 覆蓋：新增 `tests/pipeline/fixtures/audio/synthetic_separated_kick_snare_hat_pattern.wav`，為程式生成、無第三方音源的 sparse kick/snare/hat 分段 fixture；現有 silence / low-confidence / invalid audio fixture 不重複新增。
- Manual eval：`tests/manual_eval/2026-06-30_true_ai_fixture_eval.csv` 已記錄 clean / separated synthetic fixtures 與授權真實鼓聲 fixture。三者 pipeline 均完成；真實鼓聲輸出品質較 synthetic 明顯改善，但仍未完整覆蓋 hi-hat。
- ADTOF 品質診斷：clean fixture raw MIDI 為六筆 note `47` 與一筆 note `35`；separated fixture raw MIDI 為四筆 note `47`。postprocessor 依 GM drum mapping 將 `47` 映射為 tom、`35` 映射為 kick，因此「多數 tom」目前判斷是 ADTOF 對 synthetic timbre 的 raw output 問題，不是 mapping bug。授權真實鼓聲 fixture raw MIDI 為八筆 note `35` 與六筆 note `38`，processed mapping 產出 kick/snare 且無 dropped events，表示 GM kick/snare mapping 正常。
- ADTOF 品質 blocker：已不再缺授權真實鼓聲 smoke fixture，但目前只有一筆外部授權音檔，且 ADTOF 在該 fixture 上未輸出 hi-hat；仍需要更多授權測試音檔與 ground-truth / manual eval criteria 才能判定 MVP 品質門檻。

### 需要手動提供的最小項目

授權真實鼓聲 fixture：

```bash
# Current authorized real-drum smoke fixture:
/Users/zhangzhipeng/MyProject/files/audio/authorized_real_drum_smoke_60s_12s.wav

export GROOVESCRIBE_ADTOF_COMMAND_TEMPLATE="$(pwd)/.venv-ai/bin/adtof --audio {input} --out {output} --device {device} --threshold {threshold}"
PYTHONPATH=. .venv-ai/bin/python scripts/run_local_pipeline.py \
  --input /Users/zhangzhipeng/MyProject/files/audio/authorized_real_drum_smoke_60s_12s.wav \
  --output-dir /tmp/groovescribe-authorized-real-drum-run \
  --demucs-device cpu \
  --adtof-command-template "$GROOVESCRIBE_ADTOF_COMMAND_TEMPLATE" \
  --adtof-device cpu \
  --adtof-threshold 0.5
```

### Phase 2/3 artifact contract handoff（2026-07-01）

- Phase 1 local runner artifact keys 與 backend/worker storage key 已對齊：`normalized_audio`、`drums_stem`、`raw_midi`、`processed_midi`、`drum_events`、`musicxml`、`pdf`、`pipeline_log`。
- `drum_events` storage path 統一為 `jobs/{job_id}/midi/drum_events.json`，與 Phase 1 local runner 的 `midi/drum_events.json` 相同。
- backend / worker 已可表達 job `status`、`stage`、`progress`、error code/message/stage、export status、drum track warnings 與 export download metadata。
- worker mock pipeline 已寫出 `stage_reports`，可表達 per-stage artifacts、reports、warnings、`completed_with_warning` 與 failed stage error；backend 已有 internal pipeline log read model 可讀 Phase 1 `stages` 與 worker `stage_reports`。
- PDF `completed_with_warning` 目前可在 pipeline log/stage report 中表達；Result API 尚未直接外露 stage reports，若要前端顯示需另行設計 response 欄位。

## Ticket 詳細內容

### GS-P1-001 — 建立 Python 專案骨架

**Ticket ID**
GS-P1-001

**Ticket 名稱**
建立 Python 專案骨架

**背景與目的**
建立本地 pipeline POC 的最小 Python 專案結構，讓後續 ffmpeg、Demucs、ADTOF、MIDI 與 notation 任務有共同入口與依賴管理。

**實作範圍**
- 建立 `ai_pipeline/` 或 POC package 結構。
- 建立 Python dependency 管理檔，例如 `pyproject.toml`。
- 定義 `scripts/` 或 CLI entry point 的放置方式。
- 建立基本設定讀取方式，例如 input path、output dir、log level。

**不包含範圍**
- 不建立 FastAPI、Celery、database 或前端。
- 不處理 production Docker image。

**主要修改位置或建議目錄**
- ai_pipeline/
- scripts/
- tests/pipeline/
- pyproject.toml

**輸入**
- Level 1 / Level 2 pipeline 文件。
- Python 版本與套件需求。

**輸出**
- 可安裝的本地 Python 專案。
- 可執行的空 runner 或 smoke command。

**API / Data Model / Storage 關聯**
- 無 API / Data Model。Storage 先使用本地 output folder，後續再抽 StorageAdapter。

**驗收標準**
- 在新環境安裝依賴後可執行 smoke command。
- 目錄結構與 Level 1 `專案目錄結構.md` 不衝突。

**測試要求**
- 執行 basic import test。
- CI 或本機測試確認 package 可載入。

**相依任務**
無

**風險與注意事項**
- 保持 MVP 範圍，避免順手實作多人協作、即時轉譜或線上修譜。

### GS-P1-002 — 建立 ffmpeg 音訊標準化 script

**Ticket ID**
GS-P1-002

**Ticket 名稱**
建立 ffmpeg 音訊標準化 script

**背景與目的**
先用獨立 script 驗證 MP3/WAV 可轉成 pipeline 統一輸入 `normalized.wav`。

**實作範圍**
- 建立 `normalize_audio` script 或 function。
- 輸入 original audio path 與 output dir。
- 輸出 WAV PCM，建議 44.1 kHz，並寫出 duration、sample_rate、channels metadata。
- 處理 ffmpeg 不存在、解碼失敗、timeout。

**不包含範圍**
- 不做 loudness normalization、降噪、silence trimming。
- 不在 API request 中執行。

**主要修改位置或建議目錄**
- ai_pipeline/preprocessing/
- scripts/run_normalize_audio.py
- tests/pipeline/fixtures/

**輸入**
- MP3 或 WAV 檔案。
- target output directory。

**輸出**
- `normalized.wav`。
- preprocessing metadata JSON 或 log。

**API / Data Model / Storage 關聯**
- 後續會映射到 `AudioFile.normalized_storage_key`；本階段先使用 local output path。

**驗收標準**
- 短 MP3 與 WAV 均可轉出可讀 WAV。
- 損壞音檔回傳明確錯誤。

**測試要求**
- 用短 MP3 / WAV fixture 跑整合測試。
- 測試 ffmpeg command failure 與 timeout。

**相依任務**
GS-P1-001

**風險與注意事項**
- 保持 MVP 範圍，避免順手實作多人協作、即時轉譜或線上修譜。

### GS-P1-003 — 整合 Demucs 鼓軌分離

**Ticket ID**
GS-P1-003

**Ticket 名稱**
整合 Demucs 鼓軌分離

**背景與目的**
驗證 `normalized.wav` 能透過 Demucs 產出 `drums.wav`，並保留未來替換 SourceSeparator 的邊界。

**實作範圍**
- 建立 Demucs POC wrapper。
- 輸入 normalized WAV path。
- 輸出 drums stem 到 output dir。
- 記錄 Demucs model name、device、runtime。
- 驗證 drums.wav 存在、可讀、duration 合理。

**不包含範圍**
- 不保存 vocals / bass / other stems 給使用者。
- 不做多模型 source separation。

**主要修改位置或建議目錄**
- ai_pipeline/source_separation/
- scripts/run_demucs_separation.py
- tests/pipeline/

**輸入**
- `normalized.wav`。
- Demucs model / device config。

**輸出**
- `drums.wav`。
- source separation report。

**API / Data Model / Storage 關聯**
- 未來對應 `DrumTrack.drums_stem_storage_key`；本階段用 local artifact。

**驗收標準**
- 短音檔可產生 drums.wav。
- Demucs output 缺檔時有明確錯誤。

**測試要求**
- Mock Demucs output 測 wrapper。
- 手動 slow test 實跑 Demucs 短音檔。

**相依任務**
GS-P1-002, GS-P1-009

**風險與注意事項**
- 保持 MVP 範圍，避免順手實作多人協作、即時轉譜或線上修譜。

### GS-P1-004 — 整合 ADTOF-pytorch 鼓 MIDI 轉寫

**Ticket ID**
GS-P1-004

**Ticket 名稱**
整合 ADTOF-pytorch 鼓 MIDI 轉寫

**背景與目的**
驗證 `drums.wav` 可透過 ADTOF-pytorch 轉成 `raw_drum.mid`。

**實作範圍**
- 建立 ADTOF POC wrapper。
- 輸入 drums WAV path。
- 輸出 raw MIDI。
- 記錄 model checkpoint、device、runtime。
- 驗證 MIDI 可 parse 且事件數合理。

**不包含範圍**
- 不實作 Omnizart fallback。
- 不把 threshold 調整做成 UI。

**主要修改位置或建議目錄**
- ai_pipeline/transcription/
- scripts/run_adtof_transcription.py
- tests/pipeline/

**輸入**
- `drums.wav`。
- ADTOF model config。

**輸出**
- `raw_drum.mid`。
- transcription report。

**API / Data Model / Storage 關聯**
- 未來對應 `DrumTrack.raw_midi_storage_key` 與 `TranscriptionJob.drum_transcriber_version`。

**驗收標準**
- 短 drums.wav 可產生可 parse MIDI。
- 空 MIDI 或無事件要被偵測。

**測試要求**
- Mock ADTOF output 測 wrapper。
- slow test 實跑短 drums.wav。

**相依任務**
GS-P1-003, GS-P1-009

**風險與注意事項**
- 保持 MVP 範圍，避免順手實作多人協作、即時轉譜或線上修譜。

### GS-P1-005 — 建立 MIDI 後處理初版

**Ticket ID**
GS-P1-005

**Ticket 名稱**
建立 MIDI 後處理初版

**背景與目的**
將 raw MIDI 清理為使用者可下載與 notation 可消費的 processed MIDI 與 drum event JSON。

**實作範圍**
- 解析 raw MIDI note events。
- 套用 General MIDI drum mapping。
- 建立量化到 16 分音符的初版策略。
- 合併同一鼓件極短時間重複事件。
- 產生 `processed_drum.mid` 與 `drum_events.json`。

**不包含範圍**
- 不做完整 tempo map。
- 不處理左右手 sticking 或 ghost note 精修。

**主要修改位置或建議目錄**
- ai_pipeline/midi/
- tests/unit/midi/
- tests/pipeline/

**輸入**
- `raw_drum.mid`。
- quantize grid、dedupe window、mapping table。

**輸出**
- `processed_drum.mid`。
- `drum_events.json`。
- post-processing report。

**API / Data Model / Storage 關聯**
- 未來對應 `DrumTrack.processed_midi_storage_key`、`drum_events_storage_key`、`event_count`、`warnings`。

**驗收標準**
- processed MIDI 可 parse。
- drum_events JSON schema 穩定。
- kick/snare/hat mapping 有測試。

**測試要求**
- 單元測試 mapping、quantization、dedupe。
- 整合測試 raw MIDI 到 processed MIDI。

**相依任務**
GS-P1-004

**風險與注意事項**
- 保持 MVP 範圍，避免順手實作多人協作、即時轉譜或線上修譜。

### GS-P1-006 — 建立 MusicXML / PDF 輸出初版

**Ticket ID**
GS-P1-006

**Ticket 名稱**
建立 MusicXML / PDF 輸出初版

**背景與目的**
從 drum event JSON 或 processed MIDI 產生簡單鼓譜 MusicXML，並嘗試轉出 PDF。

**實作範圍**
- 建立 notation event model。
- 產生 percussion staff MusicXML。
- 預設 4/4，寫入 estimated BPM if available。
- 整合 music21 或自訂 MusicXML generator。
- 整合 MuseScore CLI 或 headless renderer 產生 PDF。

**不包含範圍**
- 不做出版級 engraving。
- 不做線上譜面編輯。

**主要修改位置或建議目錄**
- ai_pipeline/notation/
- scripts/generate_score.py
- tests/pipeline/

**輸入**
- `drum_events.json` 或 `processed_drum.mid`。
- title、BPM、time signature。

**輸出**
- `score.musicxml`。
- `score.pdf`。

**API / Data Model / Storage 關聯**
- 未來對應 `ExportFile(type=musicxml|pdf)`。

**驗收標準**
- MusicXML 可 parse。
- PDF 可打開；若 PDF renderer 不可用，需回報明確錯誤。

**測試要求**
- MusicXML XML parse test。
- 手動用 MuseScore 開啟 MusicXML。
- PDF smoke test。

**相依任務**
GS-P1-005

**風險與注意事項**
- 保持 MVP 範圍，避免順手實作多人協作、即時轉譜或線上修譜。

### GS-P1-007 — 建立本地 pipeline runner

**Ticket ID**
GS-P1-007

**Ticket 名稱**
建立本地 pipeline runner

**背景與目的**
把 Phase 1 各 POC script 串成單一 runner，形成可重現端到端流程。

**實作範圍**
- 建立 `run_local_pipeline`。
- 輸入 audio path 與 output dir。
- 依序執行 normalize、Demucs、ADTOF、MIDI post-processing、notation、PDF。
- 每個 stage 寫出 log 與 artifact。
- 任一 stage 失敗時停止並回傳失敗階段。

**不包含範圍**
- 不接 queue、database、API。
- 不做多檔批次。

**主要修改位置或建議目錄**
- scripts/run_local_pipeline.py
- ai_pipeline/
- storage/local_poc/

**輸入**
- MP3 / WAV path。
- output directory。
- pipeline config。

**輸出**
- 完整 artifacts 資料夾。
- pipeline log。

**API / Data Model / Storage 關聯**
- Artifact 命名需對齊未來 storage key：normalized.wav、drums.wav、raw_drum.mid、processed_drum.mid、score.musicxml、score.pdf。

**驗收標準**
- 一個指令可完成端到端處理。
- 失敗時可看出 stage 與錯誤摘要。

**測試要求**
- 對短 fixture 跑端到端 smoke test。
- 故意缺 Demucs output 測失敗處理。

**相依任務**
GS-P1-002, GS-P1-003, GS-P1-004, GS-P1-005, GS-P1-006

**風險與注意事項**
- 保持 MVP 範圍，避免順手實作多人協作、即時轉譜或線上修譜。

### GS-P1-008 — 準備測試音檔與人工檢查表

**Ticket ID**
GS-P1-008

**Ticket 名稱**
準備測試音檔與人工檢查表

**背景與目的**
建立 MVP pipeline QA 的最小資料集與人工檢查格式，避免只靠主觀印象驗收。

**實作範圍**
- 準備 3-5 個短音檔：乾淨鼓軌、一般完整歌曲、鼓聲不明顯、損壞或無效音檔。
- 建立人工檢查表欄位：kick/snare/hi-hat 分數、notation readability、overall usability。
- 記錄每個 fixture 的來源、授權與用途。

**不包含範圍**
- 不建立大型 benchmark。
- 不上傳未授權商用音源到 repo。

**主要修改位置或建議目錄**
- tests/fixtures/audio/
- tests/manual_eval/
- docs/03_工程實作任務/

**輸入**
- 測試音檔。
- 人工評估欄位定義。

**輸出**
- fixture manifest。
- manual evaluation template。

**API / Data Model / Storage 關聯**
- 無 API；測試資料不要進 production storage。

**驗收標準**
- 工程師可用同一批音檔重跑 regression。
- 人工檢查表可追蹤每次輸出品質。

**測試要求**
- 檢查 fixture manifest 完整。
- 至少一首音檔跑過 GS-P1-007。

**相依任務**
GS-P1-007

**風險與注意事項**
- 保持 MVP 範圍，避免順手實作多人協作、即時轉譜或線上修譜。

### GS-P1-009 — 鎖定 AI runtime 與安裝重現紀錄

**Ticket ID**
GS-P1-009

**Ticket 名稱**
鎖定 AI runtime 與安裝重現紀錄

**背景與目的**
Demucs 與 ADTOF-pytorch 的安裝、PyTorch / CUDA 版本、模型 checkpoint 與 CPU/GPU 執行方式會直接影響 pipeline 可重現性。本 ticket 先在 POC 階段鎖定最小可行 runtime，避免後續 worker / Docker 化時重新踩環境問題。

**實作範圍**
- 記錄 Python 版本、ffmpeg 版本、PyTorch 版本、Demucs 版本、ADTOF-pytorch 來源與版本。
- 記錄模型 checkpoint 來源、檔案位置、下載或安裝方式。
- 記錄 CPU / GPU 啟動命令與已知限制。
- 建立本地安裝重現文件或 lockfile 說明。
- 補上最小 smoke command：確認 ffmpeg、Demucs、ADTOF 可被呼叫。

**不包含範圍**
- 不建立 production Docker image。
- 不處理 GPU autoscaling。
- 不建立模型 registry 或自動下載平台。

**主要修改位置或建議目錄**
- docs/03_工程實作任務/
- ai_pipeline/
- scripts/
- infra/docker/notes 或等效文件

**輸入**
- Phase 1 POC 依賴。
- Demucs / ADTOF-pytorch 安裝方式。
- 本地 CPU / GPU 環境資訊。

**輸出**
- AI runtime 版本與安裝重現紀錄。
- 模型 checkpoint 紀錄。
- CPU / GPU smoke command。

**API / Data Model / Storage 關聯**
- 無 API / Data Model 直接影響。
- 後續會支援 `TranscriptionJob.source_separator_version`、`drum_transcriber_version` 與 `pipeline_version` 的實作。

**驗收標準**
- 新工程師可依文件安裝 Phase 1 所需 AI runtime。
- smoke command 可確認 ffmpeg、Demucs、ADTOF-pytorch 都可被呼叫。
- 文件明確列出 CPU 可跑但較慢、GPU 建議與版本限制。
- 模型 checkpoint 來源與路徑可追蹤。

**測試要求**
- 手動 smoke test：`ffmpeg` 可執行。
- 手動 smoke test：Demucs 可對短音檔產生 stems。
- 手動 smoke test：ADTOF-pytorch 可對短 drums.wav 產生 raw MIDI。
- 記錄 smoke test 執行日期、環境與結果。

**相依任務**
GS-P1-001

**風險與注意事項**
- 這張 ticket 的輸出是可重現環境紀錄，不是正式部署映像；production Docker 仍由 Phase 8 處理。

## Phase 完成標準

- 本地 runner 可用一個指令處理單首音檔。
- 輸出資料夾包含 normalized.wav、drums.wav、raw_drum.mid、processed_drum.mid、drum_events.json、score.musicxml、score.pdf。
- 至少一首乾淨鼓軌能產生可用的 kick / snare / hi-hat 草稿。
- 所有步驟有 README 或命令說明，可由另一位工程師重現。
