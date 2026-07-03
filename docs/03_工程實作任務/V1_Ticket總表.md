# V1 Ticket 總表

> Level 3 工程實作任務總覽。本文反映 GrooveScribe local-first 完整 V1 方向，不再以快速 MVP 或雲端部署為主線。

## V1 主線

V1 預設：

- Local Web App。
- 本機 FastAPI backend。
- SQLite database。
- 本機 job manager。
- Local filesystem artifacts。
- 本機 ffmpeg、Demucs、ADTOF、MusicXML / PDF export。

Future optional：

- Tauri / Electron desktop shell。
- Redis / Celery worker mode。
- PostgreSQL server mode。
- S3-compatible storage。
- cloud sync / SaaS deployment。

## 目前完成狀態摘要

截至 2026-07-03，local-first V1 已完成下列可驗收能力：

- local web app vertical slice：localhost UI 可做 runtime preflight、upload、job polling、result download。
- runtime diagnostics：`GET /api/v1/runtime/preflight` 與 ADTOF diagnostics 可回傳 structured status / next steps。
- true-AI baseline record：`tests/manual_eval/2026-07-03_true_ai_baseline_eval.csv` 已記錄 synthetic fixture baseline。
- result API pipeline summary：`GET /api/v1/transcriptions/{job_id}` 的 optional `pipeline` 欄位可顯示 stage summary、warnings、exports 與 quality summary。
- cleanup dry-run：local storage cleanup 可 dry-run 檢查。
- manual eval template：`tests/manual_eval/manual_eval_template.csv` 已包含 baseline report、event counts、drum counts、quality flags 與 blocked reason。

下一階段主線是 quality diagnostics / result review / manual eval gate：強化 artifact inspection、穩定 warning policy、讓結果頁能判讀 mock / true AI 輸出品質，並以 manual eval 決定 V1 是否可進 release。

## Ticket 總表

| Ticket ID | Phase | Ticket 名稱 | 優先級 | 預估難度 | 相依任務 | 對應文件 | 完成狀態 |
|---|---|---|---|---|---|---|---|
| `GS-V1-P1-001` | Phase 1 | 整理 local-first runtime baseline | P0 | M | 無 | `ai_pipeline/RUNTIME.md`, `docs/技術選型.md` | Todo |
| `GS-V1-P1-002` | Phase 1 | 建立 runtime preflight check UX contract | P0 | M | GS-V1-P1-001 | `docs/產品完整度標準.md` | Todo |
| `GS-V1-P1-003` | Phase 1 | 固定 generated fixtures 與授權真實鼓聲 fixture 流程 | P0 | M | GS-V1-P1-001 | `docs/測試策略.md`, `tests/manual_eval/README.md` | Todo |
| `GS-V1-P1-004` | Phase 1 | 補齊 true AI smoke 重現文件與限制 | P0 | S | GS-V1-P1-001 | `ai_pipeline/RUNTIME.md` | Todo |
| `GS-V1-P2-001` | Phase 2 | 將 V1 預設 database 定為 SQLite | P0 | M | 無 | `docs/系統架構.md`, `docs/資料模型設計.md` | Todo |
| `GS-V1-P2-002` | Phase 2 | 建立 SQLite migration / upgrade 流程 | P0 | M | GS-V1-P2-001 | `docs/技術選型.md` | Todo |
| `GS-V1-P2-003` | Phase 2 | 定義 app data 目錄與 local DB / artifacts 位置 | P0 | M | GS-V1-P2-001 | `docs/產品完整度標準.md` | Todo |
| `GS-V1-P2-004` | Phase 2 | 強化 LocalStorageAdapter artifact contract | P0 | M | GS-V1-P2-003 | `docs/02_功能細部設計/檔案儲存與Artifact規格.md` | Todo |
| `GS-V1-P2-005` | Phase 2 | 建立 artifacts 清理、備份與重置規格 | P1 | M | GS-V1-P2-003, GS-V1-P2-004 | `docs/產品完整度標準.md` | Todo |
| `GS-V1-P3-001` | Phase 3 | 建立本機 Job Manager interface | P0 | M | GS-V1-P2-001 | `docs/系統架構.md` | Todo |
| `GS-V1-P3-002` | Phase 3 | 實作本機 single-process job queue | P0 | M | GS-V1-P3-001 | `docs/開發計畫.md` | Todo |
| `GS-V1-P3-003` | Phase 3 | 實作 job lifecycle 狀態轉移 | P0 | M | GS-V1-P3-001, GS-V1-P2-001 | `docs/產品完整度標準.md` | Todo |
| `GS-V1-P3-004` | Phase 3 | 實作 stale / interrupted job recovery | P0 | M | GS-V1-P3-003 | `docs/產品完整度標準.md` | Todo |
| `GS-V1-P3-005` | Phase 3 | 保留 Redis / Celery adapter 邊界但移出 V1 預設 | P1 | S | GS-V1-P3-001 | `docs/架構決策/ADR-001-介面型態與執行模式.md` | Todo |
| `GS-V1-P4-001` | Phase 4 | 建立正式 PipelineService | P0 | L | GS-V1-P1-001, GS-V1-P2-004, GS-V1-P3-001 | `docs/系統架構.md`, `docs/AI音訊處理流程.md` | Todo |
| `GS-V1-P4-002` | Phase 4 | 將 ffmpeg preprocessing 接入 PipelineService | P0 | M | GS-V1-P4-001 | `docs/02_功能細部設計/ffmpeg音訊標準化規格.md` | Todo |
| `GS-V1-P4-003` | Phase 4 | 將 Demucs adapter 接入 PipelineService | P0 | L | GS-V1-P4-001 | `docs/02_功能細部設計/Demucs鼓軌分離規格.md` | Todo |
| `GS-V1-P4-004` | Phase 4 | 將 ADTOF adapter 接入 PipelineService | P0 | L | GS-V1-P4-003 | `docs/02_功能細部設計/ADTOF鼓MIDI轉寫規格.md` | Todo |
| `GS-V1-P4-005` | Phase 4 | 將 MIDI post-processing 接入 PipelineService | P0 | M | GS-V1-P4-004 | `docs/02_功能細部設計/MIDI後處理與量化規格.md` | Todo |
| `GS-V1-P4-006` | Phase 4 | 將 MusicXML / PDF export 接入 PipelineService | P0 | L | GS-V1-P4-005 | `docs/02_功能細部設計/鼓譜預覽與匯出規格.md` | Todo |
| `GS-V1-P4-007` | Phase 4 | 寫入 DrumTrack、ExportFile 與 stage report metadata | P0 | L | GS-V1-P4-006, GS-V1-P2-001 | `docs/資料模型設計.md` | Todo |
| `GS-V1-P4-008` | Phase 4 | 建立 pipeline error mapping 與使用者錯誤訊息 | P0 | M | GS-V1-P4-001 | `docs/02_功能細部設計/錯誤處理與使用者提示規格.md` | Todo |
| `GS-V1-P4-009` | Phase 4 | 記錄 pipeline / model / runtime version | P1 | S | GS-V1-P4-007 | `docs/產品完整度標準.md` | Todo |
| `GS-V1-P5-001` | Phase 5 | 建立 local web app 基礎 layout | P0 | M | 無 | `docs/02_功能細部設計/前端頁面與互動規格.md` | Todo |
| `GS-V1-P5-002` | Phase 5 | 建立上傳頁與前端預檢 | P0 | M | GS-V1-P5-001 | `docs/產品需求文件.md` | Todo |
| `GS-V1-P5-003` | Phase 5 | 建立 typed API client | P0 | M | GS-V1-P5-001 | `docs/API設計.md` | Todo |
| `GS-V1-P5-004` | Phase 5 | 建立 job result page | P0 | M | GS-V1-P5-003 | `docs/02_功能細部設計/前端頁面與互動規格.md` | Todo |
| `GS-V1-P5-005` | Phase 5 | 建立 job status polling 與 stage UI | P0 | M | GS-V1-P5-004, GS-V1-P3-003 | `docs/產品完整度標準.md` | Todo |
| `GS-V1-P5-006` | Phase 5 | 建立錯誤、warning 與準確度提醒 UI | P0 | M | GS-V1-P5-004, GS-V1-P4-008 | `docs/產品需求文件.md` | Todo |
| `GS-V1-P5-007` | Phase 5 | 建立下載按鈕與 partial success UI | P0 | S | GS-V1-P5-004, GS-V1-P4-007 | `docs/API設計.md` | Todo |
| `GS-V1-P5-008` | Phase 5 | 建立 runtime preflight / diagnostics UI | P1 | M | GS-V1-P1-002, GS-V1-P5-001 | `docs/產品完整度標準.md` | Todo |
| `GS-V1-P6-001` | Phase 6 | 整合 OpenSheetMusicDisplay | P0 | M | GS-V1-P5-004, GS-V1-P4-006 | `docs/02_功能細部設計/鼓譜預覽與匯出規格.md` | Todo |
| `GS-V1-P6-002` | Phase 6 | 建立 MusicXML preview component | P0 | M | GS-V1-P6-001 | `docs/02_功能細部設計/前端頁面與互動規格.md` | Todo |
| `GS-V1-P6-003` | Phase 6 | 建立 PDF export 狀態與 fallback UI | P0 | M | GS-V1-P5-007, GS-V1-P4-006 | `docs/產品完整度標準.md` | Todo |
| `GS-V1-P6-004` | Phase 6 | 建立 artifact / pipeline log 檢視入口 | P1 | M | GS-V1-P4-007 | `docs/產品完整度標準.md` | Todo |
| `GS-V1-P6-005` | Phase 6 | 建立重新執行 job 的產品規則 | P1 | M | GS-V1-P3-004, GS-V1-P6-004 | `docs/產品完整度標準.md` | Todo |
| `GS-V1-P7-001` | Phase 7 | 補齊 backend API / SQLite / storage tests | P0 | M | GS-V1-P2-004, GS-V1-P3-003 | `docs/測試策略.md` | Todo |
| `GS-V1-P7-002` | Phase 7 | 補齊 local job manager tests | P0 | M | GS-V1-P3-004 | `docs/測試策略.md` | Todo |
| `GS-V1-P7-003` | Phase 7 | 補齊 pipeline fixture / regression tests | P0 | L | GS-V1-P4-006 | `docs/測試策略.md` | Todo |
| `GS-V1-P7-004` | Phase 7 | 補齊 frontend component / API mock tests | P0 | M | GS-V1-P5-007 | `docs/測試策略.md` | Todo |
| `GS-V1-P7-005` | Phase 7 | 建立 localhost browser smoke test | P0 | L | GS-V1-P5-007, GS-V1-P6-002 | `docs/產品完整度標準.md` | Todo |
| `GS-V1-P7-006` | Phase 7 | 建立人工準確度評估與 release gate | P0 | M | GS-V1-P1-003, GS-V1-P7-003 | `docs/產品完整度標準.md` | Todo |
| `GS-V1-P7-007` | Phase 7 | 建立 structured diagnostics 與常見錯誤文件 | P1 | M | GS-V1-P4-008, GS-V1-P5-008 | `docs/產品完整度標準.md` | Todo |
| `GS-V1-P8-001` | Phase 8 | 建立一條本機啟動命令 | P0 | M | GS-V1-P2-003, GS-V1-P3-002, GS-V1-P5-001 | `docs/開發計畫.md` | Todo |
| `GS-V1-P8-002` | Phase 8 | 建立 app data 初始化與重置流程 | P0 | M | GS-V1-P2-003 | `docs/產品完整度標準.md` | Todo |
| `GS-V1-P8-003` | Phase 8 | 建立 V1 release checklist | P0 | S | GS-V1-P7-005, GS-V1-P7-006 | `docs/產品完整度標準.md` | Todo |
| `GS-V1-P8-004` | Phase 8 | 文件化 future desktop shell 邊界 | P2 | S | GS-V1-P8-003 | `docs/架構決策/ADR-001-介面型態與執行模式.md` | Todo |
| `GS-V1-P8-005` | Phase 8 | 文件化 future server mode 邊界 | P2 | S | GS-V1-P8-003 | `docs/架構決策/ADR-001-介面型態與執行模式.md` | Todo |

## 建議開發順序

```text
Phase 7：quality diagnostics / result review / manual eval gate
→ Phase 6：MusicXML preview polish / optional PDF clarity
→ Phase 8：local startup / release checklist hardening
→ Future：desktop shell、server mode、cloud sync
```

## 完整 V1 完成條件摘要

完整 V1 需同時滿足：

- 使用者可在本機啟動 GrooveScribe。
- 使用者可用 localhost UI 上傳單首 MP3 / WAV。
- Backend 使用 SQLite 與 local filesystem artifacts。
- 本機 job manager 可執行完整 pipeline。
- Pipeline 可產生 MIDI、MusicXML、PDF，並保留 stage reports。
- 前端可顯示 queued / processing / completed / failed / partial success。
- 完成後可預覽 MusicXML 並下載 MIDI / MusicXML / PDF。
- 失敗時有清楚錯誤訊息，不暴露 stack trace 或敏感 local path。
- 固定 fixture tests、browser smoke test、人工評估與 release checklist 完成。

詳細標準見 `docs/產品完整度標準.md`。
