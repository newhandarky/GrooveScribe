# MIDI 後處理與量化規格

> Level 2 功能細部設計。本文延伸 Level 1 產品與系統架構文件，不取代既有規劃。

## 功能目標

- 將 `raw_drum.mid` 轉成更適合使用者下載與產生鼓譜的 `processed_drum.mid`。
- 建立標準化 `drum_events.json` 作為 MusicXML、PDF、debug 與未來編輯器的共同資料來源。
- 處理 tempo 對齊、量化、鼓件 mapping、重複事件合併與 velocity cleanup。

## 使用者情境

- 使用者下載的 MIDI 應能匯入 DAW，並大致對齊拍點。
- 使用者看到的鼓譜不應因 raw MIDI 微小 timing jitter 而產生難讀節奏。

## 前端行為

- 前端不做 MIDI 後處理。
- 當 stage 為 `midi_post_processing` 時顯示「正在整理鼓點」。
- 結果頁顯示 warnings，例如 hi-hat 開閉不保證、cymbal 已簡化。

## 後端行為

- Result API 回傳 `estimated_bpm`、`time_signature`、`event_count`、`confidence_label`、`warnings`。
- Download MIDI API 提供 processed MIDI，不提供 raw MIDI。

## Worker / Pipeline 行為

- 使用 `MidiPostProcessor.process(raw_midi, audio_metadata, config) -> MidiPostProcessResult`。
- 解析 raw MIDI note events，轉成內部 event model。
- 預設拍號為 4/4；BPM 可由 MIDI tempo、簡化 beat tracking 或 fallback 預設值取得。
- 預設量化 grid 為 16 分音符；極慢或極快歌曲可依 config 改為 8 分或 32 分。
- 套用 General MIDI drum mapping：kick 36、snare 38、closed hat 42、tom/cymbal 使用簡化 mapping。
- 合併同一鼓件在極短時間窗內的重複事件，過低 velocity noise 可過濾或降權。

## 輸入資料

- `raw_drum.mid` artifact ref。
- Audio metadata：duration、estimated BPM if available。
- Post-processing config：quantize grid、dedupe window、velocity floor、mapping table。

## 輸出資料

- `processed_drum.mid`。
- `drum_events.json`。
- post-processing report：event count、dropped events、warnings、estimated BPM。

## API 關聯

- `GET /api/v1/transcriptions/{job_id}` 回傳後處理摘要。
- `GET /api/v1/transcriptions/{job_id}/download/midi` 回傳 processed MIDI。

## Data Model 關聯

- `DrumTrack.processed_midi_storage_key`。
- `DrumTrack.drum_events_storage_key`。
- `DrumTrack.estimated_bpm`、`time_signature`、`event_count`、`confidence_label`、`warnings`。
- `ExportFile(type=midi)`。

## Storage / Artifact 關聯

- 輸入：`jobs/{job_id}/midi/raw_drum.mid`。
- 輸出：`jobs/{job_id}/midi/processed_drum.mid`。
- 輸出：`jobs/{job_id}/midi/drum_events.json`。
- Log：post-processing report。

## 狀態流轉

```text
drum_transcription completed → midi_post_processing started → processed_drum.mid written → drum_events.json written → notation_generation
```

## 錯誤情境

- `RAW_MIDI_INVALID`: raw MIDI 無法 parse。
- `MIDI_POST_PROCESSING_FAILED`: 後處理發生未分類錯誤。
- `NO_USABLE_DRUM_EVENTS`: 沒有可用事件；可 failed 或 completed with low confidence，需依產品策略固定。
- `PROCESSED_MIDI_INVALID`: 輸出 MIDI 無法 parse。

## 驗收標準

- 合法 raw MIDI 可產生 processed MIDI 與 drum events JSON。
- processed MIDI 可被常見 MIDI parser 讀取。
- drum events JSON schema 穩定，notation generator 可消費。
- 重複事件合併與 mapping 有單元測試覆蓋。

## 測試案例

- 單元測試：kick/snare/hat mapping。
- 單元測試：量化到 16 分音符。
- 單元測試：dedupe window 合併重複事件。
- 單元測試：velocity floor 過濾 noise。
- 整合測試：raw MIDI → processed MIDI → drum_events.json。

## 非 MVP 範圍

- 複雜 tempo map。
- ghost note 精細保留策略。
- 左右手 sticking 推論。
- 使用者可調量化 UI。

## 未來擴充方向

- 加入 beat tracking 與 tempo map。
- 加入 per-instrument confidence。
- 支援使用者在前端重新量化。
- 加入更細緻 tom / cymbal / open hat mapping。
