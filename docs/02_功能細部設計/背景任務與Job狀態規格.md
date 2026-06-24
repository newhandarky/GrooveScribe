# 背景任務與 Job 狀態規格

> Level 2 功能細部設計。本文延伸 Level 1 產品與系統架構文件，不取代既有規劃。

## 功能目標

- 定義 `TranscriptionJob` 的 queue、worker 執行、stage 更新、progress 與狀態查詢規則。
- 確保長時間 AI pipeline 完全由 background worker 執行，不阻塞 API request。
- 讓前端可以用輪詢方式穩定顯示 queued、processing、completed、failed。

## 使用者情境

- 使用者上傳後進入結果頁，看到「等待處理」、「正在標準化音訊」、「正在分離鼓軌」等階段。
- 任務完成後，使用者看到下載按鈕與譜面預覽。
- 任務失敗時，使用者看到失敗階段與可行下一步，例如重新上傳較清楚音檔。

## 前端行為

- 結果頁每 2 至 5 秒呼叫 `GET /api/v1/transcriptions/{job_id}/status`。
- `queued` 與 `processing` 時顯示 progress bar、stage label、說明訊息。
- `completed` 時停止輪詢並呼叫 result API。
- `failed` 時停止輪詢，顯示 `error.message` 與重新上傳入口。
- 網路暫時失敗時顯示「暫時無法更新狀態」，但不把 job 判定為 failed。

## 後端行為

- 提供 status API，從 `TranscriptionJob` 讀取 status、stage、progress、timestamps、error。
- 提供 result API，只有 `status=completed` 才回傳結果；否則回傳 `409 JOB_NOT_COMPLETED`。
- 避免 status API 查詢 storage 或執行重型計算，只讀 database。
- 定義 stage-to-message mapping，讓 API 回傳穩定且可本地化的訊息。

## Worker / Pipeline 行為

- Worker task payload 只信任 `job_id`，其他資料從 database 重新讀取。
- Worker 開始時將 job 從 `queued` 更新為 `processing`，設定 `started_at`。
- 每個 pipeline stage 開始前更新 `stage` 與 progress 範圍；完成後寫入 artifact metadata。
- 任一未捕捉錯誤需被 error boundary 轉換成 `failed` 狀態，並寫入 `error_code`、`error_message`、`error_stage`。
- GPU worker concurrency 預設為 1，避免 Demucs / ADTOF 同時搶 GPU memory。

## 輸入資料

- Queue task：`job_id`、optional `pipeline_config_id`。
- Database：`TranscriptionJob`、`AudioFile`。
- Storage：original audio artifact。

## 輸出資料

- Job status response。
- `TranscriptionJob` stage / progress / timestamps。
- Pipeline log artifact：`jobs/{job_id}/logs/pipeline.json`。

## API 關聯

- `GET /api/v1/transcriptions/{job_id}/status`。
- `GET /api/v1/transcriptions/{job_id}`。
- `GET /api/v1/transcriptions/{job_id}/download/{type}` 只在 completed 或可用 export 時成功。

## Data Model 關聯

- `TranscriptionJob.status`: uploaded、queued、processing、completed、failed、canceled。
- `TranscriptionJob.stage`: preprocessing、source_separation、stem_validation、drum_transcription、midi_post_processing、notation_generation、pdf_export、completed、failed。
- `TranscriptionJob.progress`: 0-100，不代表精確時間，只代表 stage 進度。
- `TranscriptionJob.error_*` 欄位由 worker 寫入。

## Storage / Artifact 關聯

- Job 狀態以 database 為準，artifact 只保存輸入輸出與 logs。
- 每個 stage 可追加 pipeline log，但 status API 不直接讀 log。
- log artifact 可包含 stage duration、adapter version、artifact keys、warnings。

## 狀態流轉

```text
uploaded → queued → processing → completed
queued → failed
processing → failed
```

Progress 建議：queued 0、preprocessing 10、source_separation 25、stem_validation 45、drum_transcription 60、midi_post_processing 75、notation_generation 88、pdf_export 95、completed 100。

## 錯誤情境

- Worker timeout：`WORKER_TIMEOUT`。
- Queue 消費後找不到 job：記錄 worker error，不建立新 job。
- 狀態非法轉移：拒絕更新並記錄 `INVALID_JOB_STATE_TRANSITION`。
- Worker crash 後 job 長時間停在 processing：由後續 watchdog 或人工操作標記 failed；MVP 可先以 timeout 控制。

## 驗收標準

- Job 狀態可從上傳後一路查到 completed 或 failed。
- AI pipeline 任何階段失敗都不會讓 job 永遠停在 processing。
- Status API response 不暴露 stack trace。
- 前端輪詢可以根據 status 停止。

## 測試案例

- 單元測試：合法與非法狀態轉移。
- 整合測試：enqueue 後 worker 更新 stage，status API 讀得到。
- 整合測試：worker stage 拋錯後 job 變 failed。
- 整合測試：completed job result API 回傳 exports。
- 整合測試：processing job result API 回傳 409。

## 非 MVP 範圍

- 取消任務 UI 與 cancel API。
- 任務優先級與付費隊列。
- WebSocket / Server-Sent Events 即時推播。
- 多 worker 動態 autoscaling。

## 未來擴充方向

- 加入 watchdog 掃描 stuck jobs。
- 將 GPU stage 與 CPU stage 拆成不同 queue。
- 加入 SSE 取代輪詢。
- 加入任務取消、重跑與 retry policy UI。
