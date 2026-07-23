# Generic Hi-hat 下一階段架構與執行計畫

> 本文件是 generic hi-hat migration 完成後的後續工程主線。它優先於任何 articulation 功能或 ADTOF production 整合工作；既有 V1 歷史文件如與本文件衝突，以本文件的產品邊界為準。

## 1. 產品決策與不變量

GrooveScribe 現階段只提供以下鼓件事件：

- `kick`
- `snare`
- `hi_hat`
- `tom`
- `cymbal`

`hi_hat` 的產品語意是「偵測到 hi-hat 擊發及其時間位置」。generic hi-hat 的 MIDI 輸出固定為 General MIDI note 42，但這是穩定輸出編碼，不代表任何 articulation 推論。

目前產品不得輸出、推論、UI 顯示或文件宣稱 reliable 的 closed、open 或 pedal hi-hat 結果。既有 artifacts 中的 legacy hat label 僅可在讀取邊界正規化為 `hi_hat`；新 artifacts、公開 API、review packet、timeline 與 UI 都必須使用 canonical `hi_hat`。

ADTOF 是 offline evaluation 與 legacy artifact read 的參考 runtime。在其 CC BY-NC-SA 4.0 商業適用性未確認前，不是正式產品 runtime，也不是公開產品設定選項。

## 2. 現行架構與已知 P0

目前 local-first 產品的主要資料流如下：

```text
React UI
  → FastAPI /transcriptions
  → UploadService + local job queue
  → PipelineServiceRunner
  → scripts/run_local_pipeline.py
  → LocalPipelineRunner
  → preprocessing / source separation / drum transcription
  → MIDI postprocess / MusicXML / performance gate
  → local artifacts + SQLite metadata
  → ResultService / ReviewTimelineService
  → Result API / browser playback / downloads
```

generic hi-hat 已在 MIDI mapping、postprocess、MusicXML、chart、performance MIDI、quality summary、API serialization、review timeline 與 UI 的新輸出路徑中使用 `hi_hat`。performance MIDI 會輸出 note 42，且 generic baseline 不附 articulation。

### P0：產品 mode 與 backend 選擇尚未收斂

目前 CLI 的 `--transcription-backend` 預設為 `spectral_onset_v1`；但公開 `true_ai` mode 仍會在 backend orchestration 加入 ADTOF candidate thresholds 與 preset。`PipelineServiceRunner` 沒有在該路徑明確傳入 `--transcription-backend adtof`，而 `LocalPipelineRunner` 會拒絕「candidate strategies 搭配非 ADTOF backend」的組合。

這是 orchestration contract 衝突，必須在下一批先修正。它不是 closed/open 辨識問題，也不應以調整 articulation threshold 處理。

## 3. 目標產品 runtime contract

新 job 的公開 mode 收斂為：

| Mode | 用途 | transcription backend | ADTOF 依賴 |
|---|---|---|---|
| `demo_mock` | UI、流程與快速 smoke | mock | 無 |
| `generic_baseline` | 正式 local-first 產品 baseline | `spectral_onset_v1` | 無 |

既有 `true_ai` 與 ADTOF config 僅保留為 legacy job read compatibility 或 offline benchmark 使用。新的 upload/retry public API 不得建立需要 ADTOF checkpoint、threshold、preset 或 candidate analysis 的 job。

`generic_baseline` 的 backend command 必須明確傳入 `--transcription-backend spectral_onset_v1`，不得依賴 CLI 預設值；也不得加入 candidate thresholds、ADTOF preset、ADTOF checkpoint 或 ADTOF command template。

Runtime preflight 必須分開回報：

- `generic_baseline_ready`：正式產品必要條件。
- `offline_adtof_available`：僅供 offline evaluation 的選用狀態。

## 4. 實作批次

### Batch 1：Pipeline mode 與公開 API 收斂（P0）

**涉及模組**

- `backend/app/services/pipeline_config.py`
- `backend/app/services/pipeline_service.py`
- upload、retry、runtime diagnostics 與 frontend typed API contract
- `scripts/run_local_pipeline.py`

**工作內容**

- 新增並選定 `generic_baseline` 作為新 job 的正式產品 mode。
- `PipelineServiceRunner` 依 mode 明確建構 transcription backend command。
- 新的 upload/retry API 不再接受 ADTOF preset 作為產品設定；資料庫欄位與舊 job 僅維持讀取相容。
- `demo_mock` 保持可用；legacy job 可安全讀取，retry 的轉換規則必須明確且可測試。
- Runtime preflight 將產品 baseline readiness 與 offline ADTOF availability 分離。

**不可改變的行為**

- SQLite、local filesystem artifacts 與 local job queue 仍是 V1 預設。
- 不增加模型、不下載新的 runtime、不把 ADTOF 接入正式產品路徑。
- API 與 UI 不暴露 raw command、checkpoint path、token 或 runtime secret。

**驗收與測試**

- command-builder test 驗證 `generic_baseline` 明確傳入 spectral backend，且沒有 ADTOF/candidate flags。
- subprocess integration test 驗證 API job 能完整走到 pipeline payload 或得到固定 error contract。
- API integration test 驗證新 job config 不包含公開 ADTOF preset。
- legacy job read/retry regression test 驗證相容策略。

### Batch 2：Canonical drum taxonomy contract 收斂

**涉及模組**

- MIDI mapping 與 postprocess。
- ResultService、ReviewTimelineService、review packet。
- benchmark metrics 與 frontend type contract。

**工作內容**

- 將 canonical drum classes、legacy hat aliases、generic hi-hat MIDI note 與 taxonomy ID 集中為輕量且不依賴 runtime 的 contract。
- 為 artifacts 與 public quality payload 增加明確 taxonomy，例如 `generic_hihat_v1`。
- 對 legacy input 做正規化；unknown drum 不得 fallback 成 snare，必須被拒絕、丟棄或以固定 reason code 記錄。
- frontend 保留相同 canonical type，並用 API contract test 防止 Python/TypeScript schema 漂移。

**不可改變的行為**

- kick、snare、tom、cymbal 的既有映射與輸出不變。
- generic hi-hat 仍固定輸出 note 42，且不輸出 articulation。

**驗收與測試**

- legacy count 合併後總數與 coverage 保持正確。
- 新 artifact、API response、review packet、timeline 與 UI fixture 不含 legacy hat label。
- MIDI 42/44/46 經 postprocess、notation、chart 與 performance MIDI 後皆為 `hi_hat`／note 42，且不得變成 snare。

### Batch 3：真實 API-to-artifact E2E fixture

**涉及模組**

- local queue、PipelineServiceRunner、artifact storage、ResultService。
- frontend result contract 與 browser smoke。

**工作內容**

- 使用可提交的 generated fixture，跑 upload → local queue → subprocess → artifacts → result API 的完整流程。
- 對產品 baseline 加入非 mock 的 subprocess integration coverage；browser mock smoke 繼續保留，但不可作為唯一產品 pipeline 證據。

**驗收與測試**

- processed MIDI 與 performance MIDI 可解析且有事件。
- generic hi-hat event 可計數，performance MIDI 中只使用 note 42。
- MusicXML 顯示 `Hi-hat`，chart／review timeline／API 僅輸出 `hi_hat`。
- job 失敗時回傳固定 stage 與安全 error code，不暴露本機路徑或 raw subprocess output。

### Batch 4：Repo 外 generic-hat benchmark 與一次 holdout

**涉及模組**

- `ai_pipeline/benchmark/metrics.py`。
- performance benchmark、provenance、release evidence scripts。

**工作內容**

- 僅評估 kick、snare、generic hi-hat；matching window 固定 50ms。
- 將 ground-truth MIDI 的 42/44/46 合併為 generic hi-hat。
- 使用 repo 外、已授權、具 checksum 與 source-id 的 development/holdout manifest。
- ADTOF 若參與，只能是 offline comparator；不得影響正式產品 backend 選擇。

**驗收與測試**

- 報告逐段與平均 precision、recall、F1、macro F1、FP/FN、event count 與 runtime。
- development report 凍結為 baseline；後續採 non-regression gate，不用同一 development set 反推或放寬絕對門檻。
- holdout 只在 development 規則通過後跑一次；資料、MIDI、音檔、checkpoint 與 report 都留在 repo 外。

### Batch 5：generic baseline target-runtime release sign-off

**涉及模組**

- runtime preflight、release gate、release evidence、RC handoff。

**工作內容**

- 保留 deterministic CI gate：unit/integration tests、generated fixture、API contract、frontend tests、build、browser mock smoke、artifact hygiene、redaction 與 diff check。
- 新增 target-runtime sign-off：generic baseline runtime readiness、real subprocess smoke、MIDI/MusicXML parse、repo 外 benchmark 與 live-backend browser smoke。
- ADTOF unavailable 不得阻塞 generic baseline sign-off。

**驗收與測試**

- release evidence 清楚區分 deterministic CI、generic baseline target-runtime 與 offline ADTOF 狀態。
- 產物、storage、DB、benchmark outputs、reports 與 browser artifacts 不得進 git。

### Batch 6：UI、runtime guide 與 release 文件收斂

**涉及模組**

- upload/retry UI、result review、runtime guide、release checklist、工程文件索引。

**工作內容**

- 對使用者統一使用「Hi-hat」與「generic hi-hat baseline」說明。
- 移除公開 UI 對 ADTOF preset 與 articulation 的依賴。
- 說明輸出是可檢查、可下載、可人工修正的鼓譜草稿；MIDI 42 不代表 articulation。
- 將舊有 ADTOF-first／6-class／manual-eval 描述標記為 historical 或 offline-only，避免與 automation-only gate 衝突。

**驗收與測試**

- UI regression test 驗證任何 legacy input 都顯示 `Hi-hat`。
- 使用者文件不宣稱 closed/open/pedal 支援。
- release runbook 的正式 runtime 不要求 ADTOF。

## 5. 非目標

- 不新增、訓練或調整鼓組辨識模型。
- 不調整 closed/open/pedal threshold，也不將其納入產品驗收。
- 不將 ADTOF 接入正式 production runtime。
- 不重構 Redis、Celery、PostgreSQL、cloud 或 SaaS 架構。
- 不新增線上修譜、articulation UI 或多檔批次處理。

## 6. 已完成 migration 基線

generic hi-hat migration 在本分支已完成以下驗證：

- Pipeline tests：90 passed。
- Backend API tests：47 passed。
- Frontend tests：44 passed。
- Frontend production build：passed。
- `git diff --check`：passed。

後續批次必須維持此基線，並在每次修改 symbol 前執行 GitNexus impact analysis；若影響結果為 HIGH 或 CRITICAL，先向使用者回報 blast radius 與測試策略。

## 7. 建議的下一個最小工作項目

先完成 Batch 1：建立 `generic_baseline` 公開 pipeline mode，讓 backend 明確傳入 `spectral_onset_v1`，移除新 job 對 ADTOF preset 的依賴，並補上一個真正 subprocess command integration test。

完成這個批次後，generic hi-hat 才會從「資料模型與輸出已支援」提升為「產品入口能可靠啟動的正式 baseline」。
