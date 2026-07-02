# Phase 5：Local Web App 任務

> 本文件已依 local-first 完整 V1 方向重整。詳細 ticket 以 `V1_Ticket總表.md` 為準。

## Phase 目標

建立完整可操作的 localhost browser UI，讓使用者能上傳單首音檔、查看 job 狀態、理解錯誤與 warning，並下載輸出。

## V1 重點

- UI 是 Local Web App，不是雲端 landing page。
- 使用者操作第一屏應是實際上傳 / job 流程。
- 前端透過 typed API client 呼叫 localhost backend。
- UI 必須處理 queued、processing、completed、failed、interrupted、partial success。

## 主要任務

- `GS-V1-P5-001`：建立 local web app 基礎 layout。
- `GS-V1-P5-002`：建立上傳頁與前端預檢。
- `GS-V1-P5-003`：建立 typed API client。
- `GS-V1-P5-004`：建立 job result page。
- `GS-V1-P5-005`：建立 job status polling 與 stage UI。
- `GS-V1-P5-006`：建立錯誤、warning 與準確度提醒 UI。
- `GS-V1-P5-007`：建立下載按鈕與 partial success UI。
- `GS-V1-P5-008`：建立 runtime preflight / diagnostics UI。

## 驗收標準

- 使用者可從 localhost UI 上傳 MP3 / WAV。
- 上傳成功後自動進入 job result page。
- 分析中能看到狀態更新。
- 分析完成後能下載輸出檔案。
- 分析失敗時顯示可理解的錯誤訊息與下一步建議。

## 參考文件

- `docs/產品需求文件.md`
- `docs/API設計.md`
- `docs/02_功能細部設計/前端頁面與互動規格.md`
- `docs/產品完整度標準.md`
- `docs/03_工程實作任務/V1_Ticket總表.md`
