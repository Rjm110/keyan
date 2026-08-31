"""文件系统工具集：baseline 代码的读取与修改。

安全模式参考 examples/coding_agent.py：
- 路径沙箱：所有路径限制在 workspace 根目录内（_resolve_path）
- 敏感文件黑名单：.env、含 key 的文件名、.git/.venv/__pycache__ 等
- 写前备份：写入前在 backups 目录创建带时间戳的副本

与 coding_agent.py 的差异：
- 确认逻辑不在工具内（终端 input），而是由 ConfirmToolCallMiddleware
  在工具执行前拦截（Web 场景弹窗确认），因此 write_file/replace_in_file
  本身不弹确认。
"""

from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

from cubepi import AgentToolResult, TextContent, tool

BLOCKED_NAMES = {".env", ".env.local", ".env.production"}
BLOCKED_PARTS = {".git", ".venv", "__pycache__", "node_modules"}
MAX_READ_LINES = 2001
MAX_SEARCH_RESULTS = 100


def _text_result(text: str, *, is_error: bool = False) -> AgentToolResult:
    return AgentToolResult(content=[TextContent(text=text)], is_error=is_error)


def _resolve_path(workspace_root: Path, relative_path: str) -> Path:
    """把相对路径解析为 workspace 内的绝对路径，越界/敏感路径抛 ValueError。"""
    candidate = (workspace_root / relative_path).resolve()
    try:
        candidate.relative_to(workspace_root)
    except ValueError as exc:
        raise ValueError("path must stay inside the workspace root") from exc
    rel = candidate.relative_to(workspace_root)
    if any(part in BLOCKED_PARTS for part in rel.parts):
        raise ValueError("access to this workspace path is blocked")
    if candidate.name in BLOCKED_NAMES or "key" in candidate.name.lower():
        raise ValueError("possible secret file access is blocked")
    return candidate


def _backup(backups_dir: Path, workspace_root: Path, file_path: Path) -> Path | None:
    """写入前备份：复制到 backups/<时间戳>/<相对路径>。"""
    if not file_path.exists():
        return None
    relative = file_path.relative_to(workspace_root)
    backup = backups_dir / datetime.now().strftime("%Y%m%d-%H%M%S-%f") / relative
    backup.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(file_path, backup)
    return backup


def make_fs_tools(workspace_root: Path, backups_dir: Path) -> list:
    """创建文件系统工具集（闭包注入 workspace 根目录与备份目录）。

    返回 list[AgentTool]，可直接传给 Agent(tools=[...])。
    """
    root = workspace_root.resolve()
    backups = backups_dir.resolve()

    def resolve(relative_path: str) -> Path:
        return _resolve_path(root, relative_path)

    @tool
    async def list_files(path: str = ".") -> str:
        """List files and directories below a workspace-relative path."""
        target = resolve(path)
        if not target.exists():
            raise ValueError(f"path does not exist: {path}")
        if target.is_file():
            return str(target.relative_to(root))
        entries = []
        for child in sorted(target.iterdir()):
            if child.name in BLOCKED_PARTS or child.name in BLOCKED_NAMES:
                continue
            suffix = "/" if child.is_dir() else ""
            entries.append(f"{child.relative_to(root)}{suffix}")
        return "\n".join(entries) or "<empty directory>"

    @tool
    async def read_file(path: str, start_line: int = 1, end_line: int = 400) -> str:
        """Read a UTF-8 text file using one-based inclusive line numbers."""
        file_path = resolve(path)
        if not file_path.is_file():
            raise ValueError(f"not a file: {path}")
        if start_line < 1 or end_line < start_line or end_line - start_line > 2000:
            raise ValueError("invalid line range; use at most 2001 lines")
        lines = file_path.read_text(encoding="utf-8").splitlines()
        selected = lines[start_line - 1 : end_line]
        return "\n".join(
            f"{number}: {line}"
            for number, line in enumerate(selected, start=start_line)
        )

    @tool
    async def search_files(query: str, path: str = ".") -> str:
        """Search text files below a workspace-relative path (case-insensitive)."""
        target = resolve(path)
        if not target.exists():
            raise ValueError(f"path does not exist: {path}")
        matches: list[str] = []
        candidates = [target] if target.is_file() else target.rglob("*")
        for candidate in candidates:
            if not candidate.is_file():
                continue
            try:
                lines = candidate.read_text(encoding="utf-8").splitlines()
            except (UnicodeDecodeError, OSError):
                continue
            for number, line in enumerate(lines, start=1):
                if query.lower() in line.lower():
                    matches.append(f"{candidate.relative_to(root)}:{number}: {line}")
                    if len(matches) >= MAX_SEARCH_RESULTS:
                        return "\n".join(matches) + "\n<results truncated>"
        return "\n".join(matches) or "<no matches>"

    @tool
    async def write_file(path: str, content: str) -> str:
        """Write a UTF-8 text file (backup created first; approval handled by middleware)."""
        file_path = resolve(path)
        backup = _backup(backups, root, file_path)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding="utf-8")
        backup_text = f" Backup: {backup.relative_to(root)}." if backup else ""
        return f"wrote {path}.{backup_text}"

    @tool
    async def replace_in_file(path: str, old_text: str, new_text: str) -> str:
        """Replace exactly one occurrence of old_text with new_text in a file."""
        file_path = resolve(path)
        if not file_path.is_file():
            raise ValueError(f"not a file: {path}")
        content = file_path.read_text(encoding="utf-8")
        count = content.count(old_text)
        if count != 1:
            raise ValueError(f"expected exactly one match, found {count}")
        backup = _backup(backups, root, file_path)
        file_path.write_text(content.replace(old_text, new_text), encoding="utf-8")
        backup_text = f" Backup: {backup.relative_to(root)}." if backup else ""
        return f"edited {path}.{backup_text}"

    return [list_files, read_file, search_files, write_file, replace_in_file]
