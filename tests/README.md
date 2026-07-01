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
- `manual_eval/2026-06-30_true_ai_fixture_eval.csv`：目前真 Demucs + ADTOF generated fixture smoke 的人工評估結果；記錄為低品質，不代表轉譜準確度達標。

重新產生合成 fixture：

```bash
export PYTHON="$(pwd)/.venv-ai/bin/python"
PYTHONPATH=. "$PYTHON" scripts/generate_test_fixtures.py
```

使用 fixture 跑 local runner smoke：

```bash
export PYTHON="$(pwd)/.venv-ai/bin/python"
PYTHONPATH=. "$PYTHON" scripts/run_local_pipeline.py --input tests/pipeline/fixtures/audio/synthetic_clean_drum_pattern.wav --output-dir /tmp/groovescribe-fixture-run --mock-ai
```

真 AI fixture smoke 需先通過 runtime gate：

```bash
export PYTHON="$(pwd)/.venv-ai/bin/python"
export GROOVESCRIBE_ADTOF_COMMAND_TEMPLATE="$(pwd)/.venv-ai/bin/adtof --audio {input} --out {output} --device {device} --threshold {threshold}"
export GROOVESCRIBE_ADTOF_VERIFY_INPUT="/tmp/groovescribe-stems/drums.wav"
PYTHONPATH=. "$PYTHON" scripts/check_ai_runtime.py
PYTHONPATH=. "$PYTHON" scripts/run_local_pipeline.py --input tests/pipeline/fixtures/audio/synthetic_clean_drum_pattern.wav --output-dir /tmp/groovescribe-true-ai-run --demucs-device cpu --adtof-command-template "$GROOVESCRIBE_ADTOF_COMMAND_TEMPLATE" --adtof-device cpu --adtof-threshold 0.5
```

若 Demucs 或 ADTOF runtime 尚未 ready，保留 `manual_eval/manual_eval_template.csv`，不要填入假結果。
