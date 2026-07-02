# Phase 8：Local Startup、Packaging Boundary 與 Release 任務

> 本文件已依 local-first 完整 V1 方向重整。詳細 ticket 以 `V1_Ticket總表.md` 為準。

## Phase 目標

建立 V1 的本機啟動、app data 初始化、重置、備份與 release checklist。Staging deployment、Redis / Celery、PostgreSQL、S3 與 cloud hosting 都是 future optional，不是 V1 必要目標。

## V1 重點

- 一條本機啟動路徑。
- app data 目錄初始化。
- SQLite DB 與 artifacts 位置明確。
- runtime preflight 可在啟動流程中執行。
- Future desktop shell / server mode 邊界清楚。

## 主要任務

- `GS-V1-P8-001`：建立一條本機啟動命令。
- `GS-V1-P8-002`：建立 app data 初始化與重置流程。
- `GS-V1-P8-003`：建立 V1 release checklist。
- `GS-V1-P8-004`：文件化 future desktop shell 邊界。
- `GS-V1-P8-005`：文件化 future server mode 邊界。

## 驗收標準

- 工程師可依 README 在乾淨本機啟動 GrooveScribe。
- `localhost` UI 可完成一首短音檔端到端流程。
- app data、SQLite DB、artifacts、logs 的位置與清理方式明確。
- V1 release checklist 與 `docs/產品完整度標準.md` 對齊。

## Future Optional

- Tauri / Electron desktop shell。
- Docker Compose server mode。
- Redis / Celery worker mode。
- PostgreSQL server mode。
- S3-compatible storage。
- cloud sync / SaaS deployment。

## 參考文件

- `docs/開發計畫.md`
- `docs/技術選型.md`
- `docs/架構決策/ADR-001-介面型態與執行模式.md`
- `docs/產品完整度標準.md`
- `docs/03_工程實作任務/V1_Ticket總表.md`
