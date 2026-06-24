# Level 3：工程實作任務 README

## Level 3 文件用途

`03_工程實作任務` 是 GrooveScribe 的工程 ticket 層。Level 1 定義產品與系統架構，Level 2 定義功能細部規格，Level 3 將這些規格拆成工程師可以直接執行、測試與驗收的開發任務。

這一層文件只描述實作任務，不建立程式碼，不取代既有 Level 1 / Level 2 文件。

## 如何閱讀這些文件

建議先讀 `MVP_Ticket總表.md` 掌握全貌，再依照 Phase 順序閱讀各任務文件：

1. `Phase_1_本地Pipeline_POC任務.md`
2. `Phase_2_後端API與資料模型任務.md`
3. `Phase_3_背景Worker與Queue任務.md`
4. `Phase_4_AI_Pipeline整合任務.md`
5. `Phase_5_前端上傳與結果頁任務.md`
6. `Phase_6_樂譜預覽與匯出任務.md`
7. `Phase_7_測試與驗收任務.md`
8. `Phase_8_部署與環境設定任務.md`

若團隊想平行開發，可先用 mock adapter 讓 Phase 2 / 3 / 5 並行，Phase 4 再接真實 Demucs 與 ADTOF-pytorch。

## Level 1 / Level 2 的 5-phase 與 Level 3 的 8-phase 對照

Level 1 / Level 2 使用較粗的 5 個開發階段，Level 3 為了拆 ticket，把其中幾段再細分成 8 個工程 phase。兩者對照如下：

| Level 1 / Level 2 階段 | Level 3 對應工程 phase | 說明 |
|---|---|---|
| Phase 1：本地 Pipeline Proof of Concept | Phase 1：本地 Pipeline POC | 先證明本地音訊到 MIDI / MusicXML / PDF 可跑通。 |
| Phase 2：後端 API | Phase 2：後端 API 與資料模型、Phase 3：背景 Worker 與 Queue、Phase 4：AI Pipeline 整合 | Level 3 將 API、worker、正式 pipeline 整合拆開，避免長任務進入 API request。 |
| Phase 3：前端上傳與結果頁 | Phase 5：前端上傳與結果頁 | 建立上傳、輪詢、錯誤、下載入口。 |
| Phase 4：樂譜預覽與匯出 | Phase 6：樂譜預覽與匯出 | 整合 MusicXML preview、PDF export 與 fallback UI。 |
| Phase 5：測試與部署 | Phase 7：測試與驗收、Phase 8：部署與環境設定 | Level 3 將測試驗收與部署環境拆成兩段。 |

因此討論「Phase 2」時需明確說明是 Level 1 / 2 的粗階段，還是 Level 3 的工程 phase。

## Ticket ID 規則

Ticket ID 格式：

```text
GS-P{phase_number}-{ticket_number}
```

範例：

- `GS-P1-001`：Phase 1 第一張 ticket
- `GS-P2-006`：Phase 2 第六張 ticket
- `GS-P8-007`：Phase 8 第七張 ticket

每個 ticket 都包含目的、實作範圍、不包含範圍、建議目錄、輸入、輸出、API / Data Model / Storage 關聯、驗收標準、測試要求、相依任務與風險。

## 建議開發順序

```text
Phase 1：本地 Pipeline POC
→ Phase 2：後端 API 與資料模型
→ Phase 3：背景 Worker 與 Queue
→ Phase 4：AI Pipeline 整合
→ Phase 5：前端上傳與結果頁
→ Phase 6：樂譜預覽與匯出
→ Phase 7：測試與驗收
→ Phase 8：部署與環境設定
```

實務上可平行：

- Phase 1 與 Phase 2 可同時開始。
- Phase 3 可先用 mock pipeline，不必等 Phase 4 完成。
- Phase 5 可先用 mock API response，不必等真實模型可用。
- Phase 6 需要 MusicXML / PDF artifact 初版後再做完整驗收。

## 如何從 ticket 進入實作

1. 從 `MVP_Ticket總表.md` 選擇 Todo ticket。
2. 讀取該 ticket 的 Phase 文件與「需參考的 Level 1 / Level 2 文件」。
3. 確認相依任務是否完成。
4. 依照 ticket 的「主要修改位置或建議目錄」建立或修改實作。
5. 完成「驗收標準」與「測試要求」。
6. 更新 ticket 狀態與測試紀錄。

## 如何判斷 MVP 完成

MVP 完成需同時滿足：

- 使用者可上傳單首 MP3 / WAV。
- API request 不執行長時間音訊處理，只建立 job 並派送 queue。
- Background worker 可執行完整 pipeline。
- Pipeline 可產生 MIDI、MusicXML、PDF。
- 前端可顯示 queued / processing / completed / failed。
- 完成後可預覽 MusicXML 並下載 MIDI / MusicXML / PDF。
- 失敗時有清楚錯誤訊息，不暴露 stack trace 或 local path。
- Storage 透過 adapter 使用 local filesystem，並保留 S3-compatible storage 擴充性。
- 至少完成固定測試音檔的人工檢查與 MVP 驗收 checklist。

## Ticket Grooming 修正紀錄

本輪依文件審核結果補強：

- Phase 3 補 `GS-P3-007`，明確串接 Upload API 與 Celery enqueue。
- Phase 4 補 `GS-P4-009`、`GS-P4-010`、`GS-P4-011`，讓 preprocessing、MIDI post-processing、notation / PDF export 都有正式 service/interface 邊界。
- Phase 5 補 `GS-P5-009`，明確處理上傳表單送出、`202 Accepted` 與 `/jobs/{job_id}` 導向。
- Phase 7 補 `GS-P7-008`，建立瀏覽器端 E2E smoke test。
- 修正 Phase 2 / 4 / 5 / 6 / 8 的相依任務，讓 ticket 開工順序更清楚。


最後一輪 grooming 補強：

- 補上 5-phase 與 8-phase mapping，避免不同層級文件的 Phase 命名混淆。
- 標註 `GS-P4-001` 為 Phase 4 後段整合票，不應照票號第一個開工。
- 強化 `GS-P2-006` 與 `GS-P7-006` 的驗收標準與測試要求。
- 調整 `GS-P6-002` 相依，讓正式 MusicXML artifact 產生流程完成後再做完整預覽驗收。
- 補 `GS-P1-009`，鎖定 AI runtime 與安裝重現紀錄。
