# Pipeline Fixtures

本目錄保存 Phase 1 pipeline smoke test 使用的最小測試資料。

## 原則

- 只提交可程式產生或明確授權的音檔。
- 不提交商用歌曲、未授權 loop、或來源不明的鼓軌。
- `manifest.json` 必須記錄 fixture 用途、來源與預期行為。
- 若 fixture 是大型或第三方音源，應改放外部測試資料儲存並在 manifest 記錄取得方式。

## 重新產生

```bash
PYTHONPATH=. python scripts/generate_test_fixtures.py
```

## 目前 fixture

- `audio/synthetic_clean_drum_pattern.wav`：合成鼓型，用於 local runner mock smoke test。
- `audio/synthetic_quiet_drum_pattern.wav`：低音量合成鼓型，用於未來 low confidence 測試。
- `audio/synthetic_silence.wav`：有效但無聲音檔，用於 edge case。
- `audio/invalid_audio.wav`：副檔名為 WAV 但內容不是音訊，用於 decode failure 測試。
