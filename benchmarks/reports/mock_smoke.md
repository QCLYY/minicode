# MiniCode Smoke Evaluation Report: mock_smoke

- Generated at: 2026-06-29T14:09:57.843478+00:00
- Provider: mock
- Model/config: mock-scripted-llm
- Formal real-model evaluation executed: False
- Total runs: 15
- Success: 15/15 (100.00%)
- Abnormal terminations: 0 (0.00%)
- Average tool calls: 1.8
- Average iterations: 2.8
- Average duration seconds: 0.575
- Token usage: unsupported by current Agent result schema

## Per-Case Results

| Case | Runs | Successes | Success Rate |
| --- | ---: | ---: | ---: |
| code_understanding | 3 | 3 | 100.00% |
| code_location | 3 | 3 | 100.00% |
| single_file_edit | 3 | 3 | 100.00% |
| bug_fix | 3 | 3 | 100.00% |
| intent_constraint | 3 | 3 | 100.00% |

## Notes

- The default mock provider validates the Harness, graph, and tool plumbing; it is not a real-model capability score.
- No real API keys, model responses, or temporary workspaces are stored.
- Real-model formal evaluation should be run with `--provider configured` after the desired `.env` provider is configured.
