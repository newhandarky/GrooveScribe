# Phase 1：Local Runtime Baseline 任務

> 本文件已依 local-first 完整 V1 方向重整。詳細 ticket 以 `V1_Ticket總表.md` 為準。

## Phase 目標

建立可重現的本機 AI runtime baseline，讓 ffmpeg、Demucs、ADTOF-pytorch、MIDI post-processing、MusicXML 與 PDF export 都能在本機被檢查、診斷與驗證。

## V1 重點

- 本階段不是只證明 pipeline 可跑通，而是建立可重現 runtime 與 fixture 評估基礎。
- 保留 mock pipeline，用於驗證 orchestration、artifact contract 與 UI flow。
- 保留 true AI smoke，用於驗證 Demucs / ADTOF / notation 的實際輸出。
- 授權真實鼓聲 fixture、manual eval criteria、pipeline version 記錄是 V1 品質門檻的一部分。

## 主要任務

- `GS-V1-P1-001`：整理 local-first runtime baseline。
- `GS-V1-P1-002`：建立 runtime preflight check UX contract。
- `GS-V1-P1-003`：固定 generated fixtures 與授權真實鼓聲 fixture 流程。
- `GS-V1-P1-004`：補齊 true AI smoke 重現文件與限制。

## 驗收標準

- `scripts/check_ai_runtime.py` 能清楚回報本機 runtime 狀態。
- mock local pipeline 可在 fixture 上穩定跑完。
- true AI local pipeline 的前置條件、命令、輸出與限制有文件可重現。
- MusicXML 與 PDF export 有成功、warning 或 failed 的明確狀態。

## 參考文件

- `ai_pipeline/RUNTIME.md`
- `docs/AI音訊處理流程.md`
- `docs/測試策略.md`
- `docs/產品完整度標準.md`
- `docs/03_工程實作任務/V1_Ticket總表.md`
