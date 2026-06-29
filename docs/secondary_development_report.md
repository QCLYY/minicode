# MiniCode Secondary Development Report

Date: 2026-06-29

## Baseline

- Before fix: 320/323 passed, 3 failed, 0 errors.
- Failed areas:
  - Chinese/direct-answer intent detection.
  - `ProjectMemory.search()` returning no results when Mini Vector DB / `EmbeddingClient` is unavailable.
  - Agent-mode Intent Auditor blocked-path handling could fall through to a meaningless `Done.` final answer.

## Defects And Root Causes

### Chinese Direct-Answer Detection

Root cause:

- `memory/project.py` contained corrupted Chinese intent keyword literals.
- `is_direct_answer_query()` called `re.search()` with reversed arguments, so direct-answer regexes were not applied to the task text.
- Coding/action keywords were too broad for read-only Chinese requests containing negated actions such as `不要修改` or `不要执行`.

Fix:

- Added valid UTF-8 Chinese and English intent patterns.
- Added positive execution-intent detection that strips negated actions before matching.
- Kept execution tasks such as modify, run, create, fix, install, commit, and delete classified as non-direct-answer.
- Kept read-only requests such as explanation, cause analysis, and general knowledge questions classified as direct-answer.

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

- In agent mode, the blocked-path audit could reuse the same mock/agent LLM for NLI fallback.
- That consumed the response intended for the agent's reconsidered answer.
- The next agent call then returned the mock fallback `Done.`, and `finish_node` treated it like a normal no-tool completion.
- The state did not clearly distinguish normal completion from an Intent Auditor block.

Fix:

- Added a small local mismatch guard for obvious direct/read-only user goals paired with mutating tool thoughts.
- Added `auditor_blocked`, `finish_reason`, and `auditor_blocked_answer` state fields.
- Preserved the normal allowed-tool path.
- Made `finish_node` prefer a meaningful recovery answer after a block, and fall back to a clear block explanation instead of `Done.`.
- Marked blocked completions with `finish_reason="auditor_blocked"` and memory success `False`.

## Modified Files

- `memory/project.py`
- `agent/state.py`
- `graph/nodes.py`
- `graph/routing.py`
- `tests/test_dual_mode.py`
- `tests/test_intent_auditor.py`
- `tests/test_memory.py`
- `.gitignore`
- `docs/secondary_development_report.md`

## Tests Added

- Added 9 new pytest test functions for ProjectMemory fallback behavior.
- Added 4 new pytest test functions for Intent Auditor blocked/allowed behavior.
- Added 6 direct-answer regression assertions for Chinese/read-only/execution classification.

## Verification

Target tests:

- `tests/test_dual_mode.py::TestIsConversationalQuery::test_direct_answer_detects_general_knowledge`: passed.
- `tests/test_graph.py::TestIsDirectAnswerQuery::test_general_knowledge_questions`: passed.
- `tests/test_memory.py::TestProjectMemory::test_search_returns_relevant`: passed.

Related module tests:

- Command: `D:\App\Anaconda\envs\minicode\python.exe -m pytest tests/test_dual_mode.py tests/test_graph.py tests/test_memory.py -q`
- Result: 136 passed.
- Command: `D:\App\Anaconda\envs\minicode\python.exe -m pytest tests/test_intent_auditor.py -q`
- Result: 34 passed.

Full test run:

- Command: `D:\App\Anaconda\envs\minicode\python.exe -m pytest tests -q --basetemp="D:\App\Codex\workspaces\minicode\pytest_tmp_run_pycharm\final"`
- Result: 336 passed, 0 failed, 0 errors.
- Change from original baseline: 320/323 passed to 336/336 passed.

## Pytest Cache Handling

- `.pytest_cache/`, `.pytest_tmp/`, and `pytest_tmp_run*/` are ignored.
- No pytest cache warning appeared in the final full run.

## External Dependencies And Limits

- Mini Vector DB / `EmbeddingClient` remains optional for vector search; local JSONL fallback now handles unavailable vector components.
- Intent Auditor still depends on its existing embedding or NLI path for non-obvious alignment checks; the new local guard only handles clear direct/read-only goal versus mutating-action mismatches.
- This pass did not modify multi-agent, MCP, shell safety, web UI, or the LangGraph graph topology.

## Final-Stage Harness And Documentation

Added:

- `benchmarks/smoke_eval.py`
- `benchmarks/cases/README.md`
- `benchmarks/reports/mock_smoke.json`
- `benchmarks/reports/mock_smoke.md`
- `benchmarks/reports/comparison.md`
- `docs/resume_project_summary.md`
- Updated `README.md`

Harness scope:

- Five task classes: code understanding, code location, single-file edit, bug fix, and intent constraint.
- Three runs per class, for 15 mock smoke runs.
- Fixed mock configuration: provider `mock`, model `mock-scripted-llm`, temperature `0.0`, max iterations `8`, max retries `1`, context max tokens `20000`, memory disabled, Intent Auditor disabled for Harness isolation.
- Reports include success count/rate, abnormal terminations, average tool calls, average iterations, average duration, unauthorized modifications, meaningless final answers, and token usage support status.

Harness verification:

- Command: `D:\App\Anaconda\envs\minicode\python.exe benchmarks\smoke_eval.py --provider mock --runs-per-case 3 --out-dir benchmarks\reports --report-name mock_smoke --python-exe D:\App\Anaconda\envs\minicode\python.exe`
- Result: 15/15 mock smoke runs passed.
- Final pytest command: `D:\App\Anaconda\envs\minicode\python.exe -m pytest tests -q -p no:cacheprovider`
- Final pytest result: 336 passed in 6.80s.
- Formal real-model evaluation was not executed because no real model run was requested with a configured API key during this phase.
- The mock smoke result validates Harness plumbing only and is not a real-model capability score.

Baseline comparison:

- Actual Harness baseline-vs-develop comparison was not executed because the `baseline` tag predates the new Harness entry point.
- No fake `baseline.json` or `improved.json` files were created.
- Existing verified regression data remains: 320/323 before reliability fixes and 336/336 after reliability fixes.
