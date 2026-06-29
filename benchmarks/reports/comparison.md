# Baseline Comparison

Actual Harness baseline-vs-develop evaluation was not executed because the `baseline` tag predates the new `benchmarks/smoke_eval.py` Harness and does not expose the same evaluation entry point. No fake `baseline.json` or `improved.json` files were created.

Regression data from the verified development work is available:

| Checkpoint | Result |
| --- | --- |
| Before reliability fixes | 320/323 tests passed |
| After reliability fixes | 336/336 tests passed |

Use the new Harness for future comparable runs by executing the same command and model configuration on both revisions.
