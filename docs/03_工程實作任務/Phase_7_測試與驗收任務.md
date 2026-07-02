# Phase 7：Quality、Diagnostics 與 V1 Acceptance 任務

> 本文件已依 local-first 完整 V1 方向重整。詳細 ticket 以 `V1_Ticket總表.md` 為準。

## Phase 目標

建立完整 V1 所需的測試、人工評估、browser smoke、diagnostics 與 release gate。V1 不只要求能跑通，而是要求可重現、可診斷、可評估。

## V1 重點

- 測試需涵蓋 SQLite、local storage、local job manager、PipelineService、frontend 與 browser smoke。
- 人工評估需記錄 pipeline version 與 runtime version。
- Runtime / pipeline 錯誤需有 structured diagnostics。

## 主要任務

- `GS-V1-P7-001`：補齊 backend API / SQLite / storage tests。
- `GS-V1-P7-002`：補齊 local job manager tests。
- `GS-V1-P7-003`：補齊 pipeline fixture / regression tests。
- `GS-V1-P7-004`：補齊 frontend component / API mock tests。
- `GS-V1-P7-005`：建立 localhost browser smoke test。
- `GS-V1-P7-006`：建立人工準確度評估與 release gate。
- `GS-V1-P7-007`：建立 structured diagnostics 與常見錯誤文件。

## 驗收標準

- local-first V1 主要測試可在本機執行。
- browser smoke 可從 localhost UI 上傳短 fixture 並取得結果。
- 至少一組 generated fixture 與一組授權真實鼓聲 fixture 完成人工評估。
- V1 release checklist 可被逐項驗收。

## 參考文件

- `docs/測試策略.md`
- `docs/產品完整度標準.md`
- `tests/manual_eval/README.md`
- `docs/03_工程實作任務/V1_Ticket總表.md`
