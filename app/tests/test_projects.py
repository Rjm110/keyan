"""项目管理测试：CRUD、默认项目迁移、会话归属、删除级联、目录浏览。

覆盖：
1. ProjectRepository CRUD（创建 / 列表 / 重命名 / 删除）
2. ProjectService 默认项目迁移（旧 baseline 内容复制到 default）
3. 项目 = 真实路径（create 带 path，project_dir 返回真实路径）
4. 删除项目只移除记录 + 会话，**不删除磁盘代码目录**
5. thread_id 构造与项目提取
6. 目录浏览（"我的电脑"式选择器）
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

from cubepi.checkpointer.sqlite import SQLiteCheckpointer
from cubepi.providers.base import TextContent, UserMessage

from app.repositories.conversation_repo import ConversationRepository
from app.repositories.project_repo import (
    DEFAULT_PROJECT_ID,
    ProjectRepository,
)
from app.services.chat_service import ChatService
from app.services.conversation_service import ConversationService
from app.services.project_service import ProjectService


def _make_service(tmp_path) -> tuple[ProjectService, ProjectRepository]:
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir(parents=True, exist_ok=True)
    repo = ProjectRepository(projects_dir / "projects.json")
    # 同步测试不涉及会话级联，conversation_repo 传空
    svc = ProjectService(repo, projects_dir, cast(ConversationRepository, None))
    return svc, repo


def test_create_and_list(tmp_path):
    """创建项目（真实路径）后能列出，且按创建时间升序。"""
    svc, _ = _make_service(tmp_path)
    real_dir = tmp_path / "my-real-project"
    real_dir.mkdir(parents=True, exist_ok=True)
    p1 = svc.create_project("项目A", str(real_dir))
    p2 = svc.create_project("项目B", str(tmp_path))
    assert p1["id"].startswith("proj_")
    assert p1["name"] == "项目A"
    assert p1["path"] == str(real_dir.resolve())
    projects = svc.list_projects()
    assert [p["id"] for p in projects] == [p1["id"], p2["id"]]
    # project_dir 返回真实路径
    assert svc.project_dir(p1["id"]) == real_dir.resolve()


def test_create_project_requires_existing_dir(tmp_path):
    """创建项目时 path 必须为真实存在的目录。"""
    svc, _ = _make_service(tmp_path)
    import pytest

    with pytest.raises(ValueError):
        svc.create_project("不存在", str(tmp_path / "ghost"))
    # 文件路径也不行
    f = tmp_path / "a.txt"
    f.write_text("x")
    with pytest.raises(ValueError):
        svc.create_project("是文件", str(f))


def test_rename_project(tmp_path):
    """重命名项目。"""
    svc, _ = _make_service(tmp_path)
    p = svc.create_project("旧名字", str(tmp_path))
    renamed = svc.rename_project(p["id"], "新名字")
    assert renamed is not None
    assert renamed["name"] == "新名字"
    # 重命名不存在的项目返回 None
    assert svc.rename_project("proj_ghost", "x") is None


async def test_delete_project_keeps_code_dir(tmp_path):
    """删除项目：移除元数据 + 会话，**不删除磁盘代码目录**。"""
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir(parents=True, exist_ok=True)
    repo = ProjectRepository(projects_dir / "projects.json")
    async with SQLiteCheckpointer(str(tmp_path / "s.db")) as cp:
        svc = ProjectService(repo, projects_dir, ConversationRepository(cp))
        real_dir = tmp_path / "real-code"
        real_dir.mkdir(parents=True, exist_ok=True)
        (real_dir / "a.py").write_text("x = 1\n")
        p = svc.create_project("要删除", str(real_dir))
        assert await svc.delete_project("demo-user", p["id"]) is True
        # 磁盘代码目录保留！
        assert real_dir.exists() is True
        assert (real_dir / "a.py").read_text() == "x = 1\n"
        assert svc.list_projects() == []
        # 删除不存在的项目返回 False
        assert await svc.delete_project("demo-user", "proj_ghost") is False


def test_ensure_default_project_creates(tmp_path):
    """首次启动创建默认项目（指向 projects/default）。"""
    svc, _ = _make_service(tmp_path)
    svc.ensure_default_project(tmp_path / "baseline")
    projects = svc.list_projects()
    assert len(projects) == 1
    assert projects[0]["id"] == DEFAULT_PROJECT_ID
    assert projects[0]["name"] == "默认项目"
    assert projects[0]["path"] == str(
        (tmp_path / "projects" / DEFAULT_PROJECT_ID).resolve()
    )
    assert svc.project_dir(DEFAULT_PROJECT_ID).is_dir()


def test_ensure_default_project_migrates_legacy_baseline(tmp_path):
    """旧 baseline 内容迁移到 default 项目目录。"""
    svc, _ = _make_service(tmp_path)
    legacy = tmp_path / "baseline"
    legacy.mkdir(parents=True, exist_ok=True)
    (legacy / "model.py").write_text("x = 1\n")
    (legacy / "sub").mkdir()
    (legacy / "sub" / "util.py").write_text("y = 2\n")

    svc.ensure_default_project(legacy)

    target = svc.project_dir(DEFAULT_PROJECT_ID)
    assert (target / "model.py").read_text() == "x = 1\n"
    assert (target / "sub" / "util.py").read_text() == "y = 2\n"


def test_ensure_default_project_idempotent(tmp_path):
    """重复调用不重复创建/迁移。"""
    svc, _ = _make_service(tmp_path)
    legacy = tmp_path / "baseline"
    legacy.mkdir(parents=True, exist_ok=True)
    (legacy / "model.py").write_text("x = 1\n")

    svc.ensure_default_project(legacy)
    svc.ensure_default_project(legacy)

    assert len(svc.list_projects()) == 1
    # 迁移只发生一次（文件不会被覆盖成空）
    assert (svc.project_dir(DEFAULT_PROJECT_ID) / "model.py").read_text() == "x = 1\n"


def test_ensure_default_project_backfills_legacy_path(tmp_path):
    """旧数据兼容：default 项目 path 为空时补上 projects/default 路径。"""
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir(parents=True, exist_ok=True)
    repo = ProjectRepository(projects_dir / "projects.json")
    # 模拟旧数据：default 项目无 path 字段
    repo.create_default("默认项目", "")
    svc = ProjectService(repo, projects_dir, cast(ConversationRepository, None))

    svc.ensure_default_project(tmp_path / "baseline")

    projects = svc.list_projects()
    assert projects[0]["path"] == str(
        (projects_dir / DEFAULT_PROJECT_ID).resolve()
    )
    assert svc.project_dir(DEFAULT_PROJECT_ID).is_dir()


def test_browse_directory(tmp_path):
    """目录浏览：返回当前路径、父路径、子目录列表。"""
    svc, _ = _make_service(tmp_path)
    root = tmp_path / "root"
    (root / "sub1").mkdir(parents=True)
    (root / "sub2").mkdir()
    (root / "file.txt").write_text("x")
    (root / ".hidden").mkdir()
    (root / "node_modules").mkdir()

    data = svc.browse(str(root))
    assert data["path"] == str(root.resolve())
    assert data["parent"] == str(root.parent.resolve())
    names = [e["name"] for e in data["entries"]]
    # 只列目录，过滤隐藏/敏感目录
    assert names == ["sub1", "sub2"]
    assert all(e["path"].startswith(str(root.resolve())) for e in data["entries"])


def test_browse_root_defaults_to_home(tmp_path):
    """path 为空时默认浏览主目录。"""
    svc, _ = _make_service(tmp_path)
    data = svc.browse(None)
    assert data["path"] == str(Path.home().resolve())


def test_browse_missing_dir_raises(tmp_path):
    """浏览不存在的目录抛 ValueError。"""
    svc, _ = _make_service(tmp_path)
    import pytest

    with pytest.raises(ValueError):
        svc.browse(str(tmp_path / "ghost"))


async def test_delete_project_cascades_conversations(tmp_path):
    """删除项目级联删除该项目下所有会话。"""
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir(parents=True, exist_ok=True)
    repo = ProjectRepository(projects_dir / "projects.json")
    async with SQLiteCheckpointer(str(tmp_path / "s.db")) as cp:
        conv_repo = ConversationRepository(cp)
        svc = ProjectService(repo, projects_dir, conv_repo)
        real_dir = tmp_path / "real-code"
        real_dir.mkdir(parents=True, exist_ok=True)
        p = svc.create_project("级联", str(real_dir))
        # 该项目下两个会话 + 其他项目一个会话
        await cp.append(
            f"demo-user:{p['id']}:conv_1",
            [UserMessage(content=[TextContent(text="a1")])],
        )
        await cp.append(
            f"demo-user:{p['id']}:conv_2",
            [UserMessage(content=[TextContent(text="a2")])],
        )
        await cp.append(
            "demo-user:other:conv_3",
            [UserMessage(content=[TextContent(text="b1")])],
        )

        await svc.delete_project("demo-user", p["id"])

        assert await cp.load(f"demo-user:{p['id']}:conv_1") is None
        assert await cp.load(f"demo-user:{p['id']}:conv_2") is None
        # 其他项目会话保留
        assert await cp.load("demo-user:other:conv_3") is not None


def test_thread_id_roundtrip(tmp_path):
    """thread_id 构造与项目提取。"""
    svc, _ = _make_service(tmp_path)
    tid = svc.thread_id("demo-user", "proj_abc", "conv_1")
    assert tid == "demo-user:proj_abc:conv_1"
    assert svc.project_id_from_thread(tid) == "proj_abc"
    # 旧格式（2 段）视为 default
    assert svc.project_id_from_thread("demo-user:conv_1") == DEFAULT_PROJECT_ID


async def test_get_history_legacy_thread_id_fallback(tmp_path):
    """旧 2 段 thread_id 会话在 default 项目下可读历史（兼容迁移前数据）。"""
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir(parents=True, exist_ok=True)
    repo = ProjectRepository(projects_dir / "projects.json")
    async with SQLiteCheckpointer(str(tmp_path / "s.db")) as cp:
        conv_repo = ConversationRepository(cp)
        project_svc = ProjectService(repo, projects_dir, conv_repo)
        project_svc.ensure_default_project(tmp_path / "baseline")
        conv_svc = ConversationService(conv_repo)
        chat_svc = ChatService(
            cast(Any, None), cp, conv_svc, project_svc
        )

        # 旧格式数据：demo-user:conv_legacy（2 段）
        await cp.append(
            "demo-user:conv_legacy",
            [UserMessage(content=[TextContent(text="旧消息")])],
        )

        # 3 段格式读不到，回退读 2 段
        history = await chat_svc.get_history(
            "demo-user", DEFAULT_PROJECT_ID, "conv_legacy"
        )
        assert len(history) == 1
        assert history[0]["role"] == "user"
        assert "旧消息" in history[0]["content"]

        # 新格式数据优先读 3 段
        await cp.append(
            f"demo-user:{DEFAULT_PROJECT_ID}:conv_new",
            [UserMessage(content=[TextContent(text="新消息")])],
        )
        history = await chat_svc.get_history(
            "demo-user", DEFAULT_PROJECT_ID, "conv_new"
        )
        assert len(history) == 1
        assert "新消息" in history[0]["content"]

        # 非 default 项目不启用旧格式回退
        history = await chat_svc.get_history(
            "demo-user", "proj_other", "conv_legacy"
        )
        assert history == []
