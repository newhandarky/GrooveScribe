# Phase 6：樂譜預覽與匯出任務

> Level 3 工程實作任務文件。本文只拆解開發 ticket，不取代 Level 1 / Level 2 規格。

## Phase 目標

完成 MusicXML 網頁預覽、PDF export 驗證與 fallback UI，讓使用者能查看並下載簡單鼓譜。

## 前置條件

- Phase 1/4 可產生 MusicXML 與 PDF artifact。
- Phase 2 Download API 可回傳 MusicXML/PDF。
- Phase 5 結果頁與下載按鈕已完成。

## 需參考的 Level 1 / Level 2 文件

- Level 1：產品需求文件.md
- Level 1：技術選型.md
- Level 2：鼓譜預覽與匯出規格.md
- Level 2：MIDI後處理與量化規格.md
- Level 2：前端頁面與互動規格.md

## 任務清單

- `GS-P6-001`：整合 OpenSheetMusicDisplay
- `GS-P6-002`：建立 MusicXML preview component
- `GS-P6-003`：建立 PDF export 檢查流程
- `GS-P6-004`：建立 MusicXML / PDF 失敗 fallback UI
- `GS-P6-005`：驗證 MusicXML 可被 MuseScore 開啟
- `GS-P6-006`：驗證 PDF 可正常下載與打開

## Ticket 詳細內容

### GS-P6-001 — 整合 OpenSheetMusicDisplay

**Ticket ID**
GS-P6-001

**Ticket 名稱**
整合 OpenSheetMusicDisplay

**背景與目的**
加入 OpenSheetMusicDisplay 依賴與基本載入策略，作為 MusicXML 預覽基礎。

**實作範圍**
- 安裝並封裝 OSMD。
- 建立 lazy-loaded score renderer。
- 處理容器尺寸與 loading state。

**不包含範圍**
- 不做逐音符編輯。
- 不做 VexFlow 自研 renderer。

**主要修改位置或建議目錄**
- frontend/src/lib/score/
- frontend/src/components/score/

**輸入**
- MusicXML URL 或 XML string。

**輸出**
- Score renderer 基礎元件。

**API / Data Model / Storage 關聯**
- API：使用 result.preview.musicxml_url。

**驗收標準**
- OSMD 可在頁面載入。
- 載入中與錯誤狀態可控。

**測試要求**
- component test：renderer mount。
- manual test：載入 sample MusicXML。

**相依任務**
GS-P5-004, GS-P5-005

**風險與注意事項**
- 保持 MVP 範圍，避免順手實作多人協作、即時轉譜或線上修譜。

### GS-P6-002 — 建立 MusicXML preview component

**Ticket ID**
GS-P6-002

**Ticket 名稱**
建立 MusicXML preview component

**背景與目的**
在結果頁渲染 MusicXML 鼓譜預覽。

**實作範圍**
- 建立 Preview component。
- 使用 download/musicxml URL fetch MusicXML。
- 渲染單軌鼓譜。
- 顯示 loading / error fallback。

**不包含範圍**
- 不做譜面縮放進階工具。
- 不做同步播放。

**主要修改位置或建議目錄**
- frontend/src/features/transcriptions/result/ScorePreview.tsx

**輸入**
- musicxml_url。

**輸出**
- 鼓譜預覽 UI。

**API / Data Model / Storage 關聯**
- API：download/musicxml；Storage 不直接暴露。

**驗收標準**
- completed job 可看到預覽。
- MusicXML fetch 失敗時不影響下載按鈕。

**測試要求**
- API mock test：preview success/error。

**相依任務**
GS-P6-001, GS-P5-005, GS-P2-009, GS-P4-006, GS-P4-011

**風險與注意事項**
- 保持 MVP 範圍，避免順手實作多人協作、即時轉譜或線上修譜。

### GS-P6-003 — 建立 PDF export 檢查流程

**Ticket ID**
GS-P6-003

**Ticket 名稱**
建立 PDF export 檢查流程

**背景與目的**
在 pipeline / worker 層確認 PDF export 是否成功，並以 ExportFile 狀態反映。

**實作範圍**
- PDF 產生後檢查檔案存在、大小、content type。
- PDF failed 時建立或更新 ExportFile(status=failed)。
- Result API 能回傳 PDF 可用或失敗狀態。

**不包含範圍**
- 不改 PDF 排版。
- 不做 PDF 線上預覽。

**主要修改位置或建議目錄**
- ai_pipeline/notation/
- worker/app/pipeline_runner.py
- backend/app/services/result_service.py

**輸入**
- score.musicxml。
- PDF renderer result。

**輸出**
- score.pdf 或 failed ExportFile。

**API / Data Model / Storage 關聯**
- Data：ExportFile(type=pdf,status)。Storage：`jobs/{job_id}/exports/score.pdf`。

**驗收標準**
- PDF 成功時可下載。
- PDF 失敗時 result API 不誤報 available。

**測試要求**
- integration test：PDF success/failed metadata。

**相依任務**
GS-P4-006, GS-P2-008, GS-P2-009

**風險與注意事項**
- 保持 MVP 範圍，避免順手實作多人協作、即時轉譜或線上修譜。

### GS-P6-004 — 建立 MusicXML / PDF 失敗 fallback UI

**Ticket ID**
GS-P6-004

**Ticket 名稱**
建立 MusicXML / PDF 失敗 fallback UI

**背景與目的**
前端根據 export status 與 preview error 顯示 fallback，避免部分失敗造成整頁不可用。

**實作範圍**
- MusicXML preview 失敗時顯示 fallback。
- PDF export failed 時停用 PDF 按鈕並顯示原因。
- MIDI / MusicXML 可用時仍允許下載。

**不包含範圍**
- 不做自助重新匯出 PDF。

**主要修改位置或建議目錄**
- frontend/src/features/transcriptions/result/

**輸入**
- ResultResponse.exports。
- preview error。

**輸出**
- fallback UI。

**API / Data Model / Storage 關聯**
- API：result exports。

**驗收標準**
- PDF failed 不影響 MIDI / MusicXML 下載。
- 預覽錯誤文案清楚。

**測試要求**
- component tests：PDF failed、preview failed。

**相依任務**
GS-P6-002, GS-P6-003, GS-P5-007

**風險與注意事項**
- 保持 MVP 範圍，避免順手實作多人協作、即時轉譜或線上修譜。

### GS-P6-005 — 驗證 MusicXML 可被 MuseScore 開啟

**Ticket ID**
GS-P6-005

**Ticket 名稱**
驗證 MusicXML 可被 MuseScore 開啟

**背景與目的**
建立人工與自動檢查流程，確認輸出 MusicXML 是可交換格式。

**實作範圍**
- 準備 sample output。
- 用 XML parser 做基本檢查。
- 手動用 MuseScore 開啟並記錄結果。
- 建立檢查 checklist。

**不包含範圍**
- 不自動化完整 MuseScore GUI 測試。

**主要修改位置或建議目錄**
- tests/pipeline/
- tests/manual_eval/

**輸入**
- score.musicxml。

**輸出**
- MusicXML validation report。

**API / Data Model / Storage 關聯**
- Storage：`score.musicxml` artifact；Data：ExportFile musicxml available。

**驗收標準**
- sample MusicXML 可被 MuseScore 開啟。
- 檢查流程可重複。

**測試要求**
- XML parse test。
- manual checklist。

**相依任務**
GS-P1-006, GS-P6-002, GS-P4-006

**風險與注意事項**
- 保持 MVP 範圍，避免順手實作多人協作、即時轉譜或線上修譜。

### GS-P6-006 — 驗證 PDF 可正常下載與打開

**Ticket ID**
GS-P6-006

**Ticket 名稱**
驗證 PDF 可正常下載與打開

**背景與目的**
建立 PDF smoke test 與人工驗證流程，確認 PDF export 可用。

**實作範圍**
- 檢查 PDF header / file size。
- 透過 Download API 下載 PDF。
- 手動打開 PDF 並記錄結果。

**不包含範圍**
- 不做 PDF 排版精修。

**主要修改位置或建議目錄**
- tests/integration/
- tests/manual_eval/

**輸入**
- job_id、download/pdf URL。

**輸出**
- PDF validation report。

**API / Data Model / Storage 關聯**
- API：download/pdf；Data：ExportFile pdf；Storage：score.pdf。

**驗收標準**
- PDF 下載 content type 正確。
- PDF 可打開。

**測試要求**
- integration test：download PDF。
- manual PDF open checklist。

**相依任務**
GS-P6-003, GS-P2-009, GS-P4-006

**風險與注意事項**
- 保持 MVP 範圍，避免順手實作多人協作、即時轉譜或線上修譜。

## Phase 完成標準

- 前端可渲染 MusicXML 預覽。
- MusicXML 可被 MuseScore 開啟。
- PDF 可下載並打開。
- MusicXML / PDF 失敗時 UI 有 fallback。
