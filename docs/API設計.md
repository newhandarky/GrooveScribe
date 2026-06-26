# GrooveScribe REST API 設計

## 1. API 設計原則

- API 層只負責接收任務、查詢狀態、回傳結果與下載檔案。
- 長時間 AI pipeline 必須在 background worker 執行。
- API response 使用穩定 JSON 格式。
- 下載 API 不暴露內部 filesystem path。
- MVP 可先不做登入；若未來加入 User，API path 不需大幅更動。

Base path：

```text
/api/v1
```

## 2. 上傳音檔 API

### `POST /api/v1/transcriptions`

用途：上傳音檔並建立 transcription job。

Content-Type：`multipart/form-data`

Request fields：

| 欄位 | 類型 | 必填 | 說明 |
|---|---|---|---|
| file | File | 是 | MP3 或 WAV |
| title | string | 否 | 使用者自訂標題 |

成功 response：`202 Accepted`

```json
{
  "job_id": "job_01HZABC123",
  "status": "queued",
  "status_url": "/api/v1/transcriptions/job_01HZABC123/status",
  "result_url": "/api/v1/transcriptions/job_01HZABC123",
  "created_at": "2026-06-24T10:00:00Z"
}
```

可能錯誤：

- `400 INVALID_FILE_TYPE`
- `413 FILE_TOO_LARGE`
- `422 AUDIO_METADATA_UNREADABLE`
- `500 STORAGE_WRITE_FAILED`

## 3. 查詢任務狀態 API

### `GET /api/v1/transcriptions/{job_id}/status`

用途：查詢背景任務狀態。

成功 response：`200 OK`

```json
{
  "job_id": "job_01HZABC123",
  "status": "processing",
  "stage": "source_separation",
  "progress": 45,
  "message": "正在分離鼓軌",
  "created_at": "2026-06-24T10:00:00Z",
  "started_at": "2026-06-24T10:00:10Z",
  "completed_at": null,
  "error": null
}
```

Completed response 範例：

```json
{
  "job_id": "job_01HZABC123",
  "status": "completed",
  "stage": "completed",
  "progress": 100,
  "message": "分析完成",
  "created_at": "2026-06-24T10:00:00Z",
  "started_at": "2026-06-24T10:00:10Z",
  "completed_at": "2026-06-24T10:04:30Z",
  "error": null
}
```

Failed response 範例：

```json
{
  "job_id": "job_01HZABC123",
  "status": "failed",
  "stage": "drum_transcription",
  "progress": 60,
  "message": "鼓軌轉 MIDI 失敗",
  "created_at": "2026-06-24T10:00:00Z",
  "started_at": "2026-06-24T10:00:10Z",
  "completed_at": "2026-06-24T10:03:20Z",
  "error": {
    "code": "DRUM_TRANSCRIPTION_FAILED",
    "message": "系統無法從鼓軌產生 MIDI，請嘗試較清楚的音檔。",
    "retriable": true
  }
}
```

## 4. 取得分析結果 API

### `GET /api/v1/transcriptions/{job_id}`

用途：取得分析結果 metadata。

成功 response：`200 OK`

```json
{
  "job_id": "job_01HZABC123",
  "status": "completed",
  "title": "demo-song",
  "audio": {
    "file_name": "demo.mp3",
    "duration_seconds": 214.2,
    "content_type": "audio/mpeg"
  },
  "drum_track": {
    "estimated_bpm": 128,
    "time_signature": "4/4",
    "event_count": 842,
    "confidence_label": "medium",
    "warnings": [
      "hi_hat_open_closed_not_guaranteed",
      "cymbal_types_simplified"
    ]
  },
  "exports": [
    {
      "type": "midi",
      "download_url": "/api/v1/transcriptions/job_01HZABC123/download/midi"
    },
    {
      "type": "musicxml",
      "download_url": "/api/v1/transcriptions/job_01HZABC123/download/musicxml"
    },
    {
      "type": "pdf",
      "download_url": "/api/v1/transcriptions/job_01HZABC123/download/pdf"
    }
  ],
  "preview": {
    "musicxml_url": "/api/v1/transcriptions/job_01HZABC123/download/musicxml"
  }
}
```

若 job 尚未完成：`409 Conflict`

```json
{
  "error": {
    "code": "JOB_NOT_COMPLETED",
    "message": "任務尚未完成，請稍後再查詢結果。",
    "retriable": true,
    "details": {
      "status": "processing",
      "stage": "source_separation"
    }
  }
}
```

## 5. 下載 API

### `GET /api/v1/transcriptions/{job_id}/download/midi`

回傳：`audio/midi` 或 `application/octet-stream`

### `GET /api/v1/transcriptions/{job_id}/download/musicxml`

回傳：`application/vnd.recordare.musicxml+xml` 或 `application/xml`

### `GET /api/v1/transcriptions/{job_id}/download/pdf`

回傳：`application/pdf`

下載規則：

- job 必須是 `completed`。
- export file 必須存在且狀態為 `available`。
- 若檔案不存在，回傳 `404 EXPORT_NOT_FOUND`。
- 若檔案仍在產生，回傳 `409 EXPORT_NOT_READY`。

## 6. 錯誤 Response 格式

統一格式：

```json
{
  "error": {
    "code": "INVALID_FILE_TYPE",
    "message": "目前只支援 MP3 或 WAV 音檔。",
    "retriable": false,
    "details": {
      "allowed_extensions": ["mp3", "wav"]
    }
  }
}
```

建議錯誤碼：

| HTTP | Code | 說明 |
|---|---|---|
| 400 | INVALID_FILE_TYPE | 檔案格式不支援 |
| 413 | FILE_TOO_LARGE | 檔案過大 |
| 422 | AUDIO_METADATA_UNREADABLE | 音檔無法解析 |
| 404 | JOB_NOT_FOUND | 找不到任務 |
| 404 | ROUTE_NOT_FOUND | 找不到 API 資源 |
| 409 | JOB_NOT_COMPLETED | 任務尚未完成 |
| 409 | EXPORT_NOT_READY | 輸出檔尚未完成 |
| 500 | STORAGE_WRITE_FAILED | 寫入儲存失敗 |
| 500 | PIPELINE_FAILED | pipeline 未分類錯誤 |

## 7. Job Stage 枚舉

```text
uploaded
queued
preprocessing
source_separation
stem_validation
drum_transcription
midi_post_processing
notation_generation
pdf_export
completed
failed
```


## 8. 前端輪詢策略

建議：

- queued / processing：每 2 至 5 秒輪詢一次。
- completed / failed：停止輪詢。
- 若 API 連線失敗，前端顯示暫時無法更新狀態，但不要直接判斷 job failed。
- 未來可改 Server-Sent Events 或 WebSocket，但 MVP 輪詢足夠。
