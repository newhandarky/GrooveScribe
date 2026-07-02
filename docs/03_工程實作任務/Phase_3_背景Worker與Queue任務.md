# Phase 3：Local Job Manager 任務

> 本文件已依 local-first 完整 V1 方向重整。詳細 ticket 以 `V1_Ticket總表.md` 為準。

## Phase 目標

建立本機 job manager，讓長時間 pipeline 不阻塞 API request。V1 不以 Redis / Celery 作為預設 queue；它們只保留為 future server mode。

## V1 重點

- 預設 single-process / in-process local queue。
- 預設 pipeline concurrency = 1。
- job 狀態寫入 SQLite。
- service restart 後處理 stale / interrupted job。
- Job manager interface 保留未來替換 Redis / Celery 的可能，但 V1 不要求啟動 Redis broker。

## 主要任務

- `GS-V1-P3-001`：建立本機 Job Manager interface。
- `GS-V1-P3-002`：實作本機 single-process job queue。
- `GS-V1-P3-003`：實作 job lifecycle 狀態轉移。
- `GS-V1-P3-004`：實作 stale / interrupted job recovery。
- `GS-V1-P3-005`：保留 Redis / Celery adapter 邊界但移出 V1 預設。

## 驗收標準

- Upload API 可把 job 交給 local job manager。
- job 可從 queued 進入 processing，再進入 completed 或 failed。
- failed job 有 error code、stage、user-facing message。
- restart 後 stale processing job 不會永久卡住。

## 參考文件

- `docs/系統架構.md`
- `docs/技術選型.md`
- `docs/產品完整度標準.md`
- `docs/03_工程實作任務/V1_Ticket總表.md`
