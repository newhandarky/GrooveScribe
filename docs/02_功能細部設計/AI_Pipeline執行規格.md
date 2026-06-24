# AI Pipeline 執行規格

> Level 2 功能細部設計。本文延伸 Level 1 產品與系統架構文件，不取代既有規劃。

## 功能目標

- 定義 worker 如何 orchestration 完整 pipeline：preprocessing、source separation、stem validation、drum transcription、MIDI post-processing、notation generation、PDF export。
- 確保每個 stage 都有明確輸入 artifact、輸出 artifact、錯誤碼與可替換 adapter。
- 讓 pipeline 可被 CLI、worker、tests 重複使用，不依賴 FastAPI request / response。

## 使用者情境

- 使用者不需要理解 pipeline 細節，只透過結果頁看到目前階段。
- 當 pipeline 完成，使用者取得 MIDI、MusicXML、PDF 與網頁預覽。
- 當 pipeline 失敗，使用者看到哪個階段失敗與建議處理方式。

## 前端行為

- 前端不直接呼叫 pipeline。
- 只根據 status API 的 `stage` 顯示人類可讀訊息。
- 完成前不可顯示下載按鈕；若 PDF 部分失敗，可顯示 MIDI / MusicXML 可下載、PDF 暫不可用。

## 後端行為

- API server 只建立 job 與 queue task。
- Result API 從 database 組合 `DrumTrack` 與 `ExportFile` metadata，不執行任何 pipeline stage。
- Download API 透過 Storage Adapter 讀取已產生 artifact。

## Worker / Pipeline 行為

- Pipeline runner 以 `job_id` 為入口，讀取 `AudioFile.original_storage_key`。
- 每個 stage 使用獨立 service 或 adapter：`AudioPreprocessor`、`SourceSeparator`、`DrumTranscriber`、`MidiPostProcessor`、`NotationGenerator`、`PdfExporter`。
- 每個 stage 完成後立即保存 artifact 與 metadata，避免後續失敗時無法 debug。
- Pipeline runner 不直接知道 Demucs 或 ADTOF 的 CLI 細節，只依賴 interface。
- 所有暫存檔必須位於 job-scoped temp directory，完成後可清理，但 storage artifacts 不可刪除。

## 輸入資料

- `job_id`。
- `AudioFile.original_storage_key`。
- Pipeline config：模型名稱、模型版本、量化 grid、預設拍號、PDF renderer。
- Storage adapter 與 database session。

## 輸出資料

- `normalized.wav`、`drums.wav`、`raw_drum.mid`、`processed_drum.mid`、`drum_events.json`、`score.musicxml`、`score.pdf`。
- `DrumTrack` 紀錄與 `ExportFile` 紀錄。
- `pipeline.json` log 與 warnings。

## API 關聯

- Pipeline 不提供 HTTP API。
- 其輸出由 result API 與 download API 消費。
- Status API 的 stage / progress 由 pipeline runner 寫入 database。

## Data Model 關聯

- `TranscriptionJob.pipeline_version`。
- `TranscriptionJob.source_separator`、`source_separator_version`。
- `TranscriptionJob.drum_transcriber`、`drum_transcriber_version`。
- `DrumTrack` 保存 drums stem、raw MIDI、processed MIDI、event JSON 與摘要。
- `ExportFile` 保存 midi、musicxml、pdf 下載檔 metadata。

## Storage / Artifact 關聯

- 所有 stage artifact 都使用 `jobs/{job_id}/...` 命名。
- Raw 與 processed artifact 都保留，不覆蓋。
- Adapter 可使用 local temp path，但跨模組傳遞需使用 `ArtifactRef` 或 storage key。

## 狀態流轉

```text
queued
→ processing/preprocessing
→ processing/source_separation
→ processing/stem_validation
→ processing/drum_transcription
→ processing/midi_post_processing
→ processing/notation_generation
→ processing/pdf_export
→ completed
```

## 錯誤情境

- 任一 stage 找不到輸入 artifact：`PIPELINE_INPUT_MISSING`。
- Adapter 執行失敗：轉換為該 stage 專屬錯誤碼。
- 輸出檔案存在但不可讀：`PIPELINE_OUTPUT_INVALID`。
- PDF export 失敗：可標記 PDF export failed；若 MIDI 與 MusicXML 成功，job 可視產品策略完成但帶 warning。
- 未知錯誤：`PIPELINE_FAILED`，並保存 internal log ref。

## 驗收標準

- 給定一個已存在 original artifact 的 job，pipeline 可完整產生所有 MVP artifacts。
- 每個 stage 都能被單獨 mock 測試。
- Demucs 與 ADTOF adapter 可替換，不影響 API 層。
- 失敗時 database 有 failed status、error code、error stage。

## 測試案例

- Fast pipeline test：mock 所有 adapter，只驗證 orchestration 與 artifact flow。
- Slow pipeline test：對短音檔實際跑 ffmpeg、Demucs、ADTOF。
- 錯誤測試：讓 source separation adapter 拋錯，驗證 job failed。
- artifact 測試：每個 stage output key 符合命名約定。

## 非 MVP 範圍

- 多模型 ensemble。
- 線上人工修譜後重新產生 PDF。
- 曲風自動分類與模型 routing。
- Pipeline DAG 動態編排系統。

## 未來擴充方向

- 加入第二 `DrumTranscriber` adapter，例如 Omnizart。
- 加入 confidence-based fallback。
- 拆分 GPU / CPU queue。
- 加入 pipeline stage cache，避免重跑前面階段。
