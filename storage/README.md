# Storage

MVP 使用 local filesystem 保存 artifacts。正式程式碼必須透過 Storage Adapter 存取，不應直接把絕對路徑暴露給 API response。

預期 key 格式：

```text
jobs/{job_id}/original/{filename}
jobs/{job_id}/audio/normalized.wav
jobs/{job_id}/stems/drums.wav
jobs/{job_id}/midi/raw_drum.mid
jobs/{job_id}/midi/processed_drum.mid
jobs/{job_id}/events/drum_events.json
jobs/{job_id}/notation/score.musicxml
jobs/{job_id}/exports/score.pdf
jobs/{job_id}/logs/pipeline.json
```
