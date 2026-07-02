# Demucs 鼓軌分離規格

> Level 2 功能細部設計。本文延伸 Level 1 產品與系統架構文件，不取代既有規劃。

## 功能目標

- 使用 Demucs adapter 從 `normalized.wav` 分離出 `drums.wav`。
- 將 source separation 與業務邏輯解耦，未來可替換成其他模型。
- 讓 ADTOF-pytorch 接收較乾淨的 drums stem，降低完整混音干擾。

## 使用者情境

- 使用者上傳完整歌曲，系統自動分離鼓軌，不要求使用者提供單獨鼓軌。
- 若分離失敗，結果頁顯示「無法從音檔分離鼓聲」。

## 前端行為

- 當 status stage 為 `source_separation` 時顯示「正在分離鼓軌」。
- 不提供 Demucs 參數選擇 UI。
- 失敗時顯示可重試提示，避免承諾結果必然準確。

## 後端行為

- API 層不引用 Demucs。
- Result API 可回傳 warnings，例如 `drums_stem_low_energy`，但不暴露內部 model command。

## Worker / Pipeline 行為

- 透過 `SourceSeparator.separate(input_audio, config) -> StemSet` interface 呼叫 Demucs adapter。
- Demucs adapter 負責模型選擇、device 選擇、temp output directory 與 stderr/stdout 摘要。
- V1 只保存 drums stem；其他 stems 可不保存。
- 完成後執行 stem validation：檔案存在、可讀、duration 接近 normalized audio、RMS 不異常低。
- 更新 `TranscriptionJob.source_separator=demucs` 與 version metadata。

## 輸入資料

- `normalized.wav` artifact ref。
- Demucs config：model name、device、output stem policy、timeout。
- Audio metadata：duration。

## 輸出資料

- `drums.wav`。
- `source_separation_report.json` 或 pipeline log entry。
- Stem validation 結果與 warnings。

## API 關聯

- 沒有直接 API。
- Status API 顯示 `stage=source_separation` 或 `stage=stem_validation`。
- 失敗後 status API 回傳 source separation 相關錯誤。

## Data Model 關聯

- `TranscriptionJob.source_separator`、`source_separator_version`。
- `DrumTrack.drums_stem_storage_key`。
- `DrumTrack.warnings` 可包含 `drums_stem_low_energy` 或 `source_separation_artifacts_possible`。

## Storage / Artifact 關聯

- 輸入：`jobs/{job_id}/audio/normalized.wav`。
- 輸出：`jobs/{job_id}/stems/drums.wav`。
- 可選 log：Demucs command summary、runtime、device、model name。

## 狀態流轉

```text
preprocessing completed → source_separation started → drums.wav written → stem_validation → drum_transcription
```

## 錯誤情境

- `SOURCE_SEPARATOR_NOT_AVAILABLE`: Demucs runtime 不可用。
- `SOURCE_SEPARATION_FAILED`: Demucs process 非 0 exit。
- `DRUMS_STEM_NOT_FOUND`: 找不到 drums stem。
- `DRUMS_STEM_INVALID`: stem 不可讀或 duration 不合理。
- `DRUMS_STEM_LOW_ENERGY`: stem 幾乎無聲，可標記 low confidence 或 failed。

## 驗收標準

- 給定 normalized WAV，能產生可讀 `drums.wav`。
- Demucs 失敗時 job 不會進入 ADTOF stage。
- Demucs adapter 可被 mock 替換。
- 模型版本與 runtime metadata 被記錄。

## 測試案例

- 單元測試：SourceSeparator interface contract。
- 整合測試：mock Demucs 產生 drums.wav。
- Slow test：實際 Demucs 處理短音檔。
- 錯誤測試：Demucs output 缺 drums stem。
- Validation test：drums.wav duration 與 normalized.wav 差距過大。

## 非 V1 範圍

- 保存 vocals、bass、other stems 給使用者下載。
- 讓使用者選 Demucs model。
- 多模型 source separation 比較。
- 分離品質人工調整 UI。

## 未來擴充方向

- 加入替代 SourceSeparator adapter。
- 對低品質 stem 執行 enhancement。
- 依音檔長度自動選 CPU / GPU queue。
- 保存 stem preview 供 debug 或內部 QA。
