# MiniCode

MiniCode is a terminal Coding Agent based on the open-source MiniCode project
from `myx-99/minicode`, with secondary development in this repository for local
initialization, reliability fixes, lightweight memory fallback, Intent Auditor
blocked-path handling, and a small evaluation Harness.

This is not a fully from-scratch project. Keep upstream attribution and verify
the upstream license before public reuse. The original README declares MIT, but
this repository currently does not include a separate `LICENSE` file.

## What It Does

MiniCode runs an LLM-driven coding loop in a workspace. It uses LangGraph for
control flow, LangChain tool-calling interfaces for model/tool interaction, and
six local tools for file reading, file writing, precise edits, grep search, glob
search, and shell execution.

The three user-facing modes are:

- `ask`: read-only exploration with `read_file`, `grep_search`, and `glob_search`.
- `agent`: default tool-using coding mode with all six tools.
- `plan`: plan-and-execute mode with plan auditing before execution.

## Architecture

Core workflow:

```text
User task
  -> init_node
  -> execute_node
  -> tools_node when the model emits tool calls
  -> execute_node until the model emits task_complete
  -> finish_node
```

Plan mode adds:

```text
init_node -> plan_node -> audit_plan_node -> execute/tools/reflect/replan -> finish_node
```

Main components:

- `agent/agent.py`: `ClaudeCodeMini` public Agent wrapper.
- `graph/builder.py`: LangGraph graph construction for Ask, Agent, and Plan.
- `graph/nodes.py`: planning, execution, tool, reflection, replan, finish, and auditor logic.
- `tools/`: six local tools.
- `memory/`: session memory, project JSONL memory, and vector-search integration.
- `intent_auditor/`: NLI/embedding-based intent alignment checks.
- `benchmarks/smoke_eval.py`: lightweight Coding Agent Harness.

## Tools

Ask mode exposes three read-only tools:

- `read_file`
- `grep_search`
- `glob_search`

Agent and Plan modes expose all six tools:

- `read_file`
- `write_file`
- `edit_file`
- `grep_search`
- `glob_search`
- `shell_execute`

Shell safety is workspace-oriented command execution with basic blocking rules.
It is not a full operating-system sandbox.

## Installation

Use the fixed local Python environment for this workspace:

```powershell
Set-Location "D:\App\Codex\workspaces\minicode"
D:\App\Anaconda\envs\minicode\python.exe -m pip install -r requirements.txt
D:\App\Anaconda\envs\minicode\python.exe -m pip install pytest pytest-asyncio
```

Do not commit `.env` or real API keys.

## Environment

Create a local `.env` from `.env.example` and fill only placeholder values you
actually use:

```env
LLM_PROVIDER=openai
OPENAI_API_KEY=your-api-key
OPENAI_API_BASE=https://api.openai.com/v1
OPENAI_MODEL=gpt-4o

MEMORY_ENABLED=false
INTENT_AUDITOR_ENABLED=false
AUDITOR_TWO_LAYER=false
```

For OpenAI-compatible domestic providers, keep `LLM_PROVIDER=openai` and set the
compatible base URL and model name. Example shape only:

```env
LLM_PROVIDER=openai
OPENAI_API_KEY=your-provider-key
OPENAI_API_BASE=https://dashscope.aliyuncs.com/compatible-mode/v1
OPENAI_MODEL=qwen-plus
```

The selected model must support tool calling for Agent and Plan modes. If a
provider rejects the model name or does not support tool calls, the Agent cannot
complete tool-based steps.

## Commands

Ask mode:

```powershell
D:\App\Anaconda\envs\minicode\python.exe main.py --mode ask --no-memory "读取 README.md，用三句话说明该项目实现了什么功能。不要修改文件。"
```

Agent mode:

```powershell
D:\App\Anaconda\envs\minicode\python.exe main.py --mode agent --no-memory "为 demo.py 中的 add 函数增加类型注解和 docstring，不要修改其他文件。"
```

Plan mode:

```powershell
D:\App\Anaconda\envs\minicode\python.exe main.py --mode plan --no-memory "检查项目测试失败原因并给出修复计划。"
```

Interactive REPL:

```powershell
D:\App\Anaconda\envs\minicode\python.exe main.py --mode agent --no-memory
```

## Memory

MiniCode has session memory and project memory:

- Session memory keeps recent turns in the current REPL process.
- Project memory persists turn records as JSONL under the current project scope.
- Vector memory is used when `mini_vector_db` and its embedding client are available.
- When vector search is unavailable or fails, `ProjectMemory.search()` now falls
  back to local keyword scoring over the current project's JSONL records.

The keyword fallback is a local fallback only; it does not replace semantic
vector retrieval when a working vector backend is configured.

## Intent Auditor

The Intent Auditor checks whether planned or tool-bound actions align with the
user's request. The reliability pass fixed the blocked path so a rejected action:

- does not execute the blocked tool call;
- returns a meaningful final answer instead of `Done.`;
- records `finish_reason="auditor_blocked"` for callers that need to distinguish it.

The Auditor still depends on the existing embedding or NLI path for non-obvious
alignment cases. It is not a complete policy or sandbox system.

## Tests

Run the full regression suite:

```powershell
D:\App\Anaconda\envs\minicode\python.exe -m pytest tests -q -p no:cacheprovider
```

Verified result after reliability fixes:

```text
336 passed in 6.80s
```

Original reliability baseline before fixes:

```text
320/323 passed
```

Fixed issue classes:

- Chinese/read-only direct-answer intent detection.
- `ProjectMemory.search()` fallback when vector components are unavailable.
- Intent Auditor blocked-path final answer and termination reason.

## Evaluation Harness

The lightweight Harness is intentionally small and local:

```powershell
D:\App\Anaconda\envs\minicode\python.exe benchmarks\smoke_eval.py --provider mock --runs-per-case 3 --out-dir benchmarks\reports --report-name mock_smoke --python-exe D:\App\Anaconda\envs\minicode\python.exe
```

Current Harness report:

- Report files: `benchmarks/reports/mock_smoke.json`, `benchmarks/reports/mock_smoke.md`.
- Task classes: code understanding, code location, single-file edit, bug fix, intent constraint.
- Run count: 15 mock runs.
- Mock smoke result: 15/15 passed.
- Average tool calls: 1.8.
- Average iterations: 2.8.
- Average duration: 0.575 seconds.
- Token usage: unsupported by the current Agent result schema.
- Formal real-model evaluation: not executed.

The mock result validates Harness plumbing, graph execution, tool calls, scoring,
and report generation. It must not be presented as a real-model success rate.

To run a real configured model:

```powershell
D:\App\Anaconda\envs\minicode\python.exe benchmarks\smoke_eval.py --provider configured --runs-per-case 3 --report-name real_model_eval
```

Only run this after `.env` is configured with a real tool-calling model. Do not
commit private model responses, keys, or local temporary workspaces.

## Secondary Development Summary

This repository's secondary development work added:

- Reliable Chinese/read-only intent classification for Ask-style requests.
- Local JSONL keyword fallback for `ProjectMemory`.
- Safer Intent Auditor blocked-path handling with meaningful final answers.
- A deterministic smoke evaluation Harness.
- Updated project and resume documentation.

## Known Limits

- The project is a terminal Coding Agent prototype, not a production-grade system.
- Shell safety is not a complete system sandbox.
- Memory fallback is keyword-based and intentionally lightweight.
- Intent Auditor is useful for obvious mismatch handling but is not a full policy engine.
- Harness scale is limited to five task classes and small temporary workspaces.
- Real evaluation results are tied to the exact model, provider, prompts, and run count.
- Token usage is not reported unless the Agent result schema exposes reliable usage data.
