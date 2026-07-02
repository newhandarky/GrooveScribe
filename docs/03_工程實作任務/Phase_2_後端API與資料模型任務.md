# Phase 2：Local Data、Storage 與 API Foundation 任務

> 本文件已依 local-first 完整 V1 方向重整。詳細 ticket 以 `V1_Ticket總表.md` 為準。

## Phase 目標

建立 V1 的本機資料、storage 與 API 基礎。V1 預設 SQLite、local filesystem artifacts 與本機 API，不以 PostgreSQL 或 server deployment 作為第一版必要條件。

## V1 重點

- SQLite 是 V1 預設 database。
- Local filesystem 是 V1 預設 artifact storage。
- API 是 localhost app 的內部邊界，支援 upload、status、result、download、runtime diagnostics。
- Future server mode 可以保留 PostgreSQL / S3，但不得阻塞 V1。

## 主要任務

- `GS-V1-P2-001`：將 V1 預設 database 定為 SQLite。
- `GS-V1-P2-002`：建立 SQLite migration / upgrade 流程。
- `GS-V1-P2-003`：定義 app data 目錄與 local DB / artifacts 位置。
- `GS-V1-P2-004`：強化 LocalStorageAdapter artifact contract。
- `GS-V1-P2-005`：建立 artifacts 清理、備份與重置規格。

## 驗收標準

- SQLite 可保存 AudioFile、TranscriptionJob、DrumTrack、ExportFile。
- LocalStorageAdapter 可保存、讀取與 stream artifacts。
- API 不暴露任意本機路徑。
- app data 目錄、DB、artifacts、logs 有清楚位置與重置策略。

## 參考文件

- `docs/API設計.md`
- `docs/資料模型設計.md`
- `docs/02_功能細部設計/檔案儲存與Artifact規格.md`
- `docs/產品完整度標準.md`
- `docs/03_工程實作任務/V1_Ticket總表.md`
