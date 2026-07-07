# Manual Evaluation

人工評估用於判斷 local-first V1 輸出是否達到「可檢查、可下載、可人工修正的鼓譜草稿」，不是專業出版級轉譜驗收。

## 使用方式

1. 對同一批 fixture 或授權測試音檔跑 local pipeline。
2. 將結果填入 `manual_eval_template.csv`。
3. 若使用第三方音源，記錄來源、授權與是否可提交到 repo。
4. 針對 raw MIDI 與 processed MIDI 跑 `scripts/inspect_pipeline_artifacts.py`，記錄 note histogram、processed drum counts、event count 與 quality flags；單檔 MIDI 可用 `scripts/inspect_midi.py`。
5. 若使用 `scripts/run_true_ai_smoke_baseline.py`，可直接從 `baseline.json` 讀取 runtime、artifact、inspection 與 blocked reason。
6. 可用 `scripts/generate_manual_eval_row.py <baseline.json>` 先產生符合 `manual_eval_template.csv` 的一列，再由 reviewer 補分數。
7. Completed localhost job 可先下載 review packet，從 `review_packet.json` 的 `manual_eval_seed` 複製核心欄位，再由 reviewer 補分數。
8. 每次模型、threshold、後處理策略改動後，保留一份新的評估結果檔。

## 分數定義

- `0`：不可用或完全錯誤。
- `1`：只有少量片段可參考。
- `2`：能看出輪廓，但需要大量人工修正。
- `3`：可作為 V1 草稿，仍需使用者修正。
- `4`：大部分可用，少量修正。
- `5`：接近可直接使用。

## V1 Gate 記錄要求

- `date`：人工評估日期。
- `fixture_name`：repo 內 fixture 或授權外部音檔名稱。
- `runtime_mode`：`mock`、`true_ai` 或 `unknown`。
- `pipeline_version`：backend / ai pipeline 版本或 commit。
- `runtime_version`：AI Python、Demucs、ADTOF template / checkpoint 摘要。
- `baseline_report_ref`：`baseline.json` 或 artifact inspection report 參照。
- `artifact_ref`：repo 外 artifact 位置或 redacted storage key。
- `raw_event_count` / `processed_event_count`：raw 與 processed MIDI note-on event 數量。
- `raw_note_histogram`：raw MIDI note 分布。
- `processed_drum_counts`：postprocess 後的 drum 分布。
- `quality_flags`：`too_few_events`、`sparse_transcription`、`hihat_missing_likely`、`mostly_tom_output`、`no_snare_detected` 等穩定診斷 code。
- `warnings`：pipeline / postprocess warning。
- `blocked_reason`：true AI 尚無法完成時必填。

所有 `baseline_report_ref` / `artifact_ref` 必須使用 `baseline:<run_id>`、`external:<label>` 或 repo-relative fixture 名稱，不填 `/Users`、`/tmp`、`/private/tmp`、`/var/folders` 等本機絕對路徑。

## Blocked Baseline

若 true AI runtime 仍是 `degraded`，不要填入假分數。請新增一列並填：

- `date`
- `fixture_name`
- `runtime_mode`
- `pipeline_version`
- `runtime_version`
- `baseline_report_ref`
- `blocked_reason`
- `notes`：貼上 baseline report 路徑或 ADTOF `status_code`

評分欄位留空，等 runtime ready 後再補一份 completed baseline。

## CSV Row Generator

從 true-AI baseline 產出 row：

```bash
PYTHONPATH=. .venv-ai/bin/python scripts/generate_manual_eval_row.py \
  /tmp/groovescribe-true-ai-baseline/<run-id>/baseline.json
```

`completed` baseline 會帶入 runtime、artifact ref、raw/processed event count、note histogram、drum counts、quality flags、warnings。`blocked` baseline 會保留 blocked reason，分數欄位維持空白。

## Review Packet Seed

Completed job 的 review packet 也會提供 `manual_eval_seed`，包含 runtime mode、review ref、event counts、drum counts、quality flags、warnings 與 artifact ref。這些欄位可作為 CSV 起點，但 kick/snare/hihat/timing/readability/usability 分數必須由 reviewer 人工填寫。

Review packet CLI：

```bash
backend/.venv/bin/python scripts/export_review_packet.py \
  --job-id <job_id> \
  --output-dir /tmp/groovescribe-review-packet \
  --zip
```

不要把 generated review packet、ZIP、MIDI、MusicXML、PDF 或本機 storage 路徑提交到 repo。

## Fixture 與外部音檔

- Synthetic fixture 可提交到 repo，適合 regression / mock browser smoke。
- 外部授權音檔只記錄授權來源與 redacted label，不提交音檔、stem、MIDI、MusicXML、PDF 或完整本機 artifact 路徑。
