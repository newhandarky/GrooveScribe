# Level 3：工程實作任務 README

## Level 3 文件用途

`03_工程實作任務` 是 GrooveScribe 的工程 ticket 層。Level 1 定義產品與系統架構，Level 2 定義功能細部規格，Level 3 將這些規格拆成工程師可以直接執行、測試與驗收的開發任務。

本層文件目前以 local-first 完整 V1 為主線，不再以快速 MVP、雲端部署或 staging deployment 作為第一版目標。

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

## 如何閱讀這些文件

建議先讀 `V1_Ticket總表.md` 掌握全貌，再依照 V1 phase 順序閱讀各任務文件。既有 `Phase_*` 文件仍保留部分歷史拆分內容，後續應逐步改寫成 V1 ticket 詳細規格。

優先閱讀：

1. `V1_Ticket總表.md`
2. `docs/產品完整度標準.md`
3. `docs/架構決策/ADR-001-介面型態與執行模式.md`
4. `docs/系統架構.md`
5. `docs/技術選型.md`

## V1 Phase 對照

| V1 Phase | 目標 | 說明 |
|---|---|---|
| Phase 1 | Local runtime baseline | 鎖定本機 AI runtime、fixture、preflight 與 smoke。 |
| Phase 2 | Local data / storage foundation | SQLite、local filesystem artifacts、app data 目錄。 |
| Phase 3 | Local job manager | 不以 Redis / Celery 為預設，建立本機 job lifecycle。 |
| Phase 4 | Production pipeline service | 將 ffmpeg、Demucs、ADTOF、MIDI、MusicXML、PDF 正式串進 job。 |
| Phase 5 | Local Web App | 建立上傳、結果、輪詢、錯誤、下載 UI。 |
| Phase 6 | Preview / export / artifact UX | MusicXML preview、PDF fallback、artifact/log 檢視。 |
| Phase 7 | Quality / diagnostics / acceptance | 測試、人工評估、browser smoke、diagnostics。 |
| Phase 8 | Local startup / release checklist | 一條本機啟動路徑、app data 初始化、V1 release checklist。 |

## Ticket ID 規則

V1 ticket ID 格式：

```text
GS-V1-P{phase_number}-{ticket_number}
```

範例：

- `GS-V1-P2-001`：V1 Phase 2 第一張 ticket。
- `GS-V1-P5-004`：V1 Phase 5 第四張 ticket。

## 如何從 ticket 進入實作

1. 從 `V1_Ticket總表.md` 選擇 Todo ticket。
2. 讀取該 ticket 的對應 Level 1 / Level 2 文件。
3. 確認相依任務是否完成。
4. 依照 ticket 的「V1 主線」限制確認不引入雲端預設依賴。
5. 完成驗收標準與測試要求。
6. 更新 ticket 狀態與測試紀錄。

## 如何判斷完整 V1 完成

完整 V1 需同時滿足：

- 使用者可在本機啟動 GrooveScribe。
- 使用者可從 localhost UI 上傳單首 MP3 / WAV。
- Backend 使用 SQLite 與 local filesystem artifacts。
- 長任務由本機 job manager 執行，不阻塞 API request。
- Pipeline 可產生 MIDI、MusicXML、PDF，並保留 logs / stage reports。
- 前端可顯示 queued / processing / completed / failed / partial success。
- 完成後可預覽 MusicXML 並下載 MIDI / MusicXML / PDF。
- 失敗時有清楚錯誤訊息，不暴露 stack trace 或敏感 local path。
- 固定 fixture tests、browser smoke test、人工評估與 V1 release checklist 完成。

詳細標準見 `docs/產品完整度標準.md`。

## 舊文件處理原則

既有工程文件中若仍提到 MVP、Redis / Celery、PostgreSQL、staging deployment，應依下列規則更新：

- `MVP` 改為 `V1` 或 `完整 V1`。
- `Redis / Celery` 改為 future optional，除非該段明確在討論 server mode。
- `PostgreSQL` 改為 future optional，V1 預設 SQLite。
- `staging deployment` 改為 future optional，V1 預設 local startup / release checklist。
- `cloud / SaaS` 改為 future optional。
