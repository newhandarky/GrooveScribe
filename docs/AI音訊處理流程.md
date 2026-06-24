# GrooveScribe AI 音訊處理流程規劃

## 1. Pipeline 總覽

MVP AI pipeline：

```text
original audio
→ ffmpeg normalize
→ normalized.wav
→ Demucs source separation
→ drums.wav
→ ADTOF-pytorch drum transcription
→ raw_drum.mid
→ MIDI post-processing
→ processed_drum.mid
→ notation generation
→ MusicXML / PDF
```

設計原則：

- 每個 stage 有明確輸入與輸出。
- 每個 AI 模型都透過 adapter 呼叫。
- 模型失敗不應造成 API server crash。
- 原始輸出與後處理輸出都要保留，方便 debug 與準確度分析。

## 2. Demucs 在系統中的角色

Demucs 的角色是 source separation。它將完整歌曲分離成多個 stems，MVP 只取 `drums stem` 給下一階段使用。

為什麼需要 Demucs：

- 完整歌曲中包含 vocal、bass、guitar、keyboard 等聲音。
- Drum transcription model 若直接吃完整混音，容易受到其他樂器干擾。
- 先分離 drums stem 可以讓 ADTOF-pytorch 面對更接近「鼓軌」的輸入。

MVP 輸出：

- `drums.wav`
- `source_separation_report.json`

注意事項：

- Demucs 分離結果可能包含 bleed 或 artifacts。
- cymbal 可能被削弱或產生破碎感。
- bass / low-frequency bleed 可能影響 kick 偵測。
- 原始 Demucs repo 已封存，正式產品需評估維護風險與替代模型。

## 3. ADTOF-pytorch 在系統中的角色

ADTOF-pytorch 的角色是 automatic drum transcription。它將 drum audio 轉成 MIDI drum events。

MVP 中它負責：

- 讀取 `drums.wav`。
- 偵測 drum onsets。
- 分類基本鼓件。
- 輸出 raw drum MIDI。

MVP 輸出：

- `raw_drum.mid`
- `drum_transcription_report.json`

設計重點：

- ADTOF-pytorch 不應直接散落在 worker 業務流程中。
- 需封裝成 `AdtofDrumTranscriber` adapter。
- adapter 負責模型載入、CLI / Python API 呼叫、錯誤轉換、輸出檔驗證。

## 4. 為什麼第一版不把 Omnizart 當主線

Omnizart 是多任務音樂轉譜工具，涵蓋 vocal、drum、chord、beat、instrument transcription 等方向。它適合做研究比較或第二模型驗證，但不建議作為 MVP 主線，原因如下：

1. 產品目標明確是鼓譜，第一版應使用更聚焦的 drum transcription pipeline。
2. 多任務工具通常安裝依賴、模型管理與錯誤排查成本更高。
3. MVP 需要逐段觀察 `drums stem`、`raw MIDI`、`processed MIDI`，Demucs + ADTOF-pytorch 的責任分界更清楚。
4. 第一版的核心風險在輸出是否可用，而不是一次整合最多模型。

Omnizart 的建議定位：

- Phase 2 之後加入 benchmark。
- 對同一組測試音檔產生第二份 raw MIDI。
- 比較 kick / snare / hat F1 score 與人工評分。
- 若特定曲風效果更好，再作為 fallback 或 routing option。

## 5. drums stem 的處理方式

Demucs 輸出的 drums stem 需經過基本驗證：

- 檔案存在。
- duration 與 normalized audio 接近。
- 檔案大小不為 0。
- 可被音訊 decoder 讀取。
- RMS / peak 不為異常低值。

MVP 可暫不做複雜 audio enhancement，但應保留未來擴充點：

- loudness normalization
- high-pass / low-pass filter
- onset enhancement
- silence trimming
- transient emphasis

## 6. drum MIDI 的產生方式

ADTOF-pytorch 產生 raw MIDI 後，系統需保留原始檔案。後處理不應覆蓋 raw MIDI。

MVP 應建立中間事件模型：

```json
{
  "events": [
    {
      "time_seconds": 1.234,
      "instrument": "kick",
      "midi_note": 36,
      "velocity": 92,
      "source": "adtof"
    }
  ]
}
```

此 JSON 是後處理、MusicXML 產生、debug UI 的共同基礎。

## 7. 可能的誤判來源

常見誤判：

- Bass 被誤判成 kick。
- Clap、rim、percussion 被誤判成 snare。
- Crash、ride、open hi-hat 被混在同一類 cymbal。
- Ghost note 太小聲而漏掉。
- Drum fill 中 tom 與 snare 互相誤判。
- Demucs artifacts 造成不存在的 onset。
- 現場錄音 reverb 導致重複觸發。
- Tempo 漂移造成譜面量化錯位。

結果頁應避免宣稱 100% 準確，並鼓勵使用者下載後修正。

## 8. 後處理策略

MVP 後處理目標：產生可讀、可編輯的鼓譜草稿。

策略：

- Tempo：先用模型 MIDI timing 或簡化 beat tracking；若不可靠，允許使用預設 BPM。
- Quantization：預設量化到 16 分音符，可視 BPM 調整到 8 分或 32 分。
- Mapping：轉成 General MIDI drum mapping。
- De-duplication：同一鼓件在極短時間內重複觸發時合併。
- Velocity cleanup：限制 velocity 合理範圍，避免過小 noise 事件。
- Instrument simplification：MVP 可將複雜 cymbal 合併成 cymbal，tom 可先簡化成 high / mid / low tom。
- Empty result handling：若 raw MIDI 幾乎沒有事件，標記 low confidence，仍保存 artifacts。

## 9. 未來如何加入第二模型 fallback

定義統一 interface：

```text
DrumTranscriber.transcribe(input: AudioArtifact, config: TranscriptionConfig) -> TranscriptionResult
```

TranscriptionResult 應包含：

- raw MIDI artifact
- event JSON
- model name
- model version
- confidence metadata
- warnings

未來 fallback 策略：

1. Parallel：同一個 drums stem 同時跑 ADTOF-pytorch 與 Omnizart。
2. Sequential：ADTOF-pytorch 失敗或輸出低 confidence 時才跑 Omnizart。
3. Routing：依據音檔特徵或曲風選擇模型。
4. Ensemble：合併多模型事件，對 kick / snare / hat 分別採用較可信結果。

MVP 只需要保留 interface 與 metadata 欄位，不需要實作 fallback。

## 10. 評估指標

技術評估：

- Kick precision / recall / F1。
- Snare precision / recall / F1。
- Hi-hat precision / recall / F1。
- Onset timing error。
- Empty / failed transcription ratio。

產品評估：

- 使用者是否認為 groove 可辨識。
- 使用者修譜時間是否明顯低於從零扒譜。
- MIDI 是否可順利匯入 DAW。
- MusicXML 是否可順利匯入 MuseScore。
