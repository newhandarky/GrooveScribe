# Tests

測試目錄依 Level 3 規劃拆分：

- `unit/`：純邏輯單元測試
- `integration/`：API、database、queue、storage 整合測試
- `pipeline/`：pipeline fast / slow fixture tests
- `e2e/`：瀏覽器端 smoke tests
- `manual_eval/`：人工準確度評估表與結果

## Fixture 與人工評估

- `pipeline/fixtures/`：Phase 1 pipeline smoke test 使用的合成音檔與 manifest。
- `manual_eval/manual_eval_template.csv`：人工準確度與可用性評估表。

重新產生合成 fixture：

```bash
PYTHONPATH=. python scripts/generate_test_fixtures.py
```

使用 fixture 跑 local runner smoke：

```bash
PYTHONPATH=. python scripts/run_local_pipeline.py --input tests/pipeline/fixtures/audio/synthetic_clean_drum_pattern.wav --output-dir /tmp/groovescribe-fixture-run --mock-ai
```
