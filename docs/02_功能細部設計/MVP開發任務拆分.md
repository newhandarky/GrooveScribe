# MVP 開發任務拆分

> Level 2 功能細部設計。本文延伸 Level 1 產品與系統架構文件，不取代既有規劃。

## 功能目標

- 將 Level 1 與 Level 2 規格拆成可執行工程 ticket。
- 明確定義前端、後端、worker、AI pipeline、storage、測試與部署的交付順序。
- 確保每個 ticket 都有完成標準，不先建立大型不可驗證功能。

## 使用者情境

- 產品開發團隊可按階段交付，先證明本地 pipeline，再接 API 與 UI。
- 測試者可在每個 phase 結束時驗收具體成果。

## 前端行為

- FE-01：建立上傳頁與檔案預檢。
- FE-02：串接 upload API 與導向結果頁。
- FE-03：建立 job status polling。
- FE-04：建立 completed / failed / loading UI。
- FE-05：整合 MusicXML preview 與下載按鈕。

## 後端行為

- BE-01：建立 FastAPI 專案骨架與 health check。
- BE-02：建立 SQLAlchemy models 與 migration：User、AudioFile、TranscriptionJob、DrumTrack、ExportFile。
- BE-03：建立 StorageAdapter 與 LocalStorageAdapter。
- BE-04：實作 upload API。
- BE-05：實作 status / result / download API。
- BE-06：實作錯誤 response middleware 與 error catalog。

## Worker / Pipeline 行為

- WK-01：建立 Celery + Redis worker。
- WK-02：實作 job state updater 與 pipeline runner。
- AI-01：建立 ffmpeg preprocessing adapter。
- AI-02：建立 Demucs SourceSeparator adapter。
- AI-03：建立 ADTOF DrumTranscriber adapter。
- AI-04：建立 MIDI post-processing module。
- AI-05：建立 MusicXML / PDF export module。

## 輸入資料

- 測試音檔：乾淨鼓軌、一般完整歌曲、鼓聲不明顯歌曲、損壞音檔、超短音檔。
- Level 1 / Level 2 文件。
- API payload 與 artifact key convention。

## 輸出資料

- 可跑本地 pipeline 的 script 或 runner。
- 可上傳與查詢 job 的 API。
- 可操作的前端頁面。
- 可下載 MIDI / MusicXML / PDF。
- 單元、整合與 pipeline 測試。

## API 關聯

- API tickets 依序完成 upload、status、result、download。
- 前端 tickets 不等待完整 AI pipeline，可先用 mock API。
- Worker tickets 可先用 mock adapter 產生假 artifacts，再替換成真模型。

## Data Model 關聯

- DB-01：建立資料模型與 enum。
- DB-02：建立狀態轉移 service。
- DB-03：建立 ExportFile 查詢與下載權限檢查。

## Storage / Artifact 關聯

- ST-01：定義 ArtifactRef 與 artifact types。
- ST-02：實作 local key naming 與 sanitizer。
- ST-03：串接 upload、worker、download。
- ST-04：補 S3 adapter interface stub，不必在 MVP 完成真 S3。

## 狀態流轉

建議開發順序：

```text
Phase 1 local pipeline POC
→ Phase 2 backend models/storage/API/queue
→ Phase 3 frontend upload/status
→ Phase 4 notation preview/export
→ Phase 5 tests/deployment
```

## 錯誤情境

- 模型安裝阻塞：先以 mock adapter 完成 API / worker flow。
- PDF renderer 不穩：讓 MusicXML 作為核心譜面輸出，PDF ticket 可獨立驗收。
- GPU 不足：先以短音檔與 CPU proof of concept 驗證流程。
- Storage 權限問題：先完成 LocalStorageAdapter 測試。

## 驗收標準

- Phase 1：本地跑完一首音檔，產生所有 artifacts。
- Phase 2：API 上傳後 worker 可處理 job，狀態可查。
- Phase 3：前端可上傳、等待、顯示完成或失敗。
- Phase 4：結果頁可預覽 MusicXML，下載 MIDI / MusicXML / PDF。
- Phase 5：主要測試通過，Docker Compose 可啟動完整 MVP。

## 測試案例

- TEST-01：validators 與 data model unit tests。
- TEST-02：storage adapter tests。
- TEST-03：API integration tests。
- TEST-04：worker orchestration tests with mock adapters。
- TEST-05：slow pipeline tests with fixture audio。
- TEST-06：frontend API mock tests。

## 非 MVP 範圍

- 先不拆微服務。
- 先不做登入、付款、歷史列表。
- 先不做線上修譜。
- 先不做多模型 fallback，只保留 interface。

## 未來擴充方向

- 完成 MVP 後加入使用者帳號與歷史。
- 加入第二模型 fallback ticket。
- 加入譜面編輯與重新匯出。
- 加入 S3 production storage 與 job cleanup。
