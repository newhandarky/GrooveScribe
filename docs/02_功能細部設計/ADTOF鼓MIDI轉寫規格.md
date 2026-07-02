# ADTOF 鼓 MIDI 轉寫規格

> Level 2 功能細部設計。本文延伸 Level 1 產品與系統架構文件，不取代既有規劃。

## 功能目標

- 使用 ADTOF-pytorch adapter 將 `drums.wav` 轉成 `raw_drum.mid`。
- 將 drum transcription model 包在 `DrumTranscriber` interface 後，避免 worker 與業務邏輯直接依賴模型實作。
- 保留 raw MIDI 作為後處理與 debug 的基礎。

## 使用者情境

- 使用者等待系統分析鼓軌並產生可匯入 DAW 的鼓 MIDI 草稿。
- 若鼓聲太弱或模型無法產生有效 MIDI，結果頁顯示失敗或低信心提示。

## 前端行為

- 當 stage 為 `drum_transcription` 時顯示「正在辨識鼓點」。
- 前端不顯示模型名稱作為主要使用者資訊；可在內部 debug 頁顯示。
- 若失敗，顯示重新上傳較清楚音檔或較短片段的建議。

## 後端行為

- API 層不 import ADTOF-pytorch。
- Result API 只回傳摘要：event_count、confidence_label、warnings。
- Download API 不提供 raw MIDI，V1 只提供 processed MIDI；raw MIDI 保留供內部 debug。

## Worker / Pipeline 行為

- 透過 `DrumTranscriber.transcribe(drums_audio, config) -> TranscriptionResult` 呼叫 ADTOF adapter。
- Adapter 負責模型載入、device 選擇、checkpoint path、輸出 MIDI 驗證。
- 輸出 raw MIDI 後，立即解析 event count；若 event count 為 0 或極低，標記 low confidence 或 failed。
- 更新 `TranscriptionJob.drum_transcriber=adtof-pytorch` 與 version metadata。
- 將 raw MIDI 寫入 storage，不覆蓋 processed MIDI。

## 輸入資料

- `drums.wav` artifact ref。
- ADTOF config：model checkpoint、device、threshold、timeout。
- Stem validation metadata。

## 輸出資料

- `raw_drum.mid`。
- `drum_transcription_report.json` 或 pipeline log entry。
- 初步 model warnings，例如 `low_event_count`。

## API 關聯

- 沒有直接 API。
- Status API 顯示 `stage=drum_transcription`。
- Result API 的 `DrumTrack.event_count` 最終來自 raw MIDI 後處理後的事件統計。

## Data Model 關聯

- `TranscriptionJob.drum_transcriber`、`drum_transcriber_version`。
- `DrumTrack.raw_midi_storage_key`。
- `DrumTrack.confidence_label` 與 `warnings`。

## Storage / Artifact 關聯

- 輸入：`jobs/{job_id}/stems/drums.wav`。
- 輸出：`jobs/{job_id}/midi/raw_drum.mid`。
- log：模型名稱、版本、device、runtime、event count。

## 狀態流轉

```text
stem_validation completed → drum_transcription started → raw_drum.mid written → raw MIDI validation → midi_post_processing
```

## 錯誤情境

- `DRUM_TRANSCRIBER_NOT_AVAILABLE`: ADTOF runtime 不可用。
- `DRUM_TRANSCRIPTION_FAILED`: 模型執行失敗。
- `RAW_MIDI_NOT_FOUND`: 未產生 MIDI。
- `RAW_MIDI_INVALID`: MIDI 無法解析。
- `RAW_MIDI_EMPTY`: 幾乎沒有鼓點事件。

## 驗收標準

- 給定有效 drums.wav，能產生可 parse 的 raw MIDI。
- ADTOF adapter 可被 mock 替換。
- raw MIDI artifact 被保留。
- 低事件數或空 MIDI 有明確警告或錯誤。

## 測試案例

- 單元測試：DrumTranscriber interface contract。
- 整合測試：mock ADTOF 產生 raw MIDI。
- Slow test：實際 ADTOF 處理短 drums.wav。
- 錯誤測試：模型 process 非 0 exit。
- Validation test：raw MIDI 無 note event。

## 非 V1 範圍

- 多模型 ensemble。
- 線上調整 threshold。
- 直接輸出每個事件 confidence 到使用者 UI。
- 使用者上傳自己的模型 checkpoint。

## 未來擴充方向

- 加入 Omnizart adapter 作 fallback。
- 保存 per-event confidence。
- 依曲風或 stem 品質選擇不同 transcriber。
- 建立人工標註 benchmark 追蹤模型表現。
