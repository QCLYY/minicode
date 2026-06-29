# MiniCode 终端 Coding Agent 二次开发

## 项目简介

MiniCode 是一个基于开源 MiniCode 的终端 Coding Agent 二次开发项目。项目使用 Python、LangGraph、LangChain、LLM Tool Calling、Pytest 和 JSONL 存储，实现 Ask/Agent/Plan 三种模式、文件/搜索/Shell 工具调用、项目记忆、Intent Auditor 以及轻量评测 Harness。

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

- 修复 MiniCode 中文与只读意图识别缺陷，定位到中文关键词乱码与 `re.search()` 参数顺序问题，补充中文知识问答、只读分析和执行型任务回归覆盖，使测试结果从 320/323 提升到 336/336。
- 为 `ProjectMemory.search()` 增加本地 JSONL 关键词 fallback，在 `mini_vector_db` 或 EmbeddingClient 不可用、异常或无结果时仍能检索当前项目记忆，并覆盖空记忆、k 限制、文件名、中文关键词、异常降级等场景。
- 修复 Intent Auditor 在 Agent 模式阻止错配 thought 后返回 `Done.` 的问题，新增明确的 `auditor_blocked` / `finish_reason` 状态和可读阻止说明，累计新增 13 个回归测试函数覆盖记忆 fallback 与 Auditor 阻止路径。

## Harness 说明

新增 `benchmarks/smoke_eval.py` 轻量评测 Harness，覆盖代码理解、代码定位、单文件编辑、Bug 修复、意图约束五类任务。当前已执行 15 次 Mock LLM smoke run，用于验证 Harness、LangGraph 和工具调用链路可运行；未执行真实模型正式评测，因此不把 Mock 成功率写作模型能力指标。

## 30 秒介绍

我基于开源 MiniCode 做了一个终端 Coding Agent 的二次开发，重点不是重写 Agent，而是把本地可运行性、测试可靠性和评测链路补齐。我修复了中文只读请求识别、项目记忆在向量依赖缺失时无法检索、Intent Auditor 阻止后返回无意义 `Done.` 三类问题，并把全量测试从 320/323 提升到 336/336。最后我补了一个轻量 Harness，用 Mock LLM 验证 Agent 图和工具链路，真实模型评测入口也保留但不伪造结果。

## 2 分钟介绍

这个项目是基于开源 MiniCode 的终端 Coding Agent 二次开发，核心架构是 Python + LangGraph + LangChain Tool Calling。Agent 有 Ask、Agent、Plan 三种模式，Ask 只开放读文件和搜索工具，Agent/Plan 开放读写、精确编辑、grep/glob、Shell 六个工具。我的工作主要围绕可靠性和可评测性展开。

第一类问题是中文和只读意图识别。原代码里中文关键词出现乱码，并且部分正则调用参数顺序错误，导致“中国首都是哪里”“只告诉我错误原因，不要执行命令”这类请求不能正确识别。我修复了识别逻辑，并区分只读请求和执行型任务。

第二类问题是 ProjectMemory 依赖向量组件。一旦 `mini_vector_db` 或 EmbeddingClient 不可用，搜索会直接返回空。我保留原向量搜索优先路径，同时加了当前项目 JSONL 记录的本地关键词 fallback，支持英文、中文、文件名、k 限制和异常降级。

第三类问题是 Intent Auditor。Agent thought 被 Auditor 判定和用户意图不一致时，工具调用已经被阻止，但最终回答可能落到 `Done.`。我增加了明确的阻止状态和终止原因，保证不执行被阻止工具，并返回可理解的说明。

最后我新增了一个轻量 Harness，自动创建临时工作区、运行 Agent、检查修改文件、工具调用、pytest 和隐藏断言，并输出 JSON/Markdown 报告。当前真实测试结果是 336/336，Harness 的 15 次 Mock smoke 只说明评测框架可跑，不冒充真实模型效果。

## 面试问答

### 1. 为什么不直接让 `ProjectMemory.search()` 在向量不可用时返回全部记录？

返回全部记录会污染上下文，也会让测试误以为检索有效。我实现的是轻量相关度评分，只从当前项目 `TurnStore.load_all()` 的 JSONL 记录中检索，并且无匹配返回空、返回数不超过 k。

### 2. 中文意图识别为什么要先判断执行型任务？

因为“请修改这个函数”“运行测试并修复错误”这类请求即使包含解释性词汇，本质也是执行任务。先识别明确执行动作可以避免把需要写文件或跑命令的任务误判成 Ask-style 只读回答。

### 3. Intent Auditor 修复的关键是什么？

关键是把“被 Auditor 阻止”从普通完成中区分出来。修复后状态里有 `auditor_blocked` 和 `finish_reason="auditor_blocked"`，finish 阶段会返回已有有效文本或明确阻止说明，而不是走到空回答或 `Done.`。

### 4. Harness 为什么先用 Mock LLM？

Harness 本身要先验证评测流程、临时工作区、工具调用记录、自动打分和报告生成是否可靠。Mock LLM 可以确定性触发真实 Agent 图和工具，避免把模型波动、API Key、网络错误混进 Harness 开发阶段。

### 5. 这个项目还不能宣传成什么？

不能宣传成完全自研、生产级、企业级、高并发系统，也不能说 Shell 安全等于完整沙盒。它是基于开源项目的二次开发，当前重点是本地可靠性、测试基线和轻量评测链路。
