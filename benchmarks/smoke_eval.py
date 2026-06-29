#!/usr/bin/env python3
"""Lightweight MiniCode coding-agent evaluation harness.

The default provider is a deterministic mock LLM. It still drives the real
ClaudeCodeMini graph and tool layer, so it validates harness plumbing without
requiring API keys. Use ``--provider configured`` only when a real model is
configured through the project's normal environment settings.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from langchain_core.messages import AIMessage

from agent.agent import ClaudeCodeMini
from config.settings import settings


IGNORE_DIRS = {
    ".git",
    ".pytest_cache",
    "__pycache__",
    ".mypy_cache",
    ".tox",
    "node_modules",
}
IGNORE_SUFFIXES = {".pyc", ".pyo"}
WRITE_TOOLS = {"write_file", "edit_file"}


@dataclass(frozen=True)
class EvalCase:
    case_id: str
    category: str
    description: str
    task: str
    mode: str
    files: dict[str, str]
    allowed_changed: tuple[str, ...] = ()
    protected_unchanged: tuple[str, ...] = ()


def _status_text(text: str, reason: str = "Completed") -> str:
    return (
        f"{text}\n\n"
        "---AGENT_STATUS---\n"
        f'{{"action": "task_complete", "reason": "{reason}"}}\n'
        "---END_STATUS---"
    )


def _tool_call(name: str, args: dict[str, Any], call_id: str, thought: str) -> AIMessage:
    return AIMessage(
        content=f"Thought: {thought}",
        tool_calls=[
            {
                "name": name,
                "args": args,
                "id": call_id,
                "type": "tool_call",
            }
        ],
    )


def _quote_command_path(path: str) -> str:
    if re.search(r"\s", path):
        return f'"{path}"'
    return path


class HarnessMockLLM:
    """Canned LLM responses for smoke evaluation."""

    def __init__(self, case_id: str, python_exe: str):
        self.case_id = case_id
        self.python_exe = python_exe
        self._call_count = 0
        self._bound_tools = None
        self._responses = self._build_responses(case_id)

    def bind_tools(self, tool_schemas):
        self._bound_tools = tool_schemas
        return self

    async def ainvoke(self, messages, **kwargs):
        if self._call_count < len(self._responses):
            response = self._responses[self._call_count]
            self._call_count += 1
            return response
        return AIMessage(content=self._fallback_answer())

    def _pytest_command(self) -> str:
        return f"{_quote_command_path(self.python_exe)} -m pytest -q"

    def _build_responses(self, case_id: str) -> list[AIMessage]:
        if case_id == "code_understanding":
            final = (
                "invoice_total reads the items, computes a subtotal, applies a "
                "large-order discount, adds tax, and returns the final total."
            )
            return [
                _tool_call(
                    "read_file",
                    {"file_path": "calculator.py"},
                    "call_read_calculator",
                    "I should inspect calculator.py before explaining the function.",
                ),
                AIMessage(content=_status_text(final, "Explained function")),
                AIMessage(content=final),
            ]

        if case_id == "code_location":
            final = "services/billing.py"
            return [
                _tool_call(
                    "grep_search",
                    {"pattern": r"def calculate_invoice", "glob": "*.py"},
                    "call_find_invoice",
                    "I should search Python files for the function definition.",
                ),
                AIMessage(content=_status_text(final, "Located function")),
                AIMessage(content=final),
            ]

        if case_id == "single_file_edit":
            old = "def add(a, b):\n    return a + b\n"
            new = (
                "def add(a: int | float, b: int | float) -> int | float:\n"
                "    \"\"\"Return the sum of two numeric values.\"\"\"\n"
                "    if not isinstance(a, (int, float)) or not isinstance(b, (int, float)):\n"
                "        raise ValueError(\"add expects numeric values\")\n"
                "    return a + b\n"
            )
            final = (
                "Updated math_utils.py with numeric type annotations, a docstring, "
                "and input validation. The public pytest check passed."
            )
            return [
                _tool_call(
                    "read_file",
                    {"file_path": "math_utils.py"},
                    "call_read_math",
                    "I should read math_utils.py to edit the exact function body.",
                ),
                _tool_call(
                    "edit_file",
                    {
                        "file_path": "math_utils.py",
                        "old_string": old,
                        "new_string": new,
                    },
                    "call_edit_math",
                    "I can now make the requested single-file change.",
                ),
                _tool_call(
                    "shell_execute",
                    {"command": self._pytest_command(), "timeout": 30},
                    "call_test_math",
                    "I should run the public test after the edit.",
                ),
                AIMessage(content=_status_text(final, "Edited and tested")),
                AIMessage(content=final),
            ]

        if case_id == "bug_fix":
            old = '        amount += item["price"]\n'
            new = '        amount += item["price"] * item.get("qty", 1)\n'
            final = (
                "Fixed cart.total so each item's price is multiplied by its "
                "quantity, while leaving tests unchanged. The pytest check passed."
            )
            return [
                _tool_call(
                    "read_file",
                    {"file_path": "cart.py"},
                    "call_read_cart",
                    "I should inspect cart.py to find the quantity bug.",
                ),
                _tool_call(
                    "edit_file",
                    {
                        "file_path": "cart.py",
                        "old_string": old,
                        "new_string": new,
                    },
                    "call_edit_cart",
                    "The fix belongs in business code, not in the test file.",
                ),
                _tool_call(
                    "shell_execute",
                    {"command": self._pytest_command(), "timeout": 30},
                    "call_test_cart",
                    "I should run the tests after changing cart.py.",
                ),
                AIMessage(content=_status_text(final, "Bug fixed")),
                AIMessage(content=final),
            ]

        if case_id == "intent_constraint":
            final = (
                "broken.py 中 divide(a, b) 直接执行 a / b；当 b 为 0 时，"
                "Python 会抛出 ZeroDivisionError。该请求只需要分析原因，"
                "因此没有修改文件，也没有执行命令。"
            )
            return [
                _tool_call(
                    "read_file",
                    {"file_path": "broken.py"},
                    "call_read_broken",
                    "I should read the file only; the user forbids modification and shell commands.",
                ),
                AIMessage(content=_status_text(final, "Read-only analysis")),
                AIMessage(content=final),
            ]

        raise ValueError(f"Unknown mock case: {case_id}")

    def _fallback_answer(self) -> str:
        return _status_text("The mock LLM has no more scripted responses.")


def build_cases() -> list[EvalCase]:
    return [
        EvalCase(
            case_id="code_understanding",
            category="code_understanding",
            description="Explain a function without modifying the workspace.",
            task=(
                "Read calculator.py and explain in two sentences what "
                "invoice_total does. Do not modify files."
            ),
            mode="ask",
            files={
                "calculator.py": (
                    "def invoice_total(items, tax_rate):\n"
                    "    subtotal = sum(item[\"price\"] * item.get(\"qty\", 1) for item in items)\n"
                    "    discount = subtotal * 0.1 if subtotal >= 100 else 0\n"
                    "    taxable = subtotal - discount\n"
                    "    return round(taxable * (1 + tax_rate), 2)\n"
                )
            },
        ),
        EvalCase(
            case_id="code_location",
            category="code_location",
            description="Locate a function across multiple files without edits.",
            task=(
                "Find which file defines calculate_invoice and answer only "
                "with the relative path. Do not modify files."
            ),
            mode="ask",
            files={
                "services/billing.py": (
                    "def calculate_invoice(order):\n"
                    "    return sum(line[\"amount\"] for line in order[\"lines\"])\n"
                ),
                "services/users.py": "def load_user(user_id):\n    return {\"id\": user_id}\n",
                "README.md": "# Demo service\n",
            },
        ),
        EvalCase(
            case_id="single_file_edit",
            category="single_file_edit",
            description="Modify one file with annotations, docstring, and validation.",
            task=(
                "For math_utils.py, add type annotations, a docstring, and "
                "numeric input validation to add. Do not modify other files."
            ),
            mode="agent",
            files={
                "math_utils.py": "def add(a, b):\n    return a + b\n",
                "test_math_utils.py": (
                    "from math_utils import add\n\n"
                    "def test_add_public():\n"
                    "    assert add(2, 3) == 5\n"
                ),
            },
            allowed_changed=("math_utils.py",),
            protected_unchanged=("test_math_utils.py",),
        ),
        EvalCase(
            case_id="bug_fix",
            category="bug_fix",
            description="Fix a small bug in business code while preserving tests.",
            task=(
                "Run the tests, find the bug, and fix the business code. "
                "Do not modify tests."
            ),
            mode="agent",
            files={
                "cart.py": (
                    "def total(items):\n"
                    "    amount = 0\n"
                    "    for item in items:\n"
                    "        amount += item[\"price\"]\n"
                    "    return amount\n"
                ),
                "test_cart.py": (
                    "from cart import total\n\n"
                    "def test_total_uses_quantity():\n"
                    "    items = [{\"price\": 5, \"qty\": 2}, {\"price\": 3, \"qty\": 1}]\n"
                    "    assert total(items) == 13\n"
                ),
            },
            allowed_changed=("cart.py",),
            protected_unchanged=("test_cart.py",),
        ),
        EvalCase(
            case_id="intent_constraint",
            category="intent_constraint",
            description="Respect a read-only/no-shell constraint while answering.",
            task="分析 broken.py 中可能出现 ZeroDivisionError 的原因，不要修改文件，也不要执行命令。",
            mode="ask",
            files={
                "broken.py": "def divide(a, b):\n    return a / b\n",
            },
        ),
    ]


def write_case_files(workspace: Path, case: EvalCase) -> None:
    for relative, content in case.files.items():
        path = workspace / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8", newline="\n")


def should_ignore(path: Path) -> bool:
    if any(part in IGNORE_DIRS for part in path.parts):
        return True
    return path.suffix in IGNORE_SUFFIXES


def workspace_hashes(workspace: Path) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for path in sorted(workspace.rglob("*")):
        if not path.is_file() or should_ignore(path.relative_to(workspace)):
            continue
        rel = path.relative_to(workspace).as_posix()
        hashes[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
    return hashes


def changed_files(before: dict[str, str], after: dict[str, str]) -> list[str]:
    all_paths = sorted(set(before) | set(after))
    return [path for path in all_paths if before.get(path) != after.get(path)]


def run_subprocess(
    command: list[str],
    workspace: Path,
    timeout: int = 20,
) -> tuple[bool, str]:
    try:
        completed = subprocess.run(
            command,
            cwd=str(workspace),
            text=True,
            capture_output=True,
            timeout=timeout,
        )
    except Exception as exc:
        return False, str(exc)
    output = (completed.stdout + "\n" + completed.stderr).strip()
    return completed.returncode == 0, output


def is_meaningless_answer(answer: str) -> bool:
    normalized = answer.strip().lower()
    return normalized in {"", "done", "done.", "ok", "completed", "task complete"}


def tool_names(result: dict[str, Any]) -> list[str]:
    return [entry.get("tool", "") for entry in result.get("tool_history", [])]


def evaluate_code_understanding(
    workspace: Path,
    result: dict[str, Any],
    changes: list[str],
    python_exe: str,
) -> list[str]:
    del workspace, python_exe
    reasons: list[str] = []
    answer = result.get("final_answer", "")
    lowered = answer.lower()
    for term in ("subtotal", "discount", "tax", "total"):
        if term not in lowered:
            reasons.append(f"missing key behavior term: {term}")
    if changes:
        reasons.append(f"unexpected file changes: {changes}")
    if WRITE_TOOLS & set(tool_names(result)):
        reasons.append("write/edit tool was used in read-only explanation")
    return reasons


def evaluate_code_location(
    workspace: Path,
    result: dict[str, Any],
    changes: list[str],
    python_exe: str,
) -> list[str]:
    del workspace, python_exe
    reasons: list[str] = []
    answer = result.get("final_answer", "")
    if "services/billing.py" not in answer.replace("\\", "/"):
        reasons.append("answer did not include services/billing.py")
    if changes:
        reasons.append(f"unexpected file changes: {changes}")
    if "shell_execute" in tool_names(result):
        reasons.append("shell was used for a code-location task")
    return reasons


def evaluate_single_file_edit(
    workspace: Path,
    result: dict[str, Any],
    changes: list[str],
    python_exe: str,
) -> list[str]:
    del result
    reasons: list[str] = []
    if changes != ["math_utils.py"]:
        reasons.append(f"expected only math_utils.py to change, got {changes}")

    ok, output = run_subprocess([python_exe, "-m", "py_compile", "math_utils.py"], workspace)
    if not ok:
        reasons.append(f"py_compile failed: {output[:200]}")

    ok, output = run_subprocess([python_exe, "-m", "pytest", "-q"], workspace)
    if not ok:
        reasons.append(f"public pytest failed: {output[:300]}")

    hidden = (
        "from math_utils import add\n"
        "assert {'a', 'b', 'return'} <= set(add.__annotations__)\n"
        "assert add.__doc__ and 'sum' in add.__doc__.lower()\n"
        "assert add(1.5, 2.0) == 3.5\n"
        "try:\n"
        "    add('1', 2)\n"
        "except ValueError:\n"
        "    pass\n"
        "else:\n"
        "    raise AssertionError('expected ValueError')\n"
    )
    ok, output = run_subprocess([python_exe, "-c", hidden], workspace)
    if not ok:
        reasons.append(f"hidden assertions failed: {output[:300]}")
    return reasons


def evaluate_bug_fix(
    workspace: Path,
    result: dict[str, Any],
    changes: list[str],
    python_exe: str,
) -> list[str]:
    del result
    reasons: list[str] = []
    if "test_cart.py" in changes:
        reasons.append("test_cart.py was modified")
    if "cart.py" not in changes:
        reasons.append("cart.py was not modified")

    ok, output = run_subprocess([python_exe, "-m", "pytest", "-q"], workspace)
    if not ok:
        reasons.append(f"public pytest failed: {output[:300]}")

    hidden = (
        "from cart import total\n"
        "assert total([{'price': 2, 'qty': 4}]) == 8\n"
        "assert total([{'price': 2}]) == 2\n"
    )
    ok, output = run_subprocess([python_exe, "-c", hidden], workspace)
    if not ok:
        reasons.append(f"hidden assertions failed: {output[:300]}")
    return reasons


def evaluate_intent_constraint(
    workspace: Path,
    result: dict[str, Any],
    changes: list[str],
    python_exe: str,
) -> list[str]:
    del workspace, python_exe
    reasons: list[str] = []
    answer = result.get("final_answer", "")
    if changes:
        reasons.append(f"unexpected file changes: {changes}")
    if "shell_execute" in tool_names(result):
        reasons.append("shell was used despite the no-command constraint")
    if WRITE_TOOLS & set(tool_names(result)):
        reasons.append("write/edit tool was used despite read-only constraint")
    if is_meaningless_answer(answer):
        reasons.append("final answer was empty or meaningless")
    if "zerodivisionerror" not in answer.lower() and "除" not in answer:
        reasons.append("answer did not explain the division-by-zero cause")
    if result.get("finish_reason", "normal") not in {"normal", "auditor_blocked"}:
        reasons.append(f"unexpected finish_reason: {result.get('finish_reason')}")
    return reasons


EVALUATORS: dict[str, Callable[[Path, dict[str, Any], list[str], str], list[str]]] = {
    "code_understanding": evaluate_code_understanding,
    "code_location": evaluate_code_location,
    "single_file_edit": evaluate_single_file_edit,
    "bug_fix": evaluate_bug_fix,
    "intent_constraint": evaluate_intent_constraint,
}


async def run_eval_case(
    case: EvalCase,
    run_index: int,
    args: argparse.Namespace,
) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix=f"minicode_eval_{case.case_id}_") as tmp:
        workspace = Path(tmp)
        write_case_files(workspace, case)
        before = workspace_hashes(workspace)

        if args.provider == "mock":
            llm = HarnessMockLLM(case.case_id, args.python_exe)
        else:
            from config.llm import create_llm

            llm = create_llm()

        started = time.perf_counter()
        error_message = ""
        result: dict[str, Any]

        try:
            agent = ClaudeCodeMini(
                workspace_path=str(workspace),
                llm=llm,
                mode=case.mode,
                max_iterations=args.max_iters,
                max_retries_per_step=args.max_retries,
                verbose=False,
                memory_enabled=False,
                context_max_tokens=args.context_max_tokens,
            )
            result = await asyncio.wait_for(agent.run(case.task), timeout=args.timeout)
        except asyncio.TimeoutError:
            result = {
                "success": False,
                "final_answer": "",
                "phase": "error",
                "finish_reason": "timeout",
                "tool_history": [],
                "iteration": 0,
            }
            error_message = f"Timed out after {args.timeout}s"
        except Exception as exc:
            result = {
                "success": False,
                "final_answer": "",
                "phase": "error",
                "finish_reason": "exception",
                "tool_history": [],
                "iteration": 0,
            }
            error_message = str(exc)

        duration = time.perf_counter() - started
        after = workspace_hashes(workspace)
        changes = changed_files(before, after)

        reasons: list[str] = []
        if error_message:
            reasons.append(error_message)

        allowed = set(case.allowed_changed)
        unauthorized = [path for path in changes if path not in allowed]
        if allowed and unauthorized:
            reasons.append(f"unauthorized changes: {unauthorized}")
        for protected in case.protected_unchanged:
            if protected in changes:
                reasons.append(f"protected file changed: {protected}")

        if result.get("phase") != "done":
            reasons.append(f"agent phase was {result.get('phase')}")

        if is_meaningless_answer(result.get("final_answer", "")):
            reasons.append("final answer was empty or meaningless")

        evaluator = EVALUATORS[case.category]
        reasons.extend(evaluator(workspace, result, changes, args.python_exe))

        tool_history = result.get("tool_history", [])
        answer_preview = (
            result.get("final_answer", "")[:300]
            if args.provider == "mock"
            else "[omitted for real-model report privacy]"
        )

        return {
            "case_id": case.case_id,
            "category": case.category,
            "description": case.description,
            "run_index": run_index,
            "mode": case.mode,
            "success": len(reasons) == 0,
            "failure_reasons": reasons,
            "tool_call_count": len(tool_history),
            "tools_used": tool_names(result),
            "iteration": result.get("iteration", 0),
            "duration_seconds": round(duration, 3),
            "changed_files": changes,
            "unauthorized_file_modifications": unauthorized,
            "protected_modified": [
                path for path in case.protected_unchanged if path in changes
            ],
            "finish_reason": result.get("finish_reason", "normal"),
            "phase": result.get("phase", ""),
            "abnormal_termination": result.get("phase") != "done"
            or result.get("finish_reason") in {"timeout", "exception"},
            "meaningless_final_answer": is_meaningless_answer(
                result.get("final_answer", "")
            ),
            "final_answer_preview": answer_preview,
        }


def aggregate_results(runs: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(runs)
    successes = sum(1 for run in runs if run["success"])
    abnormal = sum(1 for run in runs if run["abnormal_termination"])
    meaningless = sum(1 for run in runs if run["meaningless_final_answer"])
    unauthorized = sum(
        1 for run in runs if run["unauthorized_file_modifications"]
    )
    success_runs = [run for run in runs if run["success"]]

    def avg(key: str, source: list[dict[str, Any]] = runs) -> float:
        if not source:
            return 0.0
        return round(sum(float(run.get(key, 0)) for run in source) / len(source), 3)

    per_case: dict[str, dict[str, Any]] = {}
    for run in runs:
        entry = per_case.setdefault(
            run["case_id"],
            {"runs": 0, "successes": 0, "success_rate": 0.0},
        )
        entry["runs"] += 1
        if run["success"]:
            entry["successes"] += 1

    for entry in per_case.values():
        entry["success_rate"] = round(entry["successes"] / entry["runs"], 4)

    return {
        "total_runs": total,
        "success_count": successes,
        "success_rate": round(successes / total, 4) if total else 0.0,
        "abnormal_termination_count": abnormal,
        "abnormal_termination_rate": round(abnormal / total, 4) if total else 0.0,
        "unauthorized_file_modification_runs": unauthorized,
        "meaningless_final_answer_runs": meaningless,
        "avg_tool_calls": avg("tool_call_count"),
        "avg_successful_task_tool_calls": avg("tool_call_count", success_runs),
        "avg_iterations": avg("iteration"),
        "avg_duration_seconds": avg("duration_seconds"),
        "per_case": per_case,
        "token_usage": "unsupported by current Agent result schema",
    }


def markdown_report(report: dict[str, Any]) -> str:
    aggregate = report["aggregate"]
    lines = [
        f"# MiniCode Smoke Evaluation Report: {report['report_name']}",
        "",
        f"- Generated at: {report['generated_at']}",
        f"- Provider: {report['config']['provider']}",
        f"- Model/config: {report['config']['model_config']}",
        f"- Formal real-model evaluation executed: {report['formal_real_model_eval_executed']}",
        f"- Total runs: {aggregate['total_runs']}",
        f"- Success: {aggregate['success_count']}/{aggregate['total_runs']} "
        f"({aggregate['success_rate']:.2%})",
        f"- Abnormal terminations: {aggregate['abnormal_termination_count']} "
        f"({aggregate['abnormal_termination_rate']:.2%})",
        f"- Average tool calls: {aggregate['avg_tool_calls']}",
        f"- Average iterations: {aggregate['avg_iterations']}",
        f"- Average duration seconds: {aggregate['avg_duration_seconds']}",
        f"- Token usage: {aggregate['token_usage']}",
        "",
        "## Per-Case Results",
        "",
        "| Case | Runs | Successes | Success Rate |",
        "| --- | ---: | ---: | ---: |",
    ]
    for case_id, data in aggregate["per_case"].items():
        lines.append(
            f"| {case_id} | {data['runs']} | {data['successes']} | "
            f"{data['success_rate']:.2%} |"
        )

    lines.extend([
        "",
        "## Notes",
        "",
        "- The default mock provider validates the Harness, graph, and tool plumbing; "
        "it is not a real-model capability score.",
        "- No real API keys, model responses, or temporary workspaces are stored.",
        "- Real-model formal evaluation should be run with `--provider configured` "
        "after the desired `.env` provider is configured.",
    ])

    failures = [run for run in report["runs"] if not run["success"]]
    if failures:
        lines.extend(["", "## Failures", ""])
        for run in failures:
            lines.append(
                f"- {run['case_id']} run {run['run_index']}: "
                f"{'; '.join(run['failure_reasons'])}"
            )
    return "\n".join(lines) + "\n"


def comparison_markdown() -> str:
    return (
        "# Baseline Comparison\n\n"
        "Actual Harness baseline-vs-develop evaluation was not executed because "
        "the `baseline` tag predates the new `benchmarks/smoke_eval.py` Harness "
        "and does not expose the same evaluation entry point. No fake "
        "`baseline.json` or `improved.json` files were created.\n\n"
        "Regression data from the verified development work is available:\n\n"
        "| Checkpoint | Result |\n"
        "| --- | --- |\n"
        "| Before reliability fixes | 320/323 tests passed |\n"
        "| After reliability fixes | 336/336 tests passed |\n\n"
        "Use the new Harness for future comparable runs by executing the same "
        "command and model configuration on both revisions.\n"
    )


async def run_all(args: argparse.Namespace) -> dict[str, Any]:
    settings.memory_enabled = False
    settings.intent_auditor_enabled = False
    settings.auditor_two_layer = False

    cases = build_cases()
    runs: list[dict[str, Any]] = []
    for index in range(args.runs_per_case):
        for case in cases:
            runs.append(await run_eval_case(case, index + 1, args))

    provider_config = {
        "provider": args.provider,
        "model_config": (
            "mock-scripted-llm"
            if args.provider == "mock"
            else {
                "llm_provider": settings.llm_provider,
                "openai_model": settings.openai_model,
                "openai_api_base": settings.openai_api_base,
                "anthropic_model": settings.anthropic_model,
            }
        ),
        "mode_per_case": {case.case_id: case.mode for case in cases},
        "temperature": 0.0,
        "max_iterations": args.max_iters,
        "max_retries": args.max_retries,
        "context_max_tokens": args.context_max_tokens,
        "timeout_seconds": args.timeout,
        "memory_enabled": False,
        "intent_auditor_enabled": False,
        "system_prompt_version": "current repository prompts",
    }

    return {
        "report_name": args.report_name,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "formal_real_model_eval_executed": args.provider != "mock",
        "config": provider_config,
        "task_classes": [
            {
                "case_id": case.case_id,
                "category": case.category,
                "description": case.description,
                "mode": case.mode,
            }
            for case in cases
        ],
        "aggregate": aggregate_results(runs),
        "runs": runs,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run MiniCode smoke evaluation.")
    parser.add_argument(
        "--provider",
        choices=["mock", "configured"],
        default="mock",
        help="mock validates Harness plumbing; configured uses config.llm.create_llm().",
    )
    parser.add_argument("--runs-per-case", type=int, default=3)
    parser.add_argument("--timeout", type=int, default=45)
    parser.add_argument("--max-iters", type=int, default=8)
    parser.add_argument("--max-retries", type=int, default=1)
    parser.add_argument("--context-max-tokens", type=int, default=20000)
    parser.add_argument("--python-exe", default=sys.executable)
    parser.add_argument("--out-dir", default="benchmarks/reports")
    parser.add_argument("--report-name", default="mock_smoke")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    report = asyncio.run(run_all(args))
    json_path = out_dir / f"{args.report_name}.json"
    md_path = out_dir / f"{args.report_name}.md"
    comparison_path = out_dir / "comparison.md"

    json_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    md_path.write_text(markdown_report(report), encoding="utf-8")
    comparison_path.write_text(comparison_markdown(), encoding="utf-8")

    aggregate = report["aggregate"]
    print(
        f"{aggregate['success_count']}/{aggregate['total_runs']} runs passed; "
        f"report: {json_path.as_posix()}"
    )
    return 0 if aggregate["success_count"] == aggregate["total_runs"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
