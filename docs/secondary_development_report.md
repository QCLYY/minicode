# MiniCode Reliability And Evaluation Report

Date: 2026-06-29

## Stable Baseline

- Stable tag before this polish pass: `v1.0.0`.
- Verified baseline: 336 passed, 0 failed, 0 errors.
- Earlier reliability starting point: 320/323 passed, 3 failed, 0 errors.

## Reliability Fixes Completed Before v1.0.0

### Chinese Direct-Answer Detection

Root cause:

- `memory/project.py` contained corrupted Chinese intent keyword literals.
- `is_direct_answer_query()` called `re.search()` with reversed arguments.
- Coding/action keywords were too broad for read-only Chinese requests containing negated actions.

Fix:

- Added valid UTF-8 Chinese and English intent patterns.
- Added positive execution-intent detection that strips negated actions before matching.
- Kept execution tasks such as modify, run, create, fix, install, commit, and delete classified as non-direct-answer.
- Kept read-only explanation, cause analysis, and general knowledge questions classified as direct-answer.

### ProjectMemory Search Fallback

Root cause:

- `ProjectMemory.search()` returned `[]` whenever `mini_vector_db` / `EmbeddingClient` was missing, embedding generation failed, vector search returned no rows, or vector search raised an exception.
- The JSONL `TurnStore` fallback persisted records but was not used for keyword search.

Fix:

- Preserved the original vector-search path as the first choice.
- Added local JSONL fallback search using only the current `ProjectMemory` instance's `TurnStore.load_all()`.
- Added lightweight scoring over `user_task`, `final_answer`, `files_changed`, and `tools_used`.
- Scoring includes phrase matches, word matches, file/path matches, and Chinese character-fragment matches.
- Fallback returns no unmatched records, respects `k`, and sorts by relevance descending.

### Intent Auditor Blocked Path

Root cause:

- In agent mode, a blocked thought/tool path could fall through to a mock or fallback `Done.` response.
- The state did not clearly distinguish normal completion from an Intent Auditor block.

Fix:

- Added `auditor_blocked`, `finish_reason`, and `auditor_blocked_answer` state fields.
- Preserved the normal allowed-tool path.
- Made `finish_node` prefer a meaningful recovery answer after a block, and fall back to a clear block explanation instead of `Done.`.
- Marked blocked completions with `finish_reason="auditor_blocked"` and memory success `False`.

## v1.1.0 Polish Scope

### Project Positioning

Documentation now describes MiniCode as a self-designed terminal Coding Agent with independently implemented core architecture and feature development. Legacy wording about external project lineage was removed.

### CLI Configuration Forwarding

Root cause:

- Non-raw single-task mode created a `ClaudeCodeMini` instance with user parameters, but did not use it.
- The actual non-raw execution path created `AgentCLI` without forwarding `max_iters`, `max_retries`, or `context_max_tokens`.
- `--no-memory` did not consistently share the same config-building path as raw mode.

Fix:

- Added one shared `_build_agent_config()` in `main.py`.
- Raw and non-raw single-task paths now use the same config source.
- `AgentCLI` now accepts and forwards `max_iterations`, `max_retries_per_step`, and `context_max_tokens`.
- `--no-memory` takes priority over `MEMORY_ENABLED=true`.
- Mode switching inside `AgentCLI` preserves the same runtime limits.

Added tests:

- Non-raw mode forwards `max_iterations`.
- Non-raw mode forwards `max_retries_per_step`.
- Non-raw mode forwards `context_max_tokens`.
- Raw and non-raw modes use the same config builder.
- `--no-memory` overrides enabled memory settings.
- User-specified workspace and mode reach `AgentCLI` / `ClaudeCodeMini`.

### Shell Risk Controls

Added lightweight Shell command risk classification:

- `low`: read-only commands such as `dir`, `ls`, `pwd`, `type`, `cat`, `pytest`, `python -m py_compile`, `git status`, and `git diff`.
- `medium`: commands that may modify workspace or dependency state, such as `mkdir`, `copy`, `move`, `git add`, `pip install`, and `npm install`.
- `high`: dangerous or irreversible commands such as `rm -rf`, `rmdir /s`, `del /s`, `format`, `mkfs`, `diskpart`, `shutdown`, `reboot`, `git reset --hard`, `git clean -fd`, `git push --force`, deletion outside the workspace, and downloaded-script execution.

High-risk commands are blocked before execution. Allowed results include `risk_level`, `allowed`, and `blocked_reason` metadata. This is not a complete system sandbox.

Added tests:

- Read-only commands remain allowed.
- `python -m py_compile` remains allowed.
- Medium-risk commands execute but are marked.
- `rm -rf`, `rmdir /s`, `git reset --hard`, and `git push --force` are blocked.
- Case changes, extra spaces, and `cmd` / `powershell` wrappers do not bypass obvious high-risk checks.

## v1.1.0 Verification

- Targeted CLI/Shell tests: 22 passed.
- Full test command: `D:\App\Anaconda\envs\minicode\python.exe -m pytest tests -q -p no:cacheprovider`
- Full test result: 351 passed in 6.64s, 0 failed, 0 errors.
- New test count in this polish pass: 15.

## Evaluation Harness

Added in `v1.0.0`:

- `benchmarks/smoke_eval.py`
- `benchmarks/cases/README.md`
- `benchmarks/reports/mock_smoke.json`
- `benchmarks/reports/mock_smoke.md`
- `benchmarks/reports/comparison.md`

Harness scope:

- Five task classes: code understanding, code location, single-file edit, bug fix, and intent constraint.
- Three runs per class, for 15 mock smoke runs.
- Fixed mock configuration: provider `mock`, model `mock-scripted-llm`, temperature `0.0`, max iterations `8`, max retries `1`, context max tokens `20000`, memory disabled, Intent Auditor disabled for Harness isolation.
- Reports include success count/rate, abnormal terminations, average tool calls, average iterations, average duration, unauthorized modifications, meaningless final answers, and token usage support status.

Harness verification:

- Command: `D:\App\Anaconda\envs\minicode\python.exe benchmarks\smoke_eval.py --provider mock --runs-per-case 3 --out-dir benchmarks\reports --report-name mock_smoke --python-exe D:\App\Anaconda\envs\minicode\python.exe`
- Result: 15/15 mock smoke runs passed.
- Formal real-model evaluation was not executed.
- The mock smoke result validates Harness plumbing only and is not a real-model capability score.

## Current Limits

- Shell risk controls are lightweight checks, not a complete OS sandbox.
- Intent Auditor is not a complete policy engine.
- Mini Vector DB / `EmbeddingClient` remains optional for vector search; local JSONL fallback handles unavailable vector components.
- Harness scale is limited and mock results must not be presented as real-model capability.
