"""会话（conversation）数据访问层。

基于 cubepi 的 Checkpointer 协议封装会话 CRUD：
- list_threads()  — 列出所有会话摘要（按更新时间倒序）
- create()       — 懒创建：仅当第一条消息写入时才真正落库
- update_title() — 更新会话标题（写入 thread_extra.extra_json["title"]）
- load_messages()— 读取会话历史消息
- delete()       — 删除会话及其全部数据

thread_id 格式：`{user_id}:{conversation_id}`（多用户隔离）。
"""

from __future__ import annotations

from typing import Any

from cubepi.checkpointer.base import Checkpointer, ThreadSummary


class ConversationRepository:
    """封装 Checkpointer 的会话 CRUD。"""

    def __init__(self, checkpointer: Checkpointer) -> None:
        self._checkpointer = checkpointer

    async def list_threads(self) -> list[ThreadSummary]:
        """列出所有会话摘要，按更新时间倒序。"""
        return await self._checkpointer.list_threads()

    async def create(self, thread_id: str) -> None:
        """懒创建会话。

        不立即写库——第一条消息 append 时 Checkpointer 会自动建 thread。
        这里保留方法是为了语义完整（后续可扩展预建标题等）。
        """
        # 无操作：Checkpointer.append 会自动创建 thread
        return None

    async def update_title(self, thread_id: str, title: str) -> None:
        """更新会话标题（写入 extra_json["title"]）。"""
        await self._checkpointer.save_extra(thread_id, {"title": title})

    async def load_messages(self, thread_id: str) -> list[Any]:
        """读取会话历史消息（原始 Message 对象列表）。"""
        data = await self._checkpointer.load(thread_id)
        if data is None:
            return []
        return list(data.messages)

    async def delete(self, thread_id: str) -> None:
        """删除会话及其全部数据（消息、标题、pending、answers、runs）。"""
        await self._checkpointer.delete_thread(thread_id)
