# MiniCode 终端 Coding Agent

## 项目简介

MiniCode 是一个自主设计并实现的终端 Coding Agent，基于 LangGraph 构建 Ask、Agent、Plan 三种执行模式，支持代码检索、文件读写、局部编辑、Shell 执行、上下文管理、项目记忆和意图审计。

## 技术栈

- Python
- LangGraph
- LangChain
- LLM Tool Calling
- Pytest / pytest-asyncio
- JSONL
- OpenAI-compatible Chat API
- PowerShell / CLI

## 简历要点

- 自主设计并实现基于 LangGraph 的终端 Coding Agent，支持 Ask、Agent、Plan 三种模式及文件检索、局部编辑、Shell 执行、上下文管理和项目记忆。
- 修复中文意图识别、记忆降级检索及 Intent Auditor 状态流转问题，将回归测试由 320/323 提升至 336/336，并新增 13 个回归测试函数覆盖关键可靠性路径。
- 完善 CLI 配置透传与 Shell 命令风险分级，对危险命令进行默认拦截；本轮新增 15 个自动化测试，最终全量测试达到 351/351。

## Harness 说明

`benchmarks/smoke_eval.py` 覆盖代码理解、代码定位、单文件编辑、Bug 修复、意图约束五类任务。当前已执行 15 次 Mock LLM smoke run，用于验证 Harness、LangGraph 和工具调用链路可运行；未执行真实模型正式评测，因此不把 Mock 成功率写作模型能力指标。

## 30 秒介绍

MiniCode 是我自主设计并实现的终端 Coding Agent，核心是用 LangGraph 组织 Ask、Agent、Plan 三种执行模式，并通过工具调用完成代码检索、文件编辑、Shell 验证、项目记忆和意图审计。我重点做了可靠性优化和评测体系建设：修复中文意图识别、记忆 fallback、Auditor 阻止路径、CLI 参数透传和 Shell 风险分级，并用 Pytest 和轻量 Harness 验证行为。

## 2 分钟介绍

这个项目是一个终端 Coding Agent，核心架构是 Python + LangGraph + LangChain Tool Calling。Agent 有 Ask、Agent、Plan 三种模式，Ask 只开放读文件和搜索工具，Agent/Plan 开放读写、局部编辑、grep/glob、Shell 六个工具。整体目标是让 Agent 能在本地工作区内完成代码理解、定位、修改和验证。

可靠性方面，我修复了三类核心问题。第一类是中文和只读意图识别，避免把“只告诉我错误原因，不要执行命令”误判成执行任务，也避免把“请修改这个函数”误判成只读回答。第二类是项目记忆检索，当向量组件不可用时，`ProjectMemory.search()` 会从当前项目 JSONL 记录做轻量关键词 fallback。第三类是 Intent Auditor，工具调用被判定偏离目标后不会继续执行，并会返回明确说明和 `finish_reason="auditor_blocked"`。

小版本完善中，我继续修复了 CLI 参数透传问题：raw 和非 raw 模式现在统一使用同一套配置来源，`--max-iters`、`--max-retries`、`--context-max-tokens`、`--workspace`、`--mode`、`--no-memory` 行为一致。同时为 Shell 工具增加 low/medium/high 风险分级，默认拦截 `rm -rf`、`git reset --hard`、`git push --force` 等高风险命令。最后用 Pytest 和 Mock Harness 做回归验证，Mock 结果只表示评测框架可运行，不冒充真实模型效果。

## 面试问答

### 1. 为什么要区分 Ask、Agent、Plan 三种模式？

Ask 适合只读理解和定位，物理上不开放写文件和 Shell；Agent 适合直接执行修改和验证；Plan 适合需要先拆解任务、再逐步执行的场景。模式拆分能降低误操作概率，也让用户更容易按风险选择运行方式。

### 2. ProjectMemory 为什么需要 fallback？

向量检索依赖外部组件或 embedding 服务，一旦不可用就会导致历史记录无法搜索。fallback 使用当前项目 JSONL 记录做轻量关键词评分，保证没有向量组件时仍能检索相关历史，同时不会跨项目读取数据。

### 3. Intent Auditor 修复的关键是什么？

关键是把“被 Auditor 阻止”从普通完成中区分出来。修复后状态里有 `auditor_blocked` 和 `finish_reason="auditor_blocked"`，finish 阶段会返回已有有效文本或明确阻止说明，而不是空回答或 `Done.`。

### 4. CLI 参数透传问题在哪里？

非 raw 模式曾经先创建了一个带用户参数的 `ClaudeCodeMini`，但实际执行时又重新创建 `AgentCLI`，且没有传入 `max_iters`、`max_retries`、`context_max_tokens` 等参数。修复后 raw 与非 raw 都通过同一个配置构造函数传参。

### 5. Shell 风险分级解决了什么，没解决什么？

它能默认拦截明显高风险命令，并给 medium 命令打标，减少误执行危险命令的概率。但它不是完整系统沙盒，不能替代容器、虚拟机、权限隔离或人工审核。
