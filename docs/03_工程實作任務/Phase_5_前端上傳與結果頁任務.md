# Phase 5：前端上傳與結果頁任務

> Level 3 工程實作任務文件。本文只拆解開發 ticket，不取代 Level 1 / Level 2 規格。

## Phase 目標

建立 MVP Web UI，讓使用者可以上傳單首音檔、查看 job 狀態、看到錯誤與下載輸出。

## 前置條件

- Phase 2 API contract 已定義。
- Phase 3 status API 與 mock worker 可用。
- 前端技術選型確定為 TypeScript + React / Next.js 或 Vite。

## 需參考的 Level 1 / Level 2 文件

- Level 1：產品需求文件.md
- Level 1：API設計.md
- Level 2：前端頁面與互動規格.md
- Level 2：音檔上傳功能規格.md
- Level 2：背景任務與Job狀態規格.md
- Level 2：錯誤處理與使用者提示規格.md

## 任務清單

- `GS-P5-001`：建立前端專案骨架
- `GS-P5-002`：建立上傳頁
- `GS-P5-003`：建立 API client
- `GS-P5-004`：建立 job result page
- `GS-P5-005`：建立 job status polling
- `GS-P5-006`：建立錯誤狀態 UI
- `GS-P5-007`：建立下載按鈕
- `GS-P5-008`：建立使用者準確度提示文案
- `GS-P5-009`：串接上傳表單、Upload API 與成功導向

## Ticket 詳細內容

### GS-P5-001 — 建立前端專案骨架

**Ticket ID**
GS-P5-001

**Ticket 名稱**
建立前端專案骨架

**背景與目的**
建立 TypeScript 前端 app，作為上傳與結果頁實作基礎。

**實作範圍**
- 建立 React / Next.js 或 Vite 專案。
- 設定 TypeScript、lint、test runner。
- 建立基本 layout 與 route 結構。

**不包含範圍**
- 不做登入。
- 不做行銷 landing page。

**主要修改位置或建議目錄**
- frontend/
- frontend/src/app/
- frontend/src/components/

**輸入**
- 前端技術選型。

**輸出**
- 可啟動前端 dev server。

**API / Data Model / Storage 關聯**
- API client base URL config 預留。無 Data Model / Storage。

**驗收標準**
- 本機可啟動。
- 基本 smoke test 通過。

**測試要求**
- frontend smoke test。

**相依任務**
無

**風險與注意事項**
- 保持 MVP 範圍，避免順手實作多人協作、即時轉譜或線上修譜。

### GS-P5-002 — 建立上傳頁

**Ticket ID**
GS-P5-002

**Ticket 名稱**
建立上傳頁

**背景與目的**
建立音檔上傳 UI，支援單檔選擇、格式提示與前端預檢。

**實作範圍**
- 建立 upload page。
- 支援 drag-and-drop 或 file input。
- 限制單檔。
- 顯示 MP3/WAV、100MB、10 分鐘限制提示。
- 提供 optional title 欄位。

**不包含範圍**
- 不做瀏覽器端轉碼。
- 不做波形預覽。

**主要修改位置或建議目錄**
- frontend/src/features/transcriptions/upload/

**輸入**
- 使用者選取音檔與 title。

**輸出**
- 待送出的 FormData。
- 前端預檢錯誤。

**API / Data Model / Storage 關聯**
- API：將串 `POST /api/v1/transcriptions`。

**驗收標準**
- 非法副檔名與超過大小有 UI 提示。
- 單檔上傳限制有效。

**測試要求**
- component tests：檔案限制。

**相依任務**
GS-P5-001

**風險與注意事項**
- 保持 MVP 範圍，避免順手實作多人協作、即時轉譜或線上修譜。

### GS-P5-003 — 建立 API client

**Ticket ID**
GS-P5-003

**Ticket 名稱**
建立 API client

**背景與目的**
建立前端 API client 與 TypeScript types，統一處理 upload、status、result、download URL。

**實作範圍**
- 定義 JobStatus、Stage、UploadResponse、StatusResponse、ResultResponse、ApiError types。
- 建立 uploadTranscription、getJobStatus、getResult helpers。
- 統一解析 error response。

**不包含範圍**
- 不建立 GraphQL。
- 不在 client 內重試長任務結果。

**主要修改位置或建議目錄**
- frontend/src/lib/api/
- frontend/src/types/

**輸入**
- API base URL。
- API response schema。

**輸出**
- typed API client。

**API / Data Model / Storage 關聯**
- API：所有 `/api/v1/transcriptions` endpoints。

**驗收標準**
- API client 可被頁面使用。
- 錯誤格式統一。

**測試要求**
- unit tests：error parser。
- mock tests：upload/status/result。

**相依任務**
GS-P5-001, GS-P2-006, GS-P2-007, GS-P2-008

**風險與注意事項**
- 保持 MVP 範圍，避免順手實作多人協作、即時轉譜或線上修譜。

### GS-P5-004 — 建立 job result page

**Ticket ID**
GS-P5-004

**Ticket 名稱**
建立 job result page

**背景與目的**
建立 `/jobs/{job_id}` 頁面，承接上傳成功後的任務狀態與結果呈現。

**實作範圍**
- 建立 job route。
- 讀取 job_id。
- 顯示基本狀態容器。
- 預留 preview 與 downloads 區塊。

**不包含範圍**
- 不整合 MusicXML preview；Phase 6 處理。

**主要修改位置或建議目錄**
- frontend/src/app/jobs/[job_id]/
- frontend/src/features/transcriptions/result/

**輸入**
- job_id route param。

**輸出**
- 結果頁 UI skeleton。

**API / Data Model / Storage 關聯**
- API：會呼叫 status/result。

**驗收標準**
- 上傳成功可導向此頁。
- 無 job_id 時有合理錯誤。

**測試要求**
- route test。
- render test。

**相依任務**
GS-P5-001, GS-P5-003

**風險與注意事項**
- 保持 MVP 範圍，避免順手實作多人協作、即時轉譜或線上修譜。

### GS-P5-005 — 建立 job status polling

**Ticket ID**
GS-P5-005

**Ticket 名稱**
建立 job status polling

**背景與目的**
在結果頁建立輪詢邏輯，根據 queued / processing / completed / failed 切換 UI。

**實作範圍**
- 每 2-5 秒呼叫 status API。
- completed / failed 停止輪詢。
- 網路暫時錯誤不把 job 判定 failed。
- completed 後呼叫 result API。

**不包含範圍**
- 不做 WebSocket / SSE。

**主要修改位置或建議目錄**
- frontend/src/features/transcriptions/result/useJobStatus.ts

**輸入**
- job_id。
- status API response。

**輸出**
- UI state：loading、processing、completed、failed、network warning。

**API / Data Model / Storage 關聯**
- API：status/result endpoints。

**驗收標準**
- processing 會持續輪詢。
- completed 後停止並載入 result。
- failed 後停止顯示錯誤。

**測試要求**
- hook tests with fake timers。
- API mock tests。

**相依任務**
GS-P5-003, GS-P5-004, GS-P2-007, GS-P2-008

**風險與注意事項**
- 保持 MVP 範圍，避免順手實作多人協作、即時轉譜或線上修譜。

### GS-P5-006 — 建立錯誤狀態 UI

**Ticket ID**
GS-P5-006

**Ticket 名稱**
建立錯誤狀態 UI

**背景與目的**
建立上傳、輪詢、job failed、preview 失敗等錯誤提示。

**實作範圍**
- 顯示 API `error.message`。
- 依 retriable 顯示重新上傳或稍後再試。
- 避免顯示 stack trace。
- 提供返回上傳頁。

**不包含範圍**
- 不做錯誤回報系統。

**主要修改位置或建議目錄**
- frontend/src/components/ErrorState.tsx
- frontend/src/features/transcriptions/

**輸入**
- ApiError。
- Job failed error。

**輸出**
- 錯誤 UI。

**API / Data Model / Storage 關聯**
- API error response schema。

**驗收標準**
- 所有主要錯誤狀態有可理解文案。
- 不顯示技術細節。

**測試要求**
- component tests：error variants。

**相依任務**
GS-P5-003, GS-P2-010

**風險與注意事項**
- 保持 MVP 範圍，避免順手實作多人協作、即時轉譜或線上修譜。

### GS-P5-007 — 建立下載按鈕

**Ticket ID**
GS-P5-007

**Ticket 名稱**
建立下載按鈕

**背景與目的**
completed result 中顯示 MIDI / MusicXML / PDF 下載入口。

**實作範圍**
- 根據 result.exports render buttons。
- PDF failed 或缺失時停用對應按鈕。
- 下載使用 API URL，不使用 storage key。

**不包含範圍**
- 不做下載歷史。
- 不做 raw MIDI download。

**主要修改位置或建議目錄**
- frontend/src/features/transcriptions/result/DownloadButtons.tsx

**輸入**
- ResultResponse.exports。

**輸出**
- download buttons。

**API / Data Model / Storage 關聯**
- API：download endpoints；Storage 不暴露。

**驗收標準**
- available export 可點擊。
- 不可用 export 有清楚狀態。

**測試要求**
- component test：available/failed exports。

**相依任務**
GS-P5-005, GS-P2-009

**風險與注意事項**
- 保持 MVP 範圍，避免順手實作多人協作、即時轉譜或線上修譜。

### GS-P5-008 — 建立使用者準確度提示文案

**Ticket ID**
GS-P5-008

**Ticket 名稱**
建立使用者準確度提示文案

**背景與目的**
在上傳與結果頁顯示 AI 鼓譜草稿的預期準確度與限制，避免過度承諾。

**實作範圍**
- 加入固定提示文案。
- 說明輸出是可編輯草稿。
- 說明 hi-hat 開閉、crash/ride、ghost note 不保證。
- 在 result warnings 顯示模型警告。

**不包含範圍**
- 不做完整 FAQ。
- 不做準確度百分比承諾。

**主要修改位置或建議目錄**
- frontend/src/content/accuracyNotice.ts
- frontend/src/features/transcriptions/

**輸入**
- Level 1/2 accuracy wording。
- ResultResponse.warnings。

**輸出**
- 使用者提示 UI。

**API / Data Model / Storage 關聯**
- Data：DrumTrack.warnings 由 API result 提供。

**驗收標準**
- 上傳頁與結果頁都有清楚提示。
- warnings 可被顯示。

**測試要求**
- content render tests。

**相依任務**
GS-P5-002, GS-P5-003, GS-P5-005, GS-P2-008

**風險與注意事項**
- 保持 MVP 範圍，避免順手實作多人協作、即時轉譜或線上修譜。

### GS-P5-009 — 串接上傳表單、Upload API 與成功導向

**Ticket ID**
GS-P5-009

**Ticket 名稱**
串接上傳表單、Upload API 與成功導向

**背景與目的**
補足上傳頁到結果頁的核心互動：使用者送出音檔後，前端呼叫 Upload API，處理 `202 Accepted`，並導向 `/jobs/{job_id}`。這是使用者流程能否成立的關鍵 ticket。

**實作範圍**
- 將上傳頁 FormData 接到 `uploadTranscription` API client。
- 處理上傳中、成功、失敗狀態。
- 成功收到 `job_id` 後導向 `/jobs/{job_id}`。
- 失敗時顯示 API `error.message`，並保留使用者可重新送出。
- 補上重複送出保護。

**不包含範圍**
- 不做 direct-to-S3 upload。
- 不做批次上傳。
- 不做音檔波形預覽。

**主要修改位置或建議目錄**
- frontend/src/features/transcriptions/upload/
- frontend/src/lib/api/
- frontend/src/app/jobs/[job_id]/

**輸入**
- 使用者選取的 MP3 / WAV。
- optional title。

**輸出**
- Upload API request。
- 成功導向 `/jobs/{job_id}`。
- 上傳錯誤 UI。

**API / Data Model / Storage 關聯**
- API：`POST /api/v1/transcriptions`。
- Data：前端不直接讀寫 Data Model。
- Storage：前端不接觸 storage key。

**驗收標準**
- 合法檔案送出後會呼叫 Upload API。
- 收到 202 後導向正確 job result page。
- Upload API 失敗時顯示錯誤，且不導向。
- 送出期間按鈕停用，避免重複建立 job。

**測試要求**
- API mock test：upload success → route push `/jobs/{job_id}`。
- API mock test：upload error → 顯示 `error.message`。
- component test：送出期間按鈕 disabled。

**相依任務**
GS-P5-002, GS-P5-003, GS-P5-004, GS-P5-006, GS-P2-006

**風險與注意事項**
- 前端不可假設 API 會立即有結果；成功後只能進入輪詢狀態。

## Phase 完成標準

- 使用者可完成上傳並進入結果頁。
- 結果頁可輪詢 queued / processing / completed / failed。
- 完成後顯示下載按鈕與準確度提示。
