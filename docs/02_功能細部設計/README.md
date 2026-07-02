# Level 2：功能細部設計 README

## 這一層文件的用途

`02_功能細部設計` 是 GrooveScribe 的 Level 2 規格層，承接上一層 Level 1 的產品需求、系統架構、資料模型、API 設計與 AI pipeline 規劃。

Level 1 回答「要做什麼、系統怎麼分層」；Level 2 回答「每個功能要怎麼實作、輸入輸出是什麼、狀態怎麼流、錯誤怎麼處理、如何驗收」。

這一層文件以 local-first 完整 V1 為主線。Redis / Celery、PostgreSQL、S3、cloud sync、desktop shell 都是 future optional，除非文件明確標示 server mode 或 future。

## 建議閱讀順序

1. `音檔上傳功能規格.md`
2. `背景任務與Job狀態規格.md`
3. `檔案儲存與Artifact規格.md`
4. `AI_Pipeline執行規格.md`
5. `ffmpeg音訊標準化規格.md`
6. `Demucs鼓軌分離規格.md`
7. `ADTOF鼓MIDI轉寫規格.md`
8. `MIDI後處理與量化規格.md`
9. `鼓譜預覽與匯出規格.md`
10. `錯誤處理與使用者提示規格.md`
11. `前端頁面與互動規格.md`
12. `V1開發任務拆分.md`

若要先做 runtime proof，從第 4 到第 9 份開始；若要先建 local-first 產品骨架，從第 1、2、3、10、11、12 份開始。

## 每份文件對應的開發模組

| 文件 | 主要模組 | 次要模組 |
|---|---|---|
| `音檔上傳功能規格.md` | backend upload API | frontend upload UI、storage、local job manager |
| `背景任務與Job狀態規格.md` | local job manager、backend job service | frontend polling、SQLite |
| `AI_Pipeline執行規格.md` | pipeline service | ai_pipeline、storage、SQLite |
| `ffmpeg音訊標準化規格.md` | ai_pipeline preprocessing | pipeline service、storage |
| `Demucs鼓軌分離規格.md` | ai_pipeline source separation adapter | pipeline service、storage |
| `ADTOF鼓MIDI轉寫規格.md` | ai_pipeline drum transcription adapter | pipeline service、storage |
| `MIDI後處理與量化規格.md` | ai_pipeline MIDI module | notation、pipeline service |
| `鼓譜預覽與匯出規格.md` | notation/export module | frontend preview、backend download API |
| `檔案儲存與Artifact規格.md` | local storage adapter | backend、pipeline service、ai_pipeline |
| `錯誤處理與使用者提示規格.md` | backend error response、pipeline error mapping | frontend UI |
| `前端頁面與互動規格.md` | frontend local web app | backend API |
| `V1開發任務拆分.md` | project execution | all modules |

## 如何從這些文件拆成工程 ticket

建議每個 ticket 至少包含：

- 來源文件與章節，例如 `音檔上傳功能規格.md / 後端行為`。
- 變更範圍，例如 `backend/app/api/transcriptions` 或 `ai_pipeline/preprocessing`。
- 明確輸入與輸出。
- API 或資料模型影響。
- Storage / artifact 影響。
- 錯誤情境。
- 驗收標準。
- 測試案例。

建議拆票方式：

```text
Epic 1：Local runtime baseline
Epic 2：SQLite、local storage 與 Job 建立
Epic 3：Local job manager、狀態流轉與錯誤處理
Epic 4：Production pipeline service
Epic 5：Local web upload、status、preview 與 download
Epic 6：MusicXML/PDF、artifact/log UX
Epic 7：測試、人工評估、browser smoke 與 V1 驗收
Epic 8：本機啟動、app data、release checklist
```

拆 ticket 時應優先讓每個 ticket 可獨立驗收。例如先用 mock adapter 跑通 job manager 與 API，再接真實 Demucs / ADTOF-pytorch；先產生 MusicXML，再處理 PDF；先完成 local storage adapter，再規劃 future S3-compatible storage。
