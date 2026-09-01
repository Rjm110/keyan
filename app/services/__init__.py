"""services 层：业务逻辑。

职责：
- 编排 repositories 层，实现业务规则（标题生成、会话列表等）
- 不直接接触数据库/Checkpointer，不感知 HTTP
- 依赖注入：构造时传入 repository
"""

from app.services.chat_service import ChatService
from app.services.conversation_service import ConversationService
from app.services.workspace_service import WorkspaceService

__all__ = ["ChatService", "ConversationService", "WorkspaceService"]
