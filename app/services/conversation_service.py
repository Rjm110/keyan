"""会话业务逻辑：列表、创建、标题生成。

设计决策：
- 会话 ID 用 UUID 短格式（如 conv_8f3a2b），避免暴露自增序号
- 会话懒创建：POST /conversations 只生成 ID，第一条消息时才真正落库
- 标题自动取首条用户消息前 20 字（无消息时显示"新会话"）
- 更新时间取 messages 表 MAX(created_at)（由 Checkpointer.list_threads 提供）
- 会话归属项目：thread_id = {user_id}:{project_id}:{conversation_id}
"""

from __future__ import annotations

import re
import uuid

from app.repositories.conversation_repo import ConversationRepository
from app.repositories.project_repo import DEFAULT_PROJECT_ID

# 会话 ID 前缀（便于识别与过滤）
_CONV_PREFIX = "conv_"
# 标题截取长度
_TITLE_MAX_LEN = 20
# 标题默认值
_DEFAULT_TITLE = "新会话"


def _generate_conversation_id() -> str:
    """生成短格式会话 ID：conv_ + 6 位十六进制。"""
    return f"{_CONV_PREFIX}{uuid.uuid4().hex[:6]}"


def _title_from_text(text: str) -> str:
    """从用户消息提取标题：去空白、截断前 20 字。"""
    cleaned = re.sub(r"\s+", " ", text).strip()
    if not cleaned:
        return _DEFAULT_TITLE
    return cleaned[:_TITLE_MAX_LEN]


class ConversationService:
    """会话业务逻辑。"""

    def __init__(self, repo: ConversationRepository) -> None:
        self._repo = repo

    async def list_conversations(self, project_id: str | None = None) -> list[dict]:
        """列出会话（按更新时间倒序），供前端侧栏展示。

        project_id 为 None 时列出全部；否则只列该项目下的会话。
        旧格式 thread_id（无项目段）视为属于 default 项目。
        """
        threads = await self._repo.list_threads()
        result = []
        for t in threads:
            conv_project = _project_id_from_thread(t.thread_id)
            if project_id is not None and conv_project != project_id:
                continue
            result.append(
                {
                    "id": _strip_prefix(t.thread_id),
                    "project_id": conv_project,
                    "title": t.title or _DEFAULT_TITLE,
                    "message_count": t.message_count,
                    "updated_at": t.updated_at,
                }
            )
        return result

    async def create_conversation(self) -> dict:
        """创建新会话（懒创建：仅生成 ID，不落库）。"""
        conversation_id = _generate_conversation_id()
        return {
            "id": conversation_id,
            "title": _DEFAULT_TITLE,
            "message_count": 0,
            "updated_at": 0.0,
        }

    async def delete_conversation(
        self, user_id: str, project_id: str, conversation_id: str
    ) -> None:
        """删除会话及其全部数据（幂等）。"""
        thread_id = f"{user_id}:{project_id}:{conversation_id}"
        await self._repo.delete(thread_id)

    async def ensure_title(self, thread_id: str, first_message: str) -> None:
        """若会话尚无标题，用首条用户消息生成标题。"""
        threads = await self._repo.list_threads()
        for t in threads:
            if t.thread_id == thread_id and t.title:
                return
        title = _title_from_text(first_message)
        await self._repo.update_title(thread_id, title)


def _strip_prefix(thread_id: str) -> str:
    """从 thread_id（user_id:project_id:conversation_id）提取 conversation_id。"""
    parts = thread_id.split(":")
    return parts[-1]


def _project_id_from_thread(thread_id: str) -> str:
    """从 thread_id 提取项目 ID；旧格式（无项目段）视为 default。"""
    parts = thread_id.split(":")
    if len(parts) >= 3:
        return parts[1]
    return DEFAULT_PROJECT_ID
