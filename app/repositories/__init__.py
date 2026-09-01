"""repositories 层：数据访问（CRUD）封装。

职责：
- 只做数据读写，不包含业务逻辑
- 依赖注入：构造时传入 checkpointer（SQLiteCheckpointer 等）
- 上层（services）通过这里访问持久化数据
"""

from app.repositories.conversation_repo import ConversationRepository

__all__ = ["ConversationRepository"]
