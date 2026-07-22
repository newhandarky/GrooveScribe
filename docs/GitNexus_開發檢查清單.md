# GrooveScribe GitNexus 開發檢查清單

GitNexus 是改碼前的導航與風險雷達；它不取代測試、code review 或資料品質 gate。

## 1. 開始任務前

- [ ] 確認 GitNexus 索引最新：

  ```bash
  npx gitnexus status
  ```

- [ ] 若索引不是最新，更新它：

  ```bash
  npx gitnexus analyze
  ```

- [ ] 先用概念找 execution flow，不急著直接改檔：

  ```bash
  npx gitnexus query "<功能、問題或領域>"
  ```

範例：

```bash
npx gitnexus query "candidate recommendation benchmark strategy"
npx gitnexus query "result API safe public summary"
npx gitnexus query "ADTOF threshold preset reference drums"
```

## 2. 理解目標程式前

- [ ] 對要處理的核心 symbol 看 360° context：

  ```bash
  npx gitnexus context <symbol>
  ```

- [ ] 確認直接 callers、下游 callees、參與的 execution flows，以及是否跨 pipeline、backend、frontend 或 benchmark。

## 3. 修改前的必要 gate

- [ ] 每次修改 function、class、method 前都跑：

  ```bash
  npx gitnexus impact <symbol> --direction upstream
  ```

- [ ] 回報 blast radius：
  - d=1：直接受影響的 callers。
  - d=2：間接受影響流程。
  - 風險等級：low、medium、high。

- [ ] 若是 high 或 critical：
  - 先告知風險。
  - 縮小修改範圍或拆分工作。
  - 先補 targeted tests 再改。

## 4. GrooveScribe 常用對照

| 工作 | 優先檢查的 symbol／概念 |
| --- | --- |
| 多候選轉譜 | `LocalPipelineRunner`、`evaluate_candidate_recommendation` |
| benchmark 與 holdout gate | `run_benchmark`、`_run_item`、`_evaluate_candidates` |
| reference-drums 歸因 | `run_reference_drums_controlled_benchmark` |
| API 公開安全摘要 | `ResultService`、`_candidate_analysis_summary` |
| 前端候選工作台 | `CandidateAnalysisPanel`、`ResultCard` |
| raw-model attribution | `run_raw_model_attribution` |

## 5. 實作期間

- [ ] 一次只做一項可歸因調整。
- [ ] 保持 scalar 候選與 preset 候選明確分開。
- [ ] 不讓 benchmark report 或 API 輸出路徑、storage key、command、stdout/stderr、Traceback。
- [ ] 新增或更新最貼近變更的單元／整合測試。
- [ ] 對 benchmark 規則特別確認 development 與 holdout 不會混用或繞過 gate。

## 6. 完成前

- [ ] 跑 targeted tests。
- [ ] 跑專案完整驗證。
- [ ] 檢查目前變更實際影響：

  ```bash
  npx gitnexus detect-changes
  ```

- [ ] 確認只有預期的 symbols／execution flows 受影響。
- [ ] 執行：

  ```bash
  git diff --check
  git status --short
  ```

- [ ] 清理不可提交輸出：`frontend/dist`、Playwright outputs、storage、DB、benchmark reports、音檔與 stems。

## 日常最小指令組合

```bash
npx gitnexus status
npx gitnexus query "<task>"
npx gitnexus context <symbol>
npx gitnexus impact <symbol> --direction upstream
# 修改與測試
npx gitnexus detect-changes
git diff --check
```
