# MiniCode

MiniCode 是一个自主设计并实现的终端 Coding Agent，基于 LangGraph 构建
Ask、Agent、Plan 三种执行模式，支持代码检索、文件读写、局部编辑、Shell
执行、上下文管理、项目记忆和意图审计。

Copyright © 项目作者。当前仓库未声明明确开源许可证；如需公开分发或商用，
请先补充清晰的许可证声明。

## Core Features

- `ask`：只读模式，仅开放 `read_file`、`grep_search`、`glob_search`。
- `agent`：默认执行模式，开放全部六个工具，由模型决定读写、编辑和验证步骤。
- `plan`：计划执行模式，先生成计划，再进入执行、反思和必要的重规划流程。
- 项目记忆：支持会话记忆、JSONL 项目记忆，以及向量检索不可用时的本地关键词 fallback。
- 意图审计：在计划或工具调用前检查动作是否偏离用户目标。
- 轻量评测 Harness：自动创建临时工作区、运行任务、评分并输出 JSON/Markdown 报告。

## Architecture

Ask/Agent 主流程：

```text
User task
  -> init_node
  -> execute_node
  -> tools_node when the model emits tool calls
  -> execute_node until task_complete
  -> finish_node
```

Plan 模式主流程：

```text
init_node -> plan_node -> audit_plan_node -> execute/tools/reflect/replan -> finish_node
```

主要模块：

- `agent/agent.py`：`ClaudeCodeMini` Agent 封装。
- `graph/builder.py`：Ask、Agent、Plan 三种模式的 LangGraph 构建。
- `graph/nodes.py`：计划、执行、工具调用、反思、重规划、收尾和审计节点。
- `tools/`：文件读取、文件写入、局部编辑、grep、glob、Shell 六个工具。
- `memory/`：会话记忆、项目 JSONL 记忆和检索逻辑。
- `intent_auditor/`：意图一致性审计。
- `benchmarks/smoke_eval.py`：轻量 Coding Agent 评测 Harness。

## Tools

Ask 模式开放三种只读工具：

- `read_file`
- `grep_search`
- `glob_search`

Agent 和 Plan 模式开放六个工具：

- `read_file`
- `write_file`
- `edit_file`
- `grep_search`
- `glob_search`
- `shell_execute`

## Installation

本地固定 Python 环境：

```powershell
Set-Location "D:\App\Codex\workspaces\minicode"
D:\App\Anaconda\envs\minicode\python.exe -m pip install -r requirements.txt
D:\App\Anaconda\envs\minicode\python.exe -m pip install pytest pytest-asyncio
```

不要提交 `.env`、真实 API Key、Token 或密码。

## Environment

复制 `.env.example` 为 `.env`，只填写本地实际使用的占位变量：

```env
LLM_PROVIDER=openai
OPENAI_API_KEY=your-api-key
OPENAI_API_BASE=https://api.openai.com/v1
OPENAI_MODEL=gpt-4o

MEMORY_ENABLED=false
INTENT_AUDITOR_ENABLED=false
AUDITOR_TWO_LAYER=false
```

国内 OpenAI-compatible 模型可保持 `LLM_PROVIDER=openai`，再配置兼容地址和模型名：

```env
LLM_PROVIDER=openai
OPENAI_API_KEY=your-provider-key
OPENAI_API_BASE=https://dashscope.aliyuncs.com/compatible-mode/v1
OPENAI_MODEL=qwen-plus
```

Agent/Plan 模式依赖模型工具调用能力；如果模型或服务端不支持 tool calling，工具步骤会失败。

## CLI

常用参数：

- `--mode ask|agent|plan|react`：选择执行模式，`react` 会映射为 `agent`。
- `--workspace` / `-w`：指定工作区目录。
- `--model` / `-m`：覆盖模型名。
- `--max-iters`：设置 ReAct 循环最大迭代次数。
- `--max-retries`：设置单步最大重试次数。
- `--context-max-tokens`：设置上下文窗口预算。
- `--no-memory`：强制关闭记忆，优先级高于环境变量 `MEMORY_ENABLED=true`。
- `--raw`：输出 `agent.run()` 的原始 JSON 结果。

raw 与非 raw 模式使用同一套配置来源，`workspace`、`mode`、`max_iters`、
`max_retries`、`context_max_tokens` 和 `memory_enabled` 行为保持一致。

Ask 模式示例：

```powershell
D:\App\Anaconda\envs\minicode\python.exe main.py --mode ask --no-memory "Read README.md and summarize the project in three sentences. Do not modify files."
```

Agent 模式示例：

```powershell
D:\App\Anaconda\envs\minicode\python.exe main.py --mode agent --max-iters 12 --max-retries 1 --no-memory "Add type hints and a docstring to demo.py."
```

Plan 模式示例：

```powershell
D:\App\Anaconda\envs\minicode\python.exe main.py --mode plan --context-max-tokens 50000 --no-memory "Analyze failing tests and propose a fix plan."
```

Raw 输出示例：

```powershell
D:\App\Anaconda\envs\minicode\python.exe main.py --raw --mode ask --max-iters 5 --no-memory "Explain this repository."
```

## Shell Risk Controls

`shell_execute` 不是完整系统沙盒。本项目只实现轻量风险分级和默认拦截：

- `low`：典型只读命令，如 `dir`、`ls`、`pwd`、`type`、`cat`、`pytest`、
  `python -m py_compile`、`git status`、`git diff`。
- `medium`：可能修改工作区或依赖环境的命令，如 `mkdir`、`copy`、`move`、
  `git add`、`pip install`、`npm install`。这类命令允许执行，但会在结果
  metadata 中标记 `risk_level="medium"`。
- `high`：危险或不可逆命令，如 `rm -rf`、`rmdir /s`、`del /s`、`format`、
  `mkfs`、`diskpart`、`shutdown`、`reboot`、`git reset --hard`、
  `git clean -fd`、`git push --force`、删除工作区外文件、下载后直接执行脚本。
  这类命令默认拒绝执行。

Shell 工具返回 metadata：

```json
{
  "risk_level": "low|medium|high",
  "allowed": true,
  "blocked_reason": ""
}
```

安全建议：

- 在真实项目中优先使用 `ask` 模式做只读分析。
- 对修改类任务限制工作区，只在干净 Git 分支上运行。
- 不要让 Agent 处理包含真实密钥、生产数据或不可恢复文件的目录。
- 风险拦截不等于完整系统沙盒，不能替代容器、虚拟机或操作系统级隔离。

## Memory

- Session memory 保存当前 REPL 会话的最近任务。
- Project memory 使用 JSONL 保存当前项目的历史任务记录。
- 向量组件可用时优先走向量检索。
- 向量组件缺失、初始化失败、查询异常或无结果时，`ProjectMemory.search()`
  会回退到当前项目 JSONL 的轻量关键词检索。

关键词 fallback 只是降级方案，不等同于完整语义检索。

## Intent Auditor

Intent Auditor 会检查计划步骤或带工具调用的 thought 是否偏离用户目标。当前实现能够：

- 阻止明显与目标不一致的工具调用；
- 在阻止后返回可理解的说明，而不是空内容或 `Done.`；
- 在结果中暴露 `finish_reason="auditor_blocked"`。

它不是完整策略系统，也不是完整安全沙盒。

## Tests

运行全量测试：

```powershell
D:\App\Anaconda\envs\minicode\python.exe -m pytest tests -q -p no:cacheprovider
```

稳定版本 `v1.0.0` 基线：

```text
336 passed, 0 failed, 0 errors
```

小版本完善后验证结果：

```text
351 passed, 0 failed, 0 errors
```

## Evaluation Harness

Mock smoke Harness：

```powershell
D:\App\Anaconda\envs\minicode\python.exe benchmarks\smoke_eval.py --provider mock --runs-per-case 3 --out-dir benchmarks\reports --report-name mock_smoke --python-exe D:\App\Anaconda\envs\minicode\python.exe
```

当前已记录的 Mock Harness 结果：

- 15 次 mock run。
- 5 类任务：代码理解、代码定位、单文件编辑、Bug 修复、意图约束。
- 15/15 passed。
- 平均工具调用：1.8。
- 平均迭代：2.8。
- 平均耗时：0.575 秒。
- Token usage：当前 Agent 结果结构不支持可靠统计。
- 真实模型正式评测：未执行。

Mock Harness 只证明评测框架、LangGraph 流程和工具调用链路可运行，不代表真实模型能力。

真实模型评测入口：

```powershell
D:\App\Anaconda\envs\minicode\python.exe benchmarks\smoke_eval.py --provider configured --runs-per-case 3 --report-name real_model_eval
```

## Reliability And Evaluation Work

已完成的可靠性优化：

- 修复中文/只读意图识别。
- 为 `ProjectMemory.search()` 增加本地 JSONL fallback。
- 修复 Intent Auditor 阻止路径的最终回答和终止原因。
- 完善 CLI 参数透传，保证 raw 与非 raw 模式一致。
- 增加 Shell 命令风险分级和 high-risk 默认拦截。
- 建设轻量评测 Harness 和项目说明文档。

## Known Limits

- Shell 风险控制不是完整系统沙盒。
- Intent Auditor 不是完整策略系统。
- ProjectMemory 的关键词 fallback 是轻量降级检索。
- Harness 规模较小，真实模型效果需要按固定模型、配置和运行次数单独评测。
- 当前 Agent 结果结构不提供可靠 token usage。
