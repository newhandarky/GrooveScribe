# Phase 7：測試與驗收任務

> Level 3 工程實作任務文件。本文只拆解開發 ticket，不取代 Level 1 / Level 2 規格。

## Phase 目標

建立 MVP 所需單元、整合、pipeline、API contract、人工準確度與 regression 測試流程。

## 前置條件

- Phase 1-6 主要功能已可用或至少有 mock 實作。
- 測試 fixture 與人工檢查表初版已存在。

- 若要執行瀏覽器端 E2E，需先完成或提供等效的 local env、Redis / Postgres、storage volume 設定。

## 需參考的 Level 1 / Level 2 文件

- Level 1：測試策略.md
- Level 2：MVP開發任務拆分.md
- Level 2：音檔上傳功能規格.md
- Level 2：AI_Pipeline執行規格.md
- Level 2：前端頁面與互動規格.md

## 任務清單

- `GS-P7-001`：建立 unit tests
- `GS-P7-002`：建立 integration tests
- `GS-P7-003`：建立 pipeline fixture tests
- `GS-P7-004`：建立 API contract tests
- `GS-P7-005`：建立人工準確度評估流程
- `GS-P7-006`：建立 MVP 驗收 checklist
- `GS-P7-007`：建立 regression test 流程
- `GS-P7-008`：建立瀏覽器端 E2E smoke test

## Ticket 詳細內容

### GS-P7-001 — 建立 unit tests

**Ticket ID**
GS-P7-001

**Ticket 名稱**
建立 unit tests

**背景與目的**
補齊核心純邏輯單元測試，降低後續 refactor 風險。

**實作範圍**
- 測 file validators、storage key sanitizer、status transition、MIDI mapping/quantization、error mapping。
- 建立測試命令與覆蓋範圍說明。

**不包含範圍**
- 不追求 100% coverage。

**主要修改位置或建議目錄**
- tests/unit/
- backend/tests/unit/
- ai_pipeline/tests/unit/

**輸入**
- 核心函式與 fixtures。

**輸出**
- unit test suite。

**API / Data Model / Storage 關聯**
- 涵蓋 API validator、Data Model enum、Storage key、MIDI 後處理。

**驗收標準**
- 單元測試可本地執行。
- 核心 mapping 與狀態轉移有測試。

**測試要求**
- 執行 unit test command。

**相依任務**
GS-P2-010, GS-P4-007, GS-P1-005

**風險與注意事項**
- 保持 MVP 範圍，避免順手實作多人協作、即時轉譜或線上修譜。

### GS-P7-002 — 建立 integration tests

**Ticket ID**
GS-P7-002

**Ticket 名稱**
建立 integration tests

**背景與目的**
建立 API、database、storage、worker mock 的整合測試。

**實作範圍**
- 測 upload 建 job。
- 測 status/result/download。
- 測 storage adapter 串接。
- 測 worker mock 更新狀態。

**不包含範圍**
- 不實跑 Demucs / ADTOF。

**主要修改位置或建議目錄**
- tests/integration/
- backend/tests/integration/

**輸入**
- 測試 database、local storage、mock queue。

**輸出**
- integration test suite。

**API / Data Model / Storage 關聯**
- API/Data/Storage/Queue 整合。

**驗收標準**
- 主要 API 整合測試通過。
- 不依賴外部網路。

**測試要求**
- 執行 integration test command。

**相依任務**
GS-P2-006, GS-P2-009, GS-P3-004

**風險與注意事項**
- 保持 MVP 範圍，避免順手實作多人協作、即時轉譜或線上修譜。

### GS-P7-003 — 建立 pipeline fixture tests

**Ticket ID**
GS-P7-003

**Ticket 名稱**
建立 pipeline fixture tests

**背景與目的**
建立 fast / slow pipeline 測試，區分 mock adapter 與真模型測試。

**實作範圍**
- fast tests mock Demucs / ADTOF。
- slow tests 對短音檔實跑 ffmpeg、Demucs、ADTOF。
- 驗證所有 artifacts 存在且可讀。

**不包含範圍**
- 不把大型音檔 commit。
- 不要求 slow test 每次 CI 都跑。

**主要修改位置或建議目錄**
- tests/pipeline/
- tests/fixtures/audio/

**輸入**
- fixture audio。
- mock adapters。

**輸出**
- pipeline test reports。

**API / Data Model / Storage 關聯**
- Storage artifact：normalized、drums、raw_midi、processed_midi、musicxml、pdf。

**驗收標準**
- fast tests 穩定通過。
- slow tests 有手動或 nightly 流程。

**測試要求**
- fast pipeline command。
- slow pipeline checklist。

**相依任務**
GS-P1-007, GS-P4-001

**風險與注意事項**
- 保持 MVP 範圍，避免順手實作多人協作、即時轉譜或線上修譜。

### GS-P7-004 — 建立 API contract tests

**Ticket ID**
GS-P7-004

**Ticket 名稱**
建立 API contract tests

**背景與目的**
固定 API response schema，避免前端與後端 contract 漂移。

**實作範圍**
- 為 upload/status/result/download/error 建 schema test。
- 驗證錯誤格式。
- 驗證 stage enum 與 export type。

**不包含範圍**
- 不導入複雜 contract broker。

**主要修改位置或建議目錄**
- tests/contract/
- backend/tests/contract/

**輸入**
- API response examples。

**輸出**
- contract test suite。

**API / Data Model / Storage 關聯**
- API：所有 MVP endpoints。

**驗收標準**
- schema 變動會被測試抓到。
- 前端 types 可依 contract 更新。

**測試要求**
- contract tests with sample responses。

**相依任務**
GS-P2-010, GS-P5-003

**風險與注意事項**
- 保持 MVP 範圍，避免順手實作多人協作、即時轉譜或線上修譜。

### GS-P7-005 — 建立人工準確度評估流程

**Ticket ID**
GS-P7-005

**Ticket 名稱**
建立人工準確度評估流程

**背景與目的**
建立小型人工評估流程，用可用性評分衡量 MVP 是否值得繼續。

**實作範圍**
- 建立 10 首以內短片段評估清單。
- 定義 kick/snare/hi-hat/readability/usability 1-5 分。
- 定義 ±50ms onset 容忍說明。
- 建立評估記錄模板。

**不包含範圍**
- 不建立大型學術 benchmark。
- 不承諾產品準確率百分比。

**主要修改位置或建議目錄**
- tests/manual_eval/
- docs/

**輸入**
- pipeline outputs。
- 人工聆聽與標註。

**輸出**
- manual evaluation records。

**API / Data Model / Storage 關聯**
- Data：可引用 job_id / artifact keys；不影響 API。

**驗收標準**
- 至少 5 首音檔完成評估。
- 評估結果可用於 MVP go/no-go。

**測試要求**
- 人工流程演練。

**相依任務**
GS-P1-008, GS-P7-003

**風險與注意事項**
- 保持 MVP 範圍，避免順手實作多人協作、即時轉譜或線上修譜。

### GS-P7-006 — 建立 MVP 驗收 checklist

**Ticket ID**
GS-P7-006

**Ticket 名稱**
建立 MVP 驗收 checklist

**背景與目的**
把產品、工程、測試標準整理成 release 前 checklist。

**實作範圍**
- 列出 API、worker、pipeline、frontend、exports、errors、storage、deployment 驗收項目。
- 定義通過 / 失敗 / 備註欄位。
- 連結 Level 1/2/3 文件。

**不包含範圍**
- 不做自動化 release management。

**主要修改位置或建議目錄**
- docs/03_工程實作任務/
- tests/manual_eval/

**輸入**
- Level 1/2/3 驗收標準。

**輸出**
- MVP acceptance checklist。

**API / Data Model / Storage 關聯**
- 涵蓋 API/Data/Storage/Frontend/Pipeline。

**驗收標準**
- Checklist 覆蓋 API upload / status / result / download。
- Checklist 覆蓋 worker queued → processing → completed / failed。
- Checklist 覆蓋完整 pipeline artifacts：normalized WAV、drums stem、raw MIDI、processed MIDI、drum_events JSON、MusicXML、PDF。
- Checklist 覆蓋前端上傳、輪詢、錯誤、預覽、下載。
- Checklist 覆蓋 storage adapter、local storage volume、不暴露 local path。
- Checklist 覆蓋已知失敗情境與使用者提示。
- Checklist 有 `Pass / Fail / N/A / Notes / Owner / Date` 欄位。

**測試要求**
- 文件 review：至少一位工程師可依 checklist 完成 dry run。
- 手動驗收：用一首短音檔跑完整 MVP path 並填寫 checklist。
- 失敗路徑驗收：至少驗證非法檔案、pipeline failed job、PDF export failed fallback。
- 確認 checklist 連回對應 Level 1 / Level 2 / Level 3 文件。

**相依任務**
GS-P7-001, GS-P7-002, GS-P7-003

**風險與注意事項**
- 保持 MVP 範圍，避免順手實作多人協作、即時轉譜或線上修譜。

### GS-P7-007 — 建立 regression test 流程

**Ticket ID**
GS-P7-007

**Ticket 名稱**
建立 regression test 流程

**背景與目的**
建立固定輸入與 artifact 層級的回歸檢查，避免 pipeline 改動破壞基本可用性。

**實作範圍**
- 定義固定 regression fixtures。
- 比對 event count 合理區間、MIDI parse、MusicXML parse、PDF exists。
- 記錄模型版本造成的輸出差異。

**不包含範圍**
- 不做 byte-by-byte AI output snapshot。

**主要修改位置或建議目錄**
- tests/regression/
- tests/pipeline/

**輸入**
- 固定測試音檔。
- pipeline output。

**輸出**
- regression report。

**API / Data Model / Storage 關聯**
- Storage artifacts 與 pipeline version metadata。

**驗收標準**
- 修改 pipeline 後可重跑 regression。
- 避免因模型非決定性造成誤報。

**測試要求**
- regression command。
- manual result review。

**相依任務**
GS-P7-003, GS-P4-008

**風險與注意事項**
- 保持 MVP 範圍，避免順手實作多人協作、即時轉譜或線上修譜。

### GS-P7-008 — 建立瀏覽器端 E2E smoke test

**Ticket ID**
GS-P7-008

**Ticket 名稱**
建立瀏覽器端 E2E smoke test

**背景與目的**
建立最小瀏覽器端端到端檢查，覆蓋使用者實際路徑：上傳、導向結果頁、輪詢、完成、預覽、下載。這能補足 unit / integration / pipeline tests 無法覆蓋的 UI 串接風險。

**實作範圍**
- 建立 Playwright 或等效 E2E smoke test。
- 使用 mock backend 或短 fixture pipeline 覆蓋上傳成功流程。
- 驗證 `/jobs/{job_id}` 導向、processing 顯示、completed 顯示、下載按鈕顯示。
- 驗證 failed job 顯示錯誤訊息。
- 文件化本地執行命令與前置服務。

**不包含範圍**
- 不跑長時間真實 Demucs / ADTOF 作為每次 E2E 必跑項。
- 不做跨瀏覽器完整矩陣。
- 不做視覺回歸測試。

**主要修改位置或建議目錄**
- tests/e2e/
- frontend/e2e/
- docs/03_工程實作任務/

**輸入**
- 前端 app。
- mock API 或測試用 backend。
- fixture job response。

**輸出**
- E2E smoke test suite。
- 本地執行說明。

**API / Data Model / Storage 關聯**
- API：upload、status、result、download endpoints。
- Data / Storage 可透過 mock 或測試 fixture 間接驗證。

**驗收標準**
- 一條 happy path E2E 可穩定通過。
- 一條 failed job E2E 可穩定通過。
- 測試命令與需要啟動的服務寫清楚。

**測試要求**
- E2E smoke test：upload success → job page → completed → downloads visible。
- E2E smoke test：failed status → error UI visible。

**相依任務**
GS-P5-009, GS-P5-005, GS-P5-007, GS-P6-002, GS-P6-004

**風險與注意事項**
- E2E smoke test 應快且穩定；真模型長任務留給 pipeline slow tests 或手動驗收。

## Phase 完成標準

- 主要測試類型可執行。
- MVP 驗收 checklist 完成。
- 至少 5 首測試音檔完成人工檢查紀錄。
