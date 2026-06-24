# Scripts

本目錄保留本地開發與 pipeline POC scripts。

## 已建立

- `run_local_pipeline.py`：輸出 MVP pipeline dry-run plan，不執行實際音訊處理。
- `run_normalize_audio.py`：使用 ffmpeg 將 MP3/WAV 轉成 `normalized.wav`。
- `run_demucs_separation.py`：使用 Demucs 將 `normalized.wav` 分離成穩定輸出 `drums.wav`。

## 預期後續 script

- `run_adtof_transcription.py`
- `inspect_midi.py`
- `generate_musicxml.py`
- `cleanup_storage.py`
