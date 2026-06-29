"""ShellTool — execute shell commands in the workspace."""

import asyncio
import platform
import re
from tools.base import BaseTool, ToolResult
from runtime.shell_platform import get_shell_environment

_SHELL_BASE_DESCRIPTION = (
    "Execute a shell command in the workspace directory and return its output "
    "(stdout and stderr combined). "
    "Use this tool to: run tests, install packages, start/stop servers, "
    "run git commands, check file properties, or any other command-line operation. "
    "Commands have a timeout to prevent hanging — avoid commands that run "
    "indefinitely (like starting a server without backgrounding). "
    "The command's working directory is already the workspace root."
)


_HIGH_RISK_PATTERNS: list[tuple[re.Pattern, str]] = [
    (
        re.compile(r"\brm\s+.*-(?:[a-z]*r[a-z]*f|[a-z]*f[a-z]*r)\b"),
        "recursive forced deletion with rm",
    ),
    (
        re.compile(r"\b(?:rmdir|rd)\s+.*(?:/s\b|-[a-z]*r)"),
        "recursive directory deletion",
    ),
    (
        re.compile(r"\b(?:del|erase)\s+.*(?:/s\b|-[a-z]*r)"),
        "recursive file deletion",
    ),
    (re.compile(r"\bformat(?:\.com)?\b"), "disk formatting command"),
    (re.compile(r"\bmkfs(?:\.|\s|$)"), "filesystem creation command"),
    (re.compile(r"\bdiskpart\b"), "disk partitioning command"),
    (re.compile(r"\bdd\s+if="), "raw disk copy command"),
    (re.compile(r":\(\)\s*\{\s*:\|:&\s*\};:"), "recursive shell process bomb"),
    (re.compile(r"\b(?:shutdown|reboot)\b"), "system shutdown/reboot command"),
    (re.compile(r"\bgit\s+reset\s+--hard\b"), "destructive git reset"),
    (
        re.compile(r"\bgit\s+clean\s+.*(?:-fd[a-z]*|-df[a-z]*|-f\s+-d|-d\s+-f)\b"),
        "destructive git clean",
    ),
    (
        re.compile(r"\bgit\s+push\s+.*(?:--force|-f\b)"),
        "forced git push",
    ),
    (
        re.compile(
            r"\b(?:rm|del|erase|rmdir|rd|remove-item)\b.*"
            r"(?:\.\.|[a-z]:\\|/(?:etc|bin|usr|var|home|root)\b|"
            r"\\(?:windows|system32)\b)"
        ),
        "deletion target appears outside the workspace",
    ),
    (
        re.compile(
            r"\b(?:curl|wget|iwr|invoke-webrequest)\b.*(?:\||&&|;).*"
            r"\b(?:bash|sh|powershell|pwsh|cmd|iex|invoke-expression)\b"
        ),
        "downloaded content is executed directly",
    ),
    (
        re.compile(r"\b(?:iex|invoke-expression)\b"),
        "PowerShell Invoke-Expression execution",
    ),
    (
        re.compile(r"\bremove-item\b.*(?:-recurse|/s).*(?:-force|/q)"),
        "forced recursive PowerShell deletion",
    ),
]

_MEDIUM_RISK_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\b(?:mkdir|md)\b"), "creates directories"),
    (re.compile(r"\b(?:copy|cp|xcopy|robocopy)\b"), "copies files"),
    (re.compile(r"\b(?:move|mv)\b"), "moves files"),
    (re.compile(r"\bgit\s+add\b"), "stages git changes"),
    (
        re.compile(r"\b(?:pip|python\s+-m\s+pip)\s+install\b"),
        "installs Python packages",
    ),
    (re.compile(r"\bnpm\s+install\b"), "installs Node packages"),
]

_LOW_RISK_PATTERNS: list[re.Pattern] = [
    re.compile(r"^(?:dir|ls|pwd|cd|type|cat|echo|where|whoami)(?:\s|$)"),
    re.compile(r"^(?:python|py|[\w:./\\ -]*python\.exe)\s+-m\s+py_compile\b"),
    re.compile(r"^(?:python|py|[\w:./\\ -]*python\.exe)\s+--version\b"),
    re.compile(
        r"^(?:pytest|python\s+-m\s+pytest|[\w:./\\ -]*python\.exe\s+-m\s+pytest)\b"
    ),
    re.compile(r"^git\s+(?:status|diff)(?:\s|$)"),
]


def _normalize_command(command: str) -> str:
    """Normalize shell text for lightweight risk checks."""
    text = (command or "").strip().lower()
    text = text.replace("`", "").replace("^", "")
    return re.sub(r"\s+", " ", text)


def _strip_common_wrapper(command: str) -> str:
    """Expose the inner command for simple cmd/powershell wrappers."""
    text = command.strip()
    changed = True
    while changed:
        changed = False

        cmd_match = re.match(r"^cmd(?:\.exe)?\s+/[cs]\s+(.+)$", text)
        if cmd_match:
            text = cmd_match.group(1).strip().strip("\"'")
            changed = True
            continue

        ps_match = re.match(
            r"^(?:powershell|powershell\.exe|pwsh|pwsh\.exe)\s+(.+)$",
            text,
        )
        if ps_match:
            rest = ps_match.group(1).strip()
            command_match = re.search(r"(?:-command|-c)\s+(.+)$", rest)
            if command_match:
                text = command_match.group(1).strip().strip("\"'")
                changed = True

    return text


def classify_shell_command(command: str) -> dict:
    """Classify a command as low, medium, or high risk."""
    normalized = _normalize_command(command)
    unwrapped = _strip_common_wrapper(normalized)
    check_text = f"{normalized} {unwrapped}".strip()

    if not normalized:
        return {"risk_level": "low", "allowed": True, "blocked_reason": ""}

    for pattern, reason in _HIGH_RISK_PATTERNS:
        if pattern.search(check_text):
            return {
                "risk_level": "high",
                "allowed": False,
                "blocked_reason": f"Blocked high-risk shell command: {reason}.",
            }

    for pattern, reason in _MEDIUM_RISK_PATTERNS:
        if pattern.search(unwrapped):
            return {
                "risk_level": "medium",
                "allowed": True,
                "blocked_reason": "",
                "risk_reason": reason,
            }

    segments = [
        part.strip()
        for part in re.split(r"\s*(?:&&|\|\||;|&|\|)\s*", unwrapped)
        if part.strip()
    ]
    if segments and all(
        any(pattern.search(segment) for pattern in _LOW_RISK_PATTERNS)
        for segment in segments
    ):
        return {"risk_level": "low", "allowed": True, "blocked_reason": ""}

    return {
        "risk_level": "medium",
        "allowed": True,
        "blocked_reason": "",
        "risk_reason": "unrecognized shell command; allowed with medium-risk metadata",
    }


class ShellTool(BaseTool):
    """Execute shell commands and capture output.

    This is how the Agent installs dependencies, runs tests, starts servers,
    and performs any operation that requires the command line.
    """

    name = "shell_execute"
    parameters = {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "The shell command to execute.",
            },
            "timeout": {
                "type": "integer",
                "description": "Timeout in seconds (default: 60, max: 300).",
            },
        },
        "required": ["command"],
    }

    def __init__(self, workspace):
        self._workspace = workspace
        self._shell_env = get_shell_environment()
        self.description = (
            _SHELL_BASE_DESCRIPTION + self._shell_env.tool_description_suffix
        )

    async def execute(self, command: str, timeout: int = 60) -> ToolResult:
        try:
            risk = classify_shell_command(command)
            if not risk["allowed"]:
                return ToolResult(
                    success=False,
                    error=risk["blocked_reason"],
                    metadata={
                        "risk_level": risk["risk_level"],
                        "allowed": False,
                        "blocked_reason": risk["blocked_reason"],
                    },
                )

            # Apply timeout cap
            timeout = min(max(timeout, 1), 300)

            cwd = self._workspace.root_str
            if self._shell_env.is_windows:
                process = await asyncio.create_subprocess_shell(
                    command,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=cwd,
                )
            else:
                process = await asyncio.create_subprocess_shell(
                    command,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=cwd,
                    executable="/bin/bash",
                )

            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    process.communicate(), timeout=timeout
                )
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
                return ToolResult(
                    success=False,
                    error=f"Command timed out after {timeout}s: {command[:80]}...",
                    metadata={"timeout": timeout, "exit_code": None},
                )

            stdout = stdout_bytes.decode("utf-8", errors="replace").strip()
            stderr = stderr_bytes.decode("utf-8", errors="replace").strip()

            exit_code = process.returncode

            # Combine stdout and stderr
            parts = []
            if stdout:
                parts.append(stdout)
            if stderr:
                parts.append(f"[stderr]\n{stderr}")

            output = "\n".join(parts) if parts else "(no output)"

            success = exit_code == 0
            status = "OK" if success else f"FAIL (exit={exit_code})"

            return ToolResult(
                success=success,
                output=f"[{status}] {command}\n{output}",
                metadata={
                    "risk_level": risk["risk_level"],
                    "allowed": True,
                    "blocked_reason": "",
                    "exit_code": exit_code,
                    "stdout_len": len(stdout_bytes),
                    "stderr_len": len(stderr_bytes),
                    "shell": self._shell_env.shell_name,
                    "platform": platform.system(),
                },
            )

        except ValueError as e:
            return ToolResult(success=False, error=str(e))
        except Exception as e:
            return ToolResult(
                success=False,
                error=f"Command execution failed: {e}",
            )
