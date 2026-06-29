# MiniCode Baseline Test Report

## Run Metadata

- Execution date: 2026-06-29
- Project path: `D:\App\Codex\workspaces\minicode`
- Python executable: `D:\App\Anaconda\envs\minicode\python.exe`
- Python version: `Python 3.12.13`
- Test command: `D:\App\Anaconda\envs\minicode\python.exe -m pytest tests -q`
- Dependency install commands:
  - `D:\App\Anaconda\envs\minicode\python.exe -m pip install --upgrade pip`
  - `D:\App\Anaconda\envs\minicode\python.exe -m pip install -r requirements.txt`
  - `D:\App\Anaconda\envs\minicode\python.exe -m pip install pytest pytest-asyncio`

## Dependency Environment

`pip` was already installed as `26.1.2`. Project and test dependencies were already satisfied in the `minicode` Conda environment; no project dependency versions were upgraded.

Key installed packages:

- `langchain==1.3.11`
- `langgraph==1.2.6`
- `langchain-openai==1.3.3`
- `langchain-anthropic==1.4.8`
- `pydantic==2.13.4`
- `pydantic-settings==2.14.2`
- `rich==15.0.0`
- `python-dotenv==1.2.2`
- `numpy==2.5.0`
- `pytest==9.1.1`
- `pytest-asyncio==1.4.0`

Full `pip freeze` snapshot:

```text
annotated-types==0.7.0
anthropic==0.112.0
anyio==4.14.1
certifi==2026.6.17
charset-normalizer==3.4.7
colorama==0.4.6
distro==1.9.0
docstring_parser==0.18.0
h11==0.16.0
httpcore==1.0.9
httpx==0.28.1
idna==3.18
iniconfig==2.3.0
jiter==0.15.0
jsonpatch==1.33
jsonpointer==3.1.1
langchain==1.3.11
langchain-anthropic==1.4.8
langchain-core==1.4.8
langchain-openai==1.3.3
langchain-protocol==0.0.18
langgraph==1.2.6
langgraph-checkpoint==4.1.1
langgraph-prebuilt==1.1.0
langgraph-sdk==0.4.2
langsmith==0.9.3
markdown-it-py==4.2.0
mdurl==0.1.2
numpy==2.5.0
openai==2.44.0
orjson==3.11.9
ormsgpack==1.12.2
packaging==26.0
pluggy==1.6.0
pydantic==2.13.4
pydantic-settings==2.14.2
pydantic_core==2.46.4
Pygments==2.20.0
pytest==9.1.1
pytest-asyncio==1.4.0
python-dotenv==1.2.2
PyYAML==6.0.3
regex==2026.6.28
requests==2.34.2
requests-toolbelt==1.0.0
rich==15.0.0
setuptools==82.0.1
sniffio==1.3.1
tenacity==9.1.4
tiktoken==0.13.0
tqdm==4.68.3
typing-inspection==0.4.2
typing_extensions==4.15.0
urllib3==2.7.0
uuid_utils==0.16.2
websockets==15.0.1
wheel==0.47.0
xxhash==3.8.0
zstandard==0.25.0
```

## Test Summary

- Total tests: 323
- Passed: 319
- Failed: 4
- Skipped: 0
- Total pytest time: 5.20s
- Exit code: 1

Pytest summary:

```text
4 failed, 319 passed in 5.20s
```

## Failed Tests

### `tests/test_dual_mode.py::TestIsConversationalQuery::test_direct_answer_detects_general_knowledge`

Observed failure:

```text
assert is_direct_answer_query("中国首都是哪里") is True
E AssertionError: assert False is True
```

Root cause category: direct-answer query detection logic.

Likely root cause: `memory.project.is_direct_answer_query()` does not recognize this Chinese general-knowledge query. The implementation calls `re.search(task_stripped.lower(), pattern)`, which appears to reverse the intended regex arguments. Several Chinese regex patterns in `memory/project.py` also appear mojibake-corrupted, so Chinese natural-language detection is unreliable.

### `tests/test_graph.py::TestIsDirectAnswerQuery::test_general_knowledge_questions`

Observed failure:

```text
assert is_direct_answer_query("中国首都是哪里") is True
E AssertionError: assert False is True
```

Root cause category: duplicate coverage of the same direct-answer detection issue.

Likely root cause: same as above. The test hits `memory.project.is_direct_answer_query()` with the same Chinese query and receives `False`.

### `tests/test_intent_auditor.py::TestAgentModeAuditorIntegration::test_thought_blocked_when_misaligned`

Observed failure:

```text
assert "Claude Code Mini" in final.get("final_answer", "")
E AssertionError: assert 'Claude Code Mini' in 'Done.'
```

Root cause category: Intent Auditor integration / mocked LLM call sequencing.

Likely root cause: when the agent-mode auditor blocks a misaligned tool call, the graph reaches `done`, but the final pass-through answer is the mock fallback `"Done."` instead of the expected reconsidered answer. This suggests the auditor path consumes or bypasses the mocked response sequence expected by the test, so the final answer assembly no longer observes the intended `AIMessage` content.

### `tests/test_memory.py::TestProjectMemory::test_search_returns_relevant`

Observed failure:

```text
assert len(results) >= 1
E assert 0 >= 1
```

Captured log:

```text
Cannot import mini_vector_db EmbeddingClient. Vector memory search will be unavailable.
```

Root cause category: external optional dependency missing.

Likely root cause: `ProjectMemory.search()` now depends on a sibling `mini_vector_db` backend (`mini_vector_db/backend/embedding_client.py`) and a Mini Vector DB binary path outside this repository. That dependency is not present in the imported MiniCode workspace, so vector search returns an empty list even after turns are added to the JSONL store.

## Failure Classification

- Query classification / Unicode handling: 2 tests
- Intent Auditor graph behavior / final answer regression: 1 test
- Missing external vector memory dependency: 1 test

## External Services and Runtime Risks

- Real Ask/Agent CLI operation requires `OPENAI_API_KEY` or `ANTHROPIC_API_KEY`.
- No real LLM API key was present in the current environment during baseline setup.
- Intent Auditor is enabled by default and two-layer auditing defaults to DashScope-compatible embeddings via `EMBED_API_KEY`.
- Project Memory is enabled by default in CLI construction unless `--no-memory` is passed, and vector search expects the external `mini_vector_db` project.
- `pip install --upgrade pip` attempted to reach `https://pypi.tuna.tsinghua.edu.cn/simple` but the sandbox denied network sockets. This did not block setup because required packages were already installed.

## Smoke Validation

Real-provider smoke tests were not run because no LLM API key was configured. Local graph/tool smoke tests were run with an injected mock LLM and optional features disabled via environment variables:

- Ask mode: succeeded; `read_file` read `README.md`; final answer was non-empty.
- Agent mode in `D:\App\Codex\workspaces\minicode_demo`: succeeded after granting write permission to that external demo workspace; `read_file` and `edit_file` operated only on relative path `demo.py`; resulting file parsed as valid Python.
