# MVP Ticket 總表

> Level 3 工程實作任務總覽。完成狀態預設為 Todo。

| Ticket ID | Phase | Ticket 名稱 | 優先級 | 預估難度 | 相依任務 | 對應文件 | 完成狀態 |
|---|---|---|---|---|---|---|---|
| `GS-P1-001` | Phase 1 | 建立 Python 專案骨架 | P0 | M | 無 | Level 1：專案目錄結構.md, Level 1：技術選型.md, Level 2：MVP開發任務拆分.md | Todo |
| `GS-P1-002` | Phase 1 | 建立 ffmpeg 音訊標準化 script | P0 | M | GS-P1-001 | Level 2：ffmpeg音訊標準化規格.md | Todo |
| `GS-P1-003` | Phase 1 | 整合 Demucs 鼓軌分離 | P0 | L | GS-P1-002, GS-P1-009 | Level 2：Demucs鼓軌分離規格.md | Todo |
| `GS-P1-004` | Phase 1 | 整合 ADTOF-pytorch 鼓 MIDI 轉寫 | P0 | L | GS-P1-003, GS-P1-009 | Level 2：ADTOF鼓MIDI轉寫規格.md | Todo |
| `GS-P1-005` | Phase 1 | 建立 MIDI 後處理初版 | P0 | L | GS-P1-004 | Level 2：MIDI後處理與量化規格.md | Todo |
| `GS-P1-006` | Phase 1 | 建立 MusicXML / PDF 輸出初版 | P0 | L | GS-P1-005 | Level 2：鼓譜預覽與匯出規格.md | Todo |
| `GS-P1-007` | Phase 1 | 建立本地 pipeline runner | P0 | M | GS-P1-002, GS-P1-003, GS-P1-004, GS-P1-005, GS-P1-006 | Level 2：AI_Pipeline執行規格.md | Todo |
| `GS-P1-008` | Phase 1 | 準備測試音檔與人工檢查表 | P1 | S | GS-P1-007 | Level 1：測試策略.md | Todo |
| `GS-P1-009` | Phase 1 | 鎖定 AI runtime 與安裝重現紀錄 | P0 | S | GS-P1-001 | Level 1：開發計畫.md, Level 1：技術選型.md, Level 2：AI_Pipeline執行規格.md | Todo |
| `GS-P2-001` | Phase 2 | 建立 FastAPI 專案骨架 | P0 | M | 無 | Level 1：技術選型.md, Level 1：API設計.md | Todo |
| `GS-P2-002` | Phase 2 | 建立 database models | P0 | M | GS-P2-001 | Level 1：資料模型設計.md | Todo |
| `GS-P2-003` | Phase 2 | 建立 Alembic migrations | P0 | M | GS-P2-002 | Level 1：資料模型設計.md | Todo |
| `GS-P2-004` | Phase 2 | 建立 Storage Adapter interface | P0 | M | GS-P2-001 | Level 2：檔案儲存與Artifact規格.md | Todo |
| `GS-P2-005` | Phase 2 | 建立 LocalStorageAdapter | P0 | M | GS-P2-004 | Level 2：檔案儲存與Artifact規格.md | Todo |
| `GS-P2-006` | Phase 2 | 建立 Upload API | P0 | L | GS-P2-002, GS-P2-005, GS-P2-010 | Level 2：音檔上傳功能規格.md | Todo |
| `GS-P2-007` | Phase 2 | 建立 Job Status API | P0 | M | GS-P2-002, GS-P2-010 | Level 1：API設計.md, Level 2：背景任務與Job狀態規格.md | Todo |
| `GS-P2-008` | Phase 2 | 建立 Result API | P0 | M | GS-P2-002, GS-P2-007, GS-P2-010 | Level 1：API設計.md | Todo |
| `GS-P2-009` | Phase 2 | 建立 Download API | P0 | M | GS-P2-005, GS-P2-008, GS-P2-010 | Level 2：鼓譜預覽與匯出規格.md | Todo |
| `GS-P2-010` | Phase 2 | 建立 API error response 格式 | P0 | M | GS-P2-001 | Level 1：API設計.md, Level 2：錯誤處理與使用者提示規格.md | Todo |
| `GS-P3-001` | Phase 3 | 建立 Redis / Celery 設定 | P0 | M | GS-P2-001 | Level 1：技術選型.md, Level 2：背景任務與Job狀態規格.md | Todo |
| `GS-P3-002` | Phase 3 | 建立 transcription job task | P0 | M | GS-P3-001, GS-P2-002 | Level 1：系統架構.md, Level 1：技術選型.md, Level 2：背景任務與Job狀態規格.md | Todo |
| `GS-P3-003` | Phase 3 | 建立 job status update service | P0 | M | GS-P3-002, GS-P2-007 | Level 1：系統架構.md, Level 1：技術選型.md, Level 2：背景任務與Job狀態規格.md | Todo |
| `GS-P3-004` | Phase 3 | 建立 pipeline stage orchestration | P0 | L | GS-P3-003 | Level 1：系統架構.md, Level 1：技術選型.md, Level 2：背景任務與Job狀態規格.md | Todo |
| `GS-P3-005` | Phase 3 | 建立 retry / timeout / failed handling | P0 | M | GS-P3-003, GS-P3-004, GS-P2-010 | Level 1：系統架構.md, Level 1：技術選型.md, Level 2：背景任務與Job狀態規格.md | Todo |
| `GS-P3-006` | Phase 3 | 建立 worker logging | P1 | S | GS-P3-002, GS-P3-004, GS-P2-005 | Level 2：背景任務與Job狀態規格.md, Level 2：檔案儲存與Artifact規格.md | Todo |
| `GS-P3-007` | Phase 3 | 建立 Queue enqueue interface 與 Upload API 實際派送整合 | P0 | M | GS-P2-006, GS-P3-001, GS-P3-002, GS-P2-010 | Level 2：音檔上傳功能規格.md, Level 2：背景任務與Job狀態規格.md | Todo |
| `GS-P4-001` | Phase 4 | 後段整合票：將 Phase 1 pipeline 封裝成 worker service | P0 | L | GS-P1-007, GS-P3-004, GS-P2-005, GS-P4-002, GS-P4-003, GS-P4-004, GS-P4-005, GS-P4-009, GS-P4-010, GS-P4-011, GS-P4-007 | Level 1：AI音訊處理流程.md, Level 1：系統架構.md, Level 2：AI_Pipeline執行規格.md | Todo |
| `GS-P4-002` | Phase 4 | 建立 SourceSeparator interface | P0 | S | GS-P1-007 | Level 1：AI音訊處理流程.md, Level 1：系統架構.md, Level 2：AI_Pipeline執行規格.md | Todo |
| `GS-P4-003` | Phase 4 | 建立 DemucsSourceSeparator adapter | P0 | L | GS-P4-002, GS-P1-003 | Level 1：AI音訊處理流程.md, Level 1：系統架構.md, Level 2：AI_Pipeline執行規格.md | Todo |
| `GS-P4-004` | Phase 4 | 建立 DrumTranscriber interface | P0 | S | GS-P1-007 | Level 1：AI音訊處理流程.md, Level 1：系統架構.md, Level 2：AI_Pipeline執行規格.md | Todo |
| `GS-P4-005` | Phase 4 | 建立 AdtofDrumTranscriber adapter | P0 | L | GS-P4-004, GS-P1-004 | Level 1：AI音訊處理流程.md, Level 1：系統架構.md, Level 2：AI_Pipeline執行規格.md | Todo |
| `GS-P4-006` | Phase 4 | 建立 artifact metadata 寫入流程 | P0 | L | GS-P4-001, GS-P4-003, GS-P4-005, GS-P4-009, GS-P4-010, GS-P4-011, GS-P2-005 | Level 1：AI音訊處理流程.md, Level 1：系統架構.md, Level 2：AI_Pipeline執行規格.md | Todo |
| `GS-P4-007` | Phase 4 | 建立 pipeline error mapping | P0 | M | GS-P3-005, GS-P4-009, GS-P4-003, GS-P4-005, GS-P4-010, GS-P4-011 | Level 1：AI音訊處理流程.md, Level 1：系統架構.md, Level 2：AI_Pipeline執行規格.md | Todo |
| `GS-P4-008` | Phase 4 | 建立模型版本與 pipeline version 記錄 | P1 | S | GS-P4-003, GS-P4-005, GS-P4-006 | Level 1：AI音訊處理流程.md, Level 1：系統架構.md, Level 2：AI_Pipeline執行規格.md | Todo |
| `GS-P4-009` | Phase 4 | 建立 AudioPreprocessor interface / ffmpeg adapter 正式化 | P0 | M | GS-P1-002, GS-P2-005 | Level 2：ffmpeg音訊標準化規格.md, Level 2：AI_Pipeline執行規格.md | Todo |
| `GS-P4-010` | Phase 4 | 建立 MidiPostProcessor service 正式化 | P0 | M | GS-P1-005, GS-P2-005 | Level 2：MIDI後處理與量化規格.md, Level 2：AI_Pipeline執行規格.md | Todo |
| `GS-P4-011` | Phase 4 | 建立 NotationGenerator / PdfExporter interface 與 worker integration | P0 | L | GS-P1-006, GS-P4-010, GS-P2-009 | Level 2：鼓譜預覽與匯出規格.md, Level 2：AI_Pipeline執行規格.md | Todo |
| `GS-P5-001` | Phase 5 | 建立前端專案骨架 | P0 | M | 無 | Level 1：技術選型.md, Level 2：前端頁面與互動規格.md | Todo |
| `GS-P5-002` | Phase 5 | 建立上傳頁 | P0 | M | GS-P5-001 | Level 1：產品需求文件.md, Level 1：API設計.md, Level 2：前端頁面與互動規格.md | Todo |
| `GS-P5-003` | Phase 5 | 建立 API client | P0 | M | GS-P5-001, GS-P2-006, GS-P2-007, GS-P2-008 | Level 1：產品需求文件.md, Level 1：API設計.md, Level 2：前端頁面與互動規格.md | Todo |
| `GS-P5-004` | Phase 5 | 建立 job result page | P0 | M | GS-P5-001, GS-P5-003 | Level 1：產品需求文件.md, Level 1：API設計.md, Level 2：前端頁面與互動規格.md | Todo |
| `GS-P5-005` | Phase 5 | 建立 job status polling | P0 | M | GS-P5-003, GS-P5-004, GS-P2-007, GS-P2-008 | Level 1：產品需求文件.md, Level 1：API設計.md, Level 2：前端頁面與互動規格.md | Todo |
| `GS-P5-006` | Phase 5 | 建立錯誤狀態 UI | P0 | S | GS-P5-003, GS-P2-010 | Level 1：產品需求文件.md, Level 1：API設計.md, Level 2：前端頁面與互動規格.md | Todo |
| `GS-P5-007` | Phase 5 | 建立下載按鈕 | P0 | S | GS-P5-005, GS-P2-009 | Level 1：產品需求文件.md, Level 1：API設計.md, Level 2：前端頁面與互動規格.md | Todo |
| `GS-P5-008` | Phase 5 | 建立使用者準確度提示文案 | P1 | S | GS-P5-002, GS-P5-003, GS-P5-005, GS-P2-008 | Level 1：產品需求文件.md, Level 2：前端頁面與互動規格.md | Todo |
| `GS-P5-009` | Phase 5 | 串接上傳表單、Upload API 與成功導向 | P0 | M | GS-P5-002, GS-P5-003, GS-P5-004, GS-P5-006, GS-P2-006 | Level 2：前端頁面與互動規格.md, Level 2：音檔上傳功能規格.md | Todo |
| `GS-P6-001` | Phase 6 | 整合 OpenSheetMusicDisplay | P0 | M | GS-P5-004, GS-P5-005 | Level 1：產品需求文件.md, Level 1：技術選型.md, Level 2：鼓譜預覽與匯出規格.md | Todo |
| `GS-P6-002` | Phase 6 | 建立 MusicXML preview component | P0 | M | GS-P6-001, GS-P5-005, GS-P2-009, GS-P4-006, GS-P4-011 | Level 1：產品需求文件.md, Level 1：技術選型.md, Level 2：鼓譜預覽與匯出規格.md | Todo |
| `GS-P6-003` | Phase 6 | 建立 PDF export 檢查流程 | P0 | M | GS-P4-006, GS-P2-008, GS-P2-009 | Level 1：產品需求文件.md, Level 1：技術選型.md, Level 2：鼓譜預覽與匯出規格.md | Todo |
| `GS-P6-004` | Phase 6 | 建立 MusicXML / PDF 失敗 fallback UI | P0 | S | GS-P6-002, GS-P6-003, GS-P5-007 | Level 1：產品需求文件.md, Level 1：技術選型.md, Level 2：鼓譜預覽與匯出規格.md | Todo |
| `GS-P6-005` | Phase 6 | 驗證 MusicXML 可被 MuseScore 開啟 | P1 | S | GS-P1-006, GS-P6-002, GS-P4-006 | Level 1：產品需求文件.md, Level 1：技術選型.md, Level 2：鼓譜預覽與匯出規格.md | Todo |
| `GS-P6-006` | Phase 6 | 驗證 PDF 可正常下載與打開 | P1 | S | GS-P6-003, GS-P2-009, GS-P4-006 | Level 1：產品需求文件.md, Level 1：技術選型.md, Level 2：鼓譜預覽與匯出規格.md | Todo |
| `GS-P7-001` | Phase 7 | 建立 unit tests | P0 | M | GS-P2-010, GS-P4-007, GS-P1-005 | Level 1：測試策略.md, Level 2：MVP開發任務拆分.md | Todo |
| `GS-P7-002` | Phase 7 | 建立 integration tests | P0 | L | GS-P2-006, GS-P2-009, GS-P3-004 | Level 1：測試策略.md, Level 2：MVP開發任務拆分.md | Todo |
| `GS-P7-003` | Phase 7 | 建立 pipeline fixture tests | P0 | L | GS-P1-007, GS-P4-001 | Level 1：測試策略.md, Level 2：MVP開發任務拆分.md, Level 2：音檔上傳功能規格.md | Todo |
| `GS-P7-004` | Phase 7 | 建立 API contract tests | P1 | M | GS-P2-010, GS-P5-003 | Level 1：測試策略.md, Level 2：MVP開發任務拆分.md | Todo |
| `GS-P7-005` | Phase 7 | 建立人工準確度評估流程 | P1 | M | GS-P1-008, GS-P7-003 | Level 1：測試策略.md, Level 2：MVP開發任務拆分.md, Level 2：音檔上傳功能規格.md | Todo |
| `GS-P7-006` | Phase 7 | 建立 MVP 驗收 checklist | P1 | S | GS-P7-001, GS-P7-002, GS-P7-003 | Level 1：測試策略.md, Level 2：MVP開發任務拆分.md, Level 2：音檔上傳功能規格.md | Todo |
| `GS-P7-007` | Phase 7 | 建立 regression test 流程 | P1 | M | GS-P7-003, GS-P4-008 | Level 1：測試策略.md, Level 2：MVP開發任務拆分.md, Level 2：音檔上傳功能規格.md | Todo |
| `GS-P7-008` | Phase 7 | 建立瀏覽器端 E2E smoke test | P1 | M | GS-P5-009, GS-P5-005, GS-P5-007, GS-P6-002, GS-P6-004 | Level 1：測試策略.md, Level 2：前端頁面與互動規格.md | Todo |
| `GS-P8-001` | Phase 8 | 建立 Dockerfile | P0 | L | GS-P2-001, GS-P3-001, GS-P5-001, GS-P4-003, GS-P4-005 | Level 1：技術選型.md, Level 1：專案目錄結構.md, Level 1：開發計畫.md | Todo |
| `GS-P8-002` | Phase 8 | 建立 docker-compose.yml | P0 | M | GS-P8-001, GS-P8-003, GS-P8-004, GS-P8-005 | Level 1：技術選型.md, Level 1：專案目錄結構.md, Level 1：開發計畫.md | Todo |
| `GS-P8-003` | Phase 8 | 建立 backend / worker / frontend env config | P0 | S | GS-P2-001, GS-P3-001, GS-P5-001 | Level 1：技術選型.md, Level 1：專案目錄結構.md, Level 1：開發計畫.md | Todo |
| `GS-P8-004` | Phase 8 | 建立 local storage volume | P0 | S | GS-P2-005, GS-P8-003 | Level 1：技術選型.md, Level 1：專案目錄結構.md, Level 1：開發計畫.md | Todo |
| `GS-P8-005` | Phase 8 | 建立 Redis / Postgres service | P0 | S | GS-P8-003 | Level 1：技術選型.md, Level 1：專案目錄結構.md, Level 1：開發計畫.md | Todo |
| `GS-P8-006` | Phase 8 | 建立 GPU worker 部署注意事項 | P1 | M | GS-P4-003, GS-P4-005, GS-P8-001 | Level 1：技術選型.md, Level 1：專案目錄結構.md, Level 1：開發計畫.md | Todo |
| `GS-P8-007` | Phase 8 | 建立 staging deployment checklist | P1 | S | GS-P8-002, GS-P7-006 | Level 1：技術選型.md, Level 1：專案目錄結構.md, Level 1：開發計畫.md | Todo |
