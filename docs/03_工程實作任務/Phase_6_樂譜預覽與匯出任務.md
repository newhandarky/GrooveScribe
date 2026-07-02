# Phase 6：Preview、Export 與 Artifact UX 任務

> 本文件已依 local-first 完整 V1 方向重整。詳細 ticket 以 `V1_Ticket總表.md` 為準。

## Phase 目標

讓使用者能在 localhost UI 檢查 MusicXML preview、下載 MIDI / MusicXML / PDF，並理解 PDF export warning 或 partial success。

## V1 重點

- MusicXML 是譜面預覽與 PDF export 的主要來源。
- PDF 是可用輸出，但 PDF renderer failure 不應讓整個 job 失敗。
- Artifact / pipeline log 應有工程診斷入口。

## 主要任務

- `GS-V1-P6-001`：整合 OpenSheetMusicDisplay。
- `GS-V1-P6-002`：建立 MusicXML preview component。
- `GS-V1-P6-003`：建立 PDF export 狀態與 fallback UI。
- `GS-V1-P6-004`：建立 artifact / pipeline log 檢視入口。
- `GS-V1-P6-005`：建立重新執行 job 的產品規則。

## 驗收標準

- completed job 可在結果頁看到鼓譜預覽。
- MusicXML 可被 MuseScore 或相容軟體開啟。
- PDF 可下載並打開，或在失敗時清楚顯示 fallback。
- MIDI / MusicXML / PDF download 不暴露本機真實路徑。

## 參考文件

- `docs/02_功能細部設計/鼓譜預覽與匯出規格.md`
- `docs/02_功能細部設計/前端頁面與互動規格.md`
- `docs/產品完整度標準.md`
- `docs/03_工程實作任務/V1_Ticket總表.md`
