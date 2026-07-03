# GrooveScribe REST API 設計

## 1. API 設計原則

- API 層只負責接收任務、查詢狀態、回傳結果與下載檔案。
- 長時間 AI pipeline 必須由本機 job manager 執行。
- API response 使用穩定 JSON 格式。
- 下載 API 不暴露內部 filesystem path。
- V1 預設不做登入；若未來加入 User 或 cloud sync，API path 不需大幅更動。
- V1 API 是 localhost app 的內部邊界，不代表雲端 SaaS contract。

Base path：

```text
/api/v1
```

## 2. Runtime / Health API

### `GET /api/v1/runtime/preflight`

用途：回傳本機 runtime preflight 狀態。

成功 response：`200 OK`

```json
{
  "status": "degraded",
  "mock_ai_ready": true,
  "true_ai_ready": false,
  "missing_requirements": [
    "ADTOF runtime has not produced and verified raw_drum.mid; set GROOVESCRIBE_ADTOF_COMMAND_TEMPLATE and GROOVESCRIBE_ADTOF_VERIFY_INPUT for output verification"
  ],
  "checks": {
    "ffmpeg": {"ready": true, "available": true, "command": "ffmpeg"},
    "demucs": {"ready": true, "package_available": true},
    "adtof": {
      "ready": false,
      "status_code": "verify_input_missing",
      "summary": "尚未提供 ADTOF verification input drums stem。",
      "next_steps": [
        "先執行 normalize 與 Demucs separation，產生 drums.wav。",
        "設定 GROOVESCRIBE_ADTOF_VERIFY_INPUT 指向該 drums.wav。"
      ],
      "required_env": ["GROOVESCRIBE_ADTOF_COMMAND_TEMPLATE"],
      "optional_env": [
        "GROOVESCRIBE_ADTOF_CHECKPOINT",
        "GROOVESCRIBE_ADTOF_VERIFY_INPUT",
        "GROOVESCRIBE_ADTOF_VERIFY_OUTPUT_DIR"
      ]
    },
    "musescore_pdf": {"ready": true, "optional_for_v1": true}
  },
  "smoke_commands": {},
  "checked_at": "2026-07-02T10:00:00Z",
  "error": null
}
```

`status=degraded` 表示 mock-ai flow 可用，但 true AI runtime 尚未 ready。V1 預設 upload gating 只要求 `mock_ai_ready=true`；true AI smoke 是 opt-in，不是一般 CI 必跑條件。

## 3. 上傳音檔 API

### `POST /api/v1/transcriptions`

用途：上傳音檔並建立 transcription job。

Content-Type：`multipart/form-data`

Request fields：

| 欄位 | 類型 | 必填 | 說明 |
|---|---|---|
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
- `503 RUNTIME_NOT_READY`

## 4. 查詢任務狀態 API

### `GET /api/v1/transcriptions/{job_id}/status`

用途：查詢本機背景任務狀態。

成功 response：`200 OK`

```json
{
  "job_id": "job_01HZABC123",
  "status": "processing",
  "stage": "source_separation",
  "progress": 45,
  "message": "正在分離鼓軌",
  "created_at": "2026-06-24T10:00:00Z",
  "queued_at": "2026-06-24T10:00:01Z",
  "started_at": "2026-06-24T10:00:10Z",
  "completed_at": null,
  "failed_at": null,
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
  "queued_at": "2026-06-24T10:00:01Z",
  "started_at": "2026-06-24T10:00:10Z",
  "completed_at": null,
  "failed_at": "2026-06-24T10:03:20Z",
  "error": {
    "code": "DRUM_TRANSCRIPTION_FAILED",
    "message": "系統無法從鼓軌產生 MIDI，請嘗試較清楚的音檔。",
    "retriable": true
  }
}
```

## 5. 取得分析結果 API

### `GET /api/v1/transcriptions/{job_id}`

用途：取得分析結果 metadata。

成功 response：`200 OK`

```json
{
  "job_id": "job_01HZABC123",
  "status": "completed",
  "stage": "completed",
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
      "status": "available",
      "download_url": "/api/v1/transcriptions/job_01HZABC123/download/midi"
    },
    {
      "type": "musicxml",
      "status": "available",
      "download_url": "/api/v1/transcriptions/job_01HZABC123/download/musicxml"
    },
    {
      "type": "pdf",
      "status": "available",
      "download_url": "/api/v1/transcriptions/job_01HZABC123/download/pdf"
    }
  ],
  "pipeline": {
    "mode": "true_ai",
    "status": "completed",
    "pipeline_log_available": true,
    "stages": [
      {
        "name": "midi_post_processing",
        "status": "completed",
        "runtime_seconds": 0.42,
        "warnings": ["hihat_missing_likely"]
      }
    ],
    "artifacts": [
      {
        "type": "midi",
        "available": true,
        "file_size_bytes": 2048,
        "status": "available"
      },
      {
        "type": "pdf",
        "available": false,
        "file_size_bytes": null,
        "status": "failed"
      }
    ],
    "warnings": ["hihat_missing_likely"]
  },
  "preview": {
    "musicxml_url": "/api/v1/transcriptions/job_01HZABC123/download/musicxml"
  }
}
```

`pipeline` 是 result review 用的 redacted summary，只包含 stage 狀態、warnings、export 狀態與 mock / true AI 模式；不得暴露 internal snapshot、filesystem path、raw command、stderr/stdout 或 traceback。PDF 仍是 optional，`pdf.status=failed` 不代表 MIDI / MusicXML 失敗。

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

## 6. 下載 API

### `GET /api/v1/transcriptions/{job_id}/download/midi`

回傳：`audio/midi` 或 `application/octet-stream`

### `GET /api/v1/transcriptions/{job_id}/download/musicxml`

回傳：`application/vnd.recordare.musicxml+xml` 或 `application/xml`

### `GET /api/v1/transcriptions/{job_id}/download/pdf`

回傳：`application/pdf`

下載規則：

- job 必須是 `completed`，或該 export 已明確標示 `available`。
- export file 必須存在且狀態為 `available`。
- 若檔案不存在，回傳 `404 EXPORT_NOT_FOUND`。
- 若檔案仍在產生，回傳 `409 EXPORT_NOT_READY`。
- API 只回傳 stream，不回傳本機真實路徑。

## 7. 錯誤 Response 格式

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
| 503 | RUNTIME_NOT_READY | 本機 runtime 尚未就緒 |

## 8. Job Status / Stage 枚舉

Status：

```text
uploaded
queued
processing
completed
failed
interrupted
canceled
```

Stage：

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

## 9. 前端輪詢策略

建議：

- queued / processing：每 2 至 5 秒輪詢一次。
- completed / failed / interrupted：停止輪詢。
- 若 API 連線失敗，前端顯示暫時無法更新狀態，但不要直接判斷 job failed。
- Future optional 可改 Server-Sent Events 或 WebSocket；V1 輪詢足夠。
