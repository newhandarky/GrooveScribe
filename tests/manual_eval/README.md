# Manual Evaluation

人工評估用於判斷 local-first V1 輸出是否達到「可檢查、可下載、可人工修正的鼓譜草稿」，不是專業出版級轉譜驗收。

## 使用方式

1. 對同一批 fixture 或授權測試音檔跑 local pipeline。
2. 將結果填入 `manual_eval_template.csv`。
3. 若使用第三方音源，記錄來源、授權與是否可提交到 repo。
4. 針對 raw MIDI 與 processed MIDI 跑 `scripts/inspect_midi.py`，記錄 note histogram、processed drum counts、event count。
5. 每次模型、threshold、後處理策略改動後，保留一份新的評估結果檔。

## 分數定義

- `0`：不可用或完全錯誤。
- `1`：只有少量片段可參考。
- `2`：能看出輪廓，但需要大量人工修正。
- `3`：可作為 V1 草稿，仍需使用者修正。
- `4`：大部分可用，少量修正。
- `5`：接近可直接使用。

## V1 Gate 記錄要求

- `pipeline_version`：backend / ai pipeline 版本或 commit。
- `runtime_version`：AI Python、Demucs、ADTOF template / checkpoint 摘要。
- `artifact_ref`：repo 外 artifact 位置或 redacted storage key。
- `raw_note_histogram`：raw MIDI note 分布。
- `processed_drum_counts`：postprocess 後的 drum 分布。
- `warnings`：pipeline / postprocess warning。
- `blocked_reason`：true AI 尚無法完成時必填。
