"""项目范围内的编码代理，带有本地文件工具。

此示例为模型提供了检查和编辑此仓库的工具。
所有路径都被限制在项目根目录内。写入和 shell 命令需要在终端中
交互式确认，并且写入前会先在 ``.cubepi-backups`` 下创建带时间戳的备份。

从任意目录运行:

    export CUBEPI_PROVIDER=deepseek
    export DEEPSEEK_API_KEY=...
    uv run python examples/coding_agent.py

该代理刻意不是不受限制的计算机控制代理。仅在审查了对你的机器的
安全影响之后，再扩展该策略。
"""

from __future__ import annotations

import asyncio
import os
import shlex
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

from cubepi import Agent, AgentToolResult, TextContent, tool

try:
    from ._provider import MODEL_ID, provider
except ImportError:
    from _provider import MODEL_ID, provider

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKUP_ROOT = PROJECT_ROOT / ".cubepi-backups"
BLOCKED_NAMES = {".env", ".env.local", ".env.production"}
BLOCKED_PARTS = {".git", ".venv", "__pycache__"}
COMMANDS_REQUIRING_CONFIRMATION = {"git", "python", "pytest", "ruff", "uv"}
READ_ONLY_COMMANDS = {
    ("pwd",),
    ("ls",),
    ("git", "status"),
    ("git", "diff"),
    ("git", "log"),
}
ALLOWED_COMMANDS = COMMANDS_REQUIRING_CONFIRMATION | {
    command[0] for command in READ_ONLY_COMMANDS
}
SHELL_SYNTAX_MARKERS = ("&&", "||", ";", "|", ">", "<", "`", "$(")
MAX_COMMAND_OUTPUT = 12000


def _resolve_path(relative_path: str) -> Path:
    candidate = (PROJECT_ROOT / relative_path).resolve()
    try:
        candidate.relative_to(PROJECT_ROOT)
    except ValueError as exc:
        raise ValueError("path must stay inside the project root") from exc
    if any(part in BLOCKED_PARTS for part in candidate.relative_to(PROJECT_ROOT).parts):
        raise ValueError("access to this project path is blocked")
    if candidate.name in BLOCKED_NAMES or "key" in candidate.name.lower():
        raise ValueError("possible secret file access is blocked")
    return candidate


def _confirm(prompt: str) -> bool:
    answer = input(f"\n[approval required] {prompt} [y/N] ").strip().lower()
    return answer in {"y", "yes"}


def _text_result(text: str, *, is_error: bool = False) -> AgentToolResult:
    return AgentToolResult(content=[TextContent(text=text)], is_error=is_error)


def _command_is_read_only(parts: list[str]) -> bool:
    """Return true only for exact, intentionally small read-only commands."""
    return tuple(parts) in READ_ONLY_COMMANDS


def _command_syntax_error(command: str) -> str | None:
    """Reject shell syntax because this tool deliberately uses shell=False."""
    for marker in SHELL_SYNTAX_MARKERS:
        if marker in command:
            return (
                f"unsupported shell syntax {marker!r}; call one command at a "
                "time without pipes, redirects, substitutions, or command chaining"
            )
    return None


@tool
async def list_files(path: str = ".") -> str:
    """List files and directories below a project-relative path."""
    root = _resolve_path(path)
    if not root.exists():
        raise ValueError(f"path does not exist: {path}")
    if root.is_file():
        return str(root.relative_to(PROJECT_ROOT))
    entries = []
    for child in sorted(root.iterdir()):
        if child.name in BLOCKED_PARTS or child.name in BLOCKED_NAMES:
            continue
        suffix = "/" if child.is_dir() else ""
        entries.append(f"{child.relative_to(PROJECT_ROOT)}{suffix}")
    return "\n".join(entries) or "<empty directory>"


@tool
async def read_file(path: str, start_line: int = 1, end_line: int = 400) -> str:
    """Read a UTF-8 text file using one-based inclusive line numbers."""
    file_path = _resolve_path(path)
    if not file_path.is_file():
        raise ValueError(f"not a file: {path}")
    if start_line < 1 or end_line < start_line or end_line - start_line > 2000:
        raise ValueError("invalid line range; use at most 2001 lines")
    lines = file_path.read_text(encoding="utf-8").splitlines()
    selected = lines[start_line - 1 : end_line]
    return "\n".join(
        f"{number}: {line}" for number, line in enumerate(selected, start=start_line)
    )


@tool
async def search_files(query: str, path: str = ".") -> str:
    """Search text files below a project-relative path."""
    root = _resolve_path(path)
    if not root.exists():
        raise ValueError(f"path does not exist: {path}")
    matches: list[str] = []
    candidates = [root] if root.is_file() else root.rglob("*")
    for candidate in candidates:
        if not candidate.is_file():
            continue
        try:
            lines = candidate.read_text(encoding="utf-8").splitlines()
        except (UnicodeDecodeError, OSError):
            continue
        for number, line in enumerate(lines, start=1):
            if query.lower() in line.lower():
                matches.append(
                    f"{candidate.relative_to(PROJECT_ROOT)}:{number}: {line}"
                )
                if len(matches) >= 100:
                    return "\n".join(matches) + "\n<results truncated>"
    return "\n".join(matches) or "<no matches>"


def _backup(file_path: Path) -> Path | None:
    if not file_path.exists():
        return None
    relative = file_path.relative_to(PROJECT_ROOT)
    backup = BACKUP_ROOT / datetime.now().strftime("%Y%m%d-%H%M%S-%f") / relative
    backup.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(file_path, backup)
    return backup


@tool
async def write_file(path: str, content: str) -> str:
    """Write a UTF-8 text file after terminal confirmation, with a backup."""
    file_path = _resolve_path(path)
    if not _confirm(f"Allow the agent to write {path!r}?"):
        return "write denied by user"
    backup = _backup(file_path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(content, encoding="utf-8")
    backup_text = f" Backup: {backup.relative_to(PROJECT_ROOT)}." if backup else ""
    return f"wrote {path}.{backup_text}"


@tool
async def replace_in_file(path: str, old_text: str, new_text: str) -> str:
    """Replace one exact text occurrence in a file after confirmation."""
    file_path = _resolve_path(path)
    content = file_path.read_text(encoding="utf-8")
    count = content.count(old_text)
    if count != 1:
        raise ValueError(f"expected exactly one match, found {count}")
    if not _confirm(f"Allow the agent to edit {path!r}?"):
        return "edit denied by user"
    backup = _backup(file_path)
    file_path.write_text(content.replace(old_text, new_text), encoding="utf-8")
    return f"edited {path}; backup at {backup.relative_to(PROJECT_ROOT)}"


@tool
async def run_command(
    command: str,
    description: str = "",
    timeout_seconds: int = 120,
) -> str:
    """Run one development command with conservative permission checks.

    The command is executed without a shell. A small exact allowlist of
    read-only commands skips confirmation; all other allowed commands require
    confirmation. Shell chaining and redirection are rejected explicitly.
    """
    syntax_error = _command_syntax_error(command)
    if syntax_error:
        raise ValueError(syntax_error)
    parts = shlex.split(command)
    if not parts or parts[0] not in ALLOWED_COMMANDS:
        allowed = ", ".join(sorted(ALLOWED_COMMANDS))
        raise ValueError(f"command must start with one of: {allowed}")
    if timeout_seconds < 1 or timeout_seconds > 600:
        raise ValueError("timeout_seconds must be between 1 and 600")
    if not _command_is_read_only(parts) and not _confirm(
        f"Allow the agent to run {command!r} in the project root?"
        + (f" ({description})" if description else "")
    ):
        return "command denied by user"
    env = os.environ.copy()
    for name in list(env):
        upper_name = name.upper()
        if any(
            marker in upper_name
            for marker in ("KEY", "TOKEN", "SECRET", "PASSWORD", "CREDENTIAL")
        ):
            env.pop(name, None)
    try:
        completed = await asyncio.to_thread(
            subprocess.run,
            parts,
            cwd=PROJECT_ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return f"command timed out after {timeout_seconds}s: {command}\n{exc}"
    output = (completed.stdout + completed.stderr).strip()
    result = f"exit code: {completed.returncode}\n{output}"
    if len(result) > MAX_COMMAND_OUTPUT:
        result = result[:MAX_COMMAND_OUTPUT] + "\n<output truncated>"
    return result


async def main() -> None:
    agent = Agent(
        model=provider.model(MODEL_ID),
        system_prompt=(
            f"You are a coding agent operating only in {PROJECT_ROOT}. "
            "Inspect files before editing. Explain the intended change, use "
            "replace_in_file for focused edits, and run a relevant check after "
            "editing. Never claim a change succeeded unless a tool confirms it."
        ),
        tools=[
            list_files,
            read_file,
            search_files,
            write_file,
            replace_in_file,
            run_command,
        ],
    )

    def on_event(event, signal=None):
        if event.type == "message_update" and event.stream_event.type == "text_delta":
            print(event.stream_event.delta, end="", flush=True)
        elif event.type == "tool_execution_start":
            print(f"\n[tool: {event.tool_name}]", flush=True)
        elif event.type == "agent_end":
            print()

    agent.subscribe(on_event)
    print(f"Coding agent root: {PROJECT_ROOT}")
    print(
        "Type a task, or press Ctrl-D to quit. File writes and commands ask for approval."
    )
    loop = asyncio.get_running_loop()
    while True:
        try:
            user_input = await loop.run_in_executor(None, input, "you> ")
        except EOFError:
            print()
            return
        if not user_input.strip():
            continue
        print("ai > ", end="", flush=True)
        await agent.prompt(user_input)


if __name__ == "__main__":
    asyncio.run(main())
