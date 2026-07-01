# 檔案儲存與 Artifact 規格

> Level 2 功能細部設計。本文延伸 Level 1 產品與系統架構文件，不取代既有規劃。

## 功能目標

- 定義所有 pipeline 檔案與中間產物的儲存方式。
- MVP 先支援 local filesystem，但介面必須可替換成 S3-compatible storage。
- 避免 API、worker、pipeline 直接依賴絕對路徑。

## 使用者情境

- 使用者只看得到下載 URL，不知道內部 storage key。
- 使用者重新整理結果頁後，仍可取得已完成 job 的輸出檔。

## 前端行為

- 前端只使用 API 回傳的 `download_url` 或 `musicxml_url`。
- 前端不可假設檔案實體路徑或 storage provider。
- 下載失敗時顯示 API 錯誤訊息。

## 後端行為

- 實作 `StorageAdapter`，提供 put、get、exists、delete optional、create_download_url 或 stream。
- Upload API 使用 adapter 保存 original audio。
- Download API 使用 adapter 讀取 ExportFile.storage_key。
- 禁止將 local absolute path 寫入 API response。

## Worker / Pipeline 行為

- Worker 從 storage 取 artifact 到 job-scoped temp directory，stage 完成後再 put 回 storage。
- Pipeline stage 之間以 `ArtifactRef` 或 storage key 傳遞，不以任意 temp path 傳遞跨 stage 產物。
- 每個 artifact 保存 content type、size、producing stage、created_at。
- 清理 temp directory 不可刪除 storage 中的正式 artifact。

## 輸入資料

- Artifact stream 或 local temp file。
- Artifact metadata：job_id、artifact_type、content_type、filename。
- Storage config：local root 或 S3 bucket / prefix。

## 輸出資料

- `ArtifactRef`：storage_key、content_type、file_size_bytes、checksum optional。
- 可下載 URL 或 API stream response。
- Artifact log entry。

## API 關聯

- Upload API put original artifact。
- Download API get export artifact。
- Result API 回傳 download API URL，不直接回傳 storage key。

## Data Model 關聯

- `AudioFile.original_storage_key`、`normalized_storage_key`。
- `DrumTrack.drums_stem_storage_key`、`raw_midi_storage_key`、`processed_midi_storage_key`、`drum_events_storage_key`。
- `ExportFile.storage_key`、`content_type`、`file_size_bytes`、`checksum`。

## Storage / Artifact 關聯

建議 key：

```text
jobs/{job_id}/original/{filename}
jobs/{job_id}/audio/normalized.wav
jobs/{job_id}/stems/drums.wav
jobs/{job_id}/midi/raw_drum.mid
jobs/{job_id}/midi/processed_drum.mid
jobs/{job_id}/midi/drum_events.json
jobs/{job_id}/notation/score.musicxml
jobs/{job_id}/exports/score.pdf
jobs/{job_id}/logs/pipeline.json
```

## 狀態流轉

- Artifact 本身不主導 job 狀態，但每個 stage 完成前必須先成功寫入必要 artifact。
- 必要 artifact 寫入失敗時，該 stage 失敗並更新 job failed。
- ExportFile 狀態可為 `available` 或 `failed`。

## 錯誤情境

- `STORAGE_WRITE_FAILED`: put 失敗。
- `STORAGE_READ_FAILED`: get 失敗。
- `ARTIFACT_NOT_FOUND`: storage key 不存在。
- `ARTIFACT_INVALID`: 檔案存在但大小為 0 或 checksum 不符。
- `PATH_TRAVERSAL_REJECTED`: 嘗試使用不安全檔名或 key。

## 驗收標準

- LocalStorageAdapter 可保存與讀取所有 MVP artifact。
- 所有 API response 不含 local absolute path。
- Storage key 命名一致且以 job id 隔離。
- 替換成 S3StorageAdapter 時不需修改業務流程。

## 測試案例

- 單元測試：storage key sanitizer。
- 單元測試：put/get/exists。
- 安全測試：`../` 檔名被拒絕或 sanitize。
- 整合測試：upload original 後 worker 可讀取。
- 整合測試：download API 從 ExportFile.storage_key 回傳檔案。

## 非 MVP 範圍

- S3 direct upload。
- 檔案生命週期自動清理 UI。
- 跨區域 storage replication。
- 使用者自訂保留期限。

## 未來擴充方向

- 實作 S3StorageAdapter。
- 加入 signed URL download。
- 加入 scheduled cleanup job。
- 加入 artifact checksum 與完整性稽核。
