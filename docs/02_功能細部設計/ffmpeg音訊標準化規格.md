# ffmpeg 音訊標準化規格

> Level 2 功能細部設計。本文延伸 Level 1 產品與系統架構文件，不取代既有規劃。

## 功能目標

- 將使用者上傳的 MP3 / WAV 轉成 pipeline 統一輸入格式 `normalized.wav`。
- 隔離 `ffmpeg` 操作於 Audio Preprocessing Module，避免其他模組直接操作轉檔命令。
- 產生可被 Demucs 穩定讀取的 WAV artifact 與 metadata。

## 使用者情境

- 使用者上傳任意合法 MP3 / WAV，不需要知道 sample rate 或聲道數。
- 若音檔損壞或不可解析，結果頁顯示「音檔無法處理，請確認檔案可正常播放」。

## 前端行為

- 前端不執行音訊標準化。
- 在 processing stage 為 `preprocessing` 時顯示「正在準備音檔」。
- 若失敗，顯示後端提供的錯誤訊息。

## 後端行為

- Upload API 可做 metadata 預檢，但不執行完整轉檔。
- API 不依賴 ffmpeg runtime；ffmpeg runtime 屬於 worker / ai_pipeline 環境。

## Worker / Pipeline 行為

- Worker 進入 `preprocessing` stage 後，從 storage 讀取 original artifact 到 job-scoped temp path。
- 透過 `AudioPreprocessor.normalize(input_artifact, config) -> NormalizedAudioResult` 呼叫 ffmpeg adapter。
- 輸出 WAV PCM，V1 建議 44.1 kHz；聲道可先保留 stereo，若 Demucs adapter 要求可轉換。
- 標準化完成後驗證檔案存在、duration 合理、可被 decoder 讀取。
- 寫入 `AudioFile.normalized_storage_key`、`duration_seconds`、`sample_rate`、`channels`。

## 輸入資料

- original audio artifact ref。
- 音訊標準化 config：target sample rate、channel policy、container、codec。
- job id 與 temp directory。

## 輸出資料

- `normalized.wav`。
- preprocessing metadata：duration、sample_rate、channels、format、ffmpeg version。
- preprocessing report，可寫入 pipeline log。

## API 關聯

- 沒有直接 API。
- Status API 在此階段回傳 `stage=preprocessing`。
- 錯誤會透過 status API 的 error 欄位呈現。

## Data Model 關聯

- `AudioFile.normalized_storage_key`。
- `AudioFile.duration_seconds`、`sample_rate`、`channels`。
- `TranscriptionJob.stage=preprocessing`、`progress≈10`。

## Storage / Artifact 關聯

- 輸入：`jobs/{job_id}/original/{filename}`。
- 輸出：`jobs/{job_id}/audio/normalized.wav`。
- log：`jobs/{job_id}/logs/pipeline.json` 中加入 preprocessing entry。

## 狀態流轉

```text
processing/source=queued → preprocessing started → normalized.wav written → preprocessing completed → source_separation
```

## 錯誤情境

- `FFMPEG_NOT_AVAILABLE`: worker 環境找不到 ffmpeg。
- `AUDIO_DECODE_FAILED`: 原始檔無法解碼。
- `AUDIO_TOO_LONG`: duration 超過 V1 限制。
- `NORMALIZED_AUDIO_INVALID`: 轉出 WAV 不存在、大小為 0 或不可讀。
- `PREPROCESSING_TIMEOUT`: ffmpeg 超時。

## 驗收標準

- 合法 MP3 / WAV 可產生 `normalized.wav`。
- 輸出 duration 與原始音檔接近。
- 損壞音檔不會進入 Demucs stage。
- 所有錯誤都能標記 job failed 並寫入 error stage。

## 測試案例

- 單元測試：ffmpeg adapter command config 組裝。
- 整合測試：短 MP3 轉成 WAV。
- 整合測試：短 WAV 轉成 normalized WAV。
- 錯誤測試：損壞音檔回傳 `AUDIO_DECODE_FAILED`。
- 錯誤測試：ffmpeg process timeout。

## 非 V1 範圍

- 進階 loudness normalization。
- 自動降噪。
- 去人聲或 EQ enhancement。
- 瀏覽器端音訊轉碼。

## 未來擴充方向

- 加入 loudness normalization。
- 加入 silence trimming。
- 依模型需求切換 sample rate 與 channel policy。
- 保存 waveform preview artifact。
