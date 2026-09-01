"""会话管理测试：列表、创建、标题生成。

覆盖：
1. ConversationService 列表（空 / 有数据）
2. 创建会话（懒创建，仅生成 ID）
3. 标题自动生成（首条消息前 20 字）
4. ConversationRepository 的 CRUD
"""

from __future__ import annotations

from cubepi.checkpointer.sqlite import SQLiteCheckpointer
from cubepi.providers.base import TextContent, UserMessage

from app.repositories.conversation_repo import ConversationRepository
from app.services.conversation_service import ConversationService


async def test_list_empty(tmp_path):
    """空库时列表为空。"""
    async with SQLiteCheckpointer(str(tmp_path / "s.db")) as cp:
        repo = ConversationRepository(cp)
        svc = ConversationService(repo)
        assert await svc.list_conversations() == []
        assert await svc.list_conversations(project_id="default") == []


async def test_create_conversation_lazy(tmp_path):
    """创建会话是懒创建：仅生成 ID，不落库。"""
    async with SQLiteCheckpointer(str(tmp_path / "s.db")) as cp:
        repo = ConversationRepository(cp)
        svc = ConversationService(repo)
        conv = await svc.create_conversation()
        assert conv["id"].startswith("conv_")
        assert conv["title"] == "新会话"
        assert conv["message_count"] == 0
        # 懒创建：列表仍为空
        assert await svc.list_conversations() == []


async def test_title_from_first_message(tmp_path):
    """首条消息自动生成标题（前 20 字）。"""
    async with SQLiteCheckpointer(str(tmp_path / "s.db")) as cp:
        repo = ConversationRepository(cp)
        svc = ConversationService(repo)
        thread_id = "demo-user:default:conv_abc123"
        # 先写入一条消息（模拟第一条用户消息）
        await cp.append(
            thread_id,
            [
                UserMessage(
                    content=[
                        TextContent(
                            text="这是一条很长的测试消息，用来验证标题截取逻辑是否正确"
                        )
                    ]
                )
            ],
        )
        await svc.ensure_title(
            thread_id, "这是一条很长的测试消息，用来验证标题截取逻辑是否正确"
        )
        threads = await repo.list_threads()
        assert len(threads) == 1
        assert threads[0].thread_id == thread_id
        assert (
            threads[0].title
            == "这是一条很长的测试消息，用来验证标题截取逻辑是否正确"[:20]
        )
        assert threads[0].message_count == 1


async def test_title_not_overwritten(tmp_path):
    """已有标题时不会覆盖。"""
    async with SQLiteCheckpointer(str(tmp_path / "s.db")) as cp:
        repo = ConversationRepository(cp)
        svc = ConversationService(repo)
        thread_id = "demo-user:default:conv_abc123"
        await cp.save_extra(thread_id, {"title": "已有标题"})
        await svc.ensure_title(thread_id, "新消息")
        threads = await repo.list_threads()
        assert threads[0].title == "已有标题"


async def test_update_title(tmp_path):
    """update_title 写入 extra_json。"""
    async with SQLiteCheckpointer(str(tmp_path / "s.db")) as cp:
        repo = ConversationRepository(cp)
        await repo.update_title("demo-user:default:conv_xyz", "我的标题")
        data = await cp.load("demo-user:default:conv_xyz")
        assert data is not None
        assert data.extra.get("title") == "我的标题"


async def test_load_messages(tmp_path):
    """load_messages 返回消息列表。"""
    async with SQLiteCheckpointer(str(tmp_path / "s.db")) as cp:
        repo = ConversationRepository(cp)
        thread_id = "demo-user:default:conv_abc"
        await cp.append(thread_id, [UserMessage(content=[TextContent(text="你好")])])
        msgs = await repo.load_messages(thread_id)
        assert len(msgs) == 1
        assert msgs[0].content[0].text == "你好"
        # 不存在的会话返回空
        assert await repo.load_messages("demo-user:default:none") == []


async def test_list_threads_sorted_by_updated_at(tmp_path):
    """list_threads 按更新时间倒序。"""
    async with SQLiteCheckpointer(str(tmp_path / "s.db")) as cp:
        # 先写 thread A，再写 thread B（B 更新）
        await cp.append(
            "demo-user:default:conv_a", [UserMessage(content=[TextContent(text="a1")])]
        )
        await cp.append(
            "demo-user:default:conv_b", [UserMessage(content=[TextContent(text="b1")])]
        )
        await cp.append(
            "demo-user:default:conv_b", [UserMessage(content=[TextContent(text="b2")])]
        )
        threads = await cp.list_threads()
        assert [t.thread_id for t in threads] == [
            "demo-user:default:conv_b",
            "demo-user:default:conv_a",
        ]
        assert threads[0].message_count == 2
        assert threads[1].message_count == 1


async def test_delete_conversation(tmp_path):
    """delete_conversation 删除会话及其全部数据。"""
    async with SQLiteCheckpointer(str(tmp_path / "s.db")) as cp:
        repo = ConversationRepository(cp)
        svc = ConversationService(repo)
        thread_id = "demo-user:default:conv_abc"
        await cp.append(thread_id, [UserMessage(content=[TextContent(text="你好")])])
        await svc.ensure_title(thread_id, "你好")

        await svc.delete_conversation("demo-user", "default", "conv_abc")

        assert await cp.load(thread_id) is None
        assert await svc.list_conversations() == []


async def test_delete_conversation_keeps_others(tmp_path):
    """删除一个会话不影响其他会话。"""
    async with SQLiteCheckpointer(str(tmp_path / "s.db")) as cp:
        repo = ConversationRepository(cp)
        svc = ConversationService(repo)
        await cp.append(
            "demo-user:default:conv_a", [UserMessage(content=[TextContent(text="a1")])]
        )
        await cp.append(
            "demo-user:default:conv_b", [UserMessage(content=[TextContent(text="b1")])]
        )

        await svc.delete_conversation("demo-user", "default", "conv_a")

        convs = await svc.list_conversations()
        assert [c["id"] for c in convs] == ["conv_b"]


async def test_delete_conversation_idempotent(tmp_path):
    """删除不存在的会话不报错（幂等）。"""
    async with SQLiteCheckpointer(str(tmp_path / "s.db")) as cp:
        repo = ConversationRepository(cp)
        svc = ConversationService(repo)
        await svc.delete_conversation("demo-user", "default", "conv_ghost")
        await svc.delete_conversation("demo-user", "default", "conv_ghost")


async def test_list_conversations_filtered_by_project(tmp_path):
    """list_conversations 按项目过滤。"""
    async with SQLiteCheckpointer(str(tmp_path / "s.db")) as cp:
        repo = ConversationRepository(cp)
        svc = ConversationService(repo)
        await cp.append(
            "demo-user:proj_a:conv_1", [UserMessage(content=[TextContent(text="a1")])]
        )
        await cp.append(
            "demo-user:proj_b:conv_2", [UserMessage(content=[TextContent(text="b1")])]
        )
        # 旧格式（2 段）视为 default 项目
        await cp.append(
            "demo-user:conv_3", [UserMessage(content=[TextContent(text="c1")])]
        )

        convs_a = await svc.list_conversations(project_id="proj_a")
        assert [c["id"] for c in convs_a] == ["conv_1"]
        assert convs_a[0]["project_id"] == "proj_a"

        convs_default = await svc.list_conversations(project_id="default")
        assert [c["id"] for c in convs_default] == ["conv_3"]
        assert convs_default[0]["project_id"] == "default"

        # 不传 project_id 返回全部
        all_convs = await svc.list_conversations()
        assert {c["id"] for c in all_convs} == {"conv_1", "conv_2", "conv_3"}
