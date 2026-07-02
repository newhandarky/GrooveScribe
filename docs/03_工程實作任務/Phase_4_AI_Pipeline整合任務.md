# Phase 4：Production Pipeline Service 任務

> 本文件已依 local-first 完整 V1 方向重整。詳細 ticket 以 `V1_Ticket總表.md` 為準。

## Phase 目標

把 Phase 1 的本機 pipeline 封裝成 V1 local job manager 可呼叫的正式 `PipelineService`，並完整寫入 artifacts、stage reports、DrumTrack、ExportFile 與 error metadata。

## V1 重點

- PipelineService 不依賴 FastAPI request / response。
- PipelineService 不綁死 Celery task。
- 每個 stage 都要有 artifacts、runtime、warnings、error summary。
- raw MIDI、processed MIDI、drum events JSON、MusicXML、PDF 與 pipeline log 都要保留。

## 主要任務

- `GS-V1-P4-001`：建立正式 PipelineService。
- `GS-V1-P4-002`：將 ffmpeg preprocessing 接入 PipelineService。
- `GS-V1-P4-003`：將 Demucs adapter 接入 PipelineService。
- `GS-V1-P4-004`：將 ADTOF adapter 接入 PipelineService。
- `GS-V1-P4-005`：將 MIDI post-processing 接入 PipelineService。
- `GS-V1-P4-006`：將 MusicXML / PDF export 接入 PipelineService。
- `GS-V1-P4-007`：寫入 DrumTrack、ExportFile 與 stage report metadata。
- `GS-V1-P4-008`：建立 pipeline error mapping 與使用者錯誤訊息。
- `GS-V1-P4-009`：記錄 pipeline / model / runtime version。

## 驗收標準

- 本機 job manager 可呼叫正式 PipelineService。
- completed job 可下載 MIDI、MusicXML、PDF。
- PDF export warning 不會讓 MusicXML / MIDI 失效。
- failed job 有穩定 error code、stage、summary 與 internal log reference。

## 參考文件

- `docs/AI音訊處理流程.md`
- `docs/模組設計.md`
- `docs/02_功能細部設計/AI_Pipeline執行規格.md`
- `docs/產品完整度標準.md`
- `docs/03_工程實作任務/V1_Ticket總表.md`
