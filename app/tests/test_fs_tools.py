"""文件系统工具集测试。"""

from __future__ import annotations

import pytest

from app.tools.fs_tools import make_fs_tools


@pytest.fixture
def fs_tools(app_config):
    return make_fs_tools(app_config.workspace_root, app_config.backups_dir)


def _tool_by_name(tools, name):
    return next(t for t in tools if t.name == name)


async def test_list_files_root(fs_tools):
    tool = _tool_by_name(fs_tools, "list_files")
    result = await tool.execute("tc-1", tool.parameters(path="."))
    text = result.content[0].text
    assert "baseline/" in text
    assert "papers/" in text
    assert "backups/" in text


async def test_write_and_read_file(fs_tools, app_config):
    write = _tool_by_name(fs_tools, "write_file")
    read = _tool_by_name(fs_tools, "read_file")

    result = await write.execute(
        "tc-1", write.parameters(path="baseline/hello.py", content="print('hi')\n")
    )
    assert "wrote baseline/hello.py" in result.content[0].text

    # 首次写入无备份（文件不存在）
    assert len(list(app_config.backups_dir.rglob("hello.py"))) == 0

    # 再次写入应有备份
    await write.execute(
        "tc-2", write.parameters(path="baseline/hello.py", content="print('hi2')\n")
    )
    assert len(list(app_config.backups_dir.rglob("hello.py"))) == 1

    result = await read.execute("tc-3", read.parameters(path="baseline/hello.py"))
    assert "1: print('hi2')" in result.content[0].text


async def test_replace_in_file(fs_tools, app_config):
    write = _tool_by_name(fs_tools, "write_file")
    replace = _tool_by_name(fs_tools, "replace_in_file")

    await write.execute(
        "tc-1", write.parameters(path="baseline/a.py", content="x = 1\nprint(x)\n")
    )
    result = await replace.execute(
        "tc-2",
        replace.parameters(path="baseline/a.py", old_text="x = 1", new_text="x = 2"),
    )
    assert "edited baseline/a.py" in result.content[0].text
    content = (app_config.baseline_dir / "a.py").read_text()
    assert "x = 2" in content
    # 备份存在
    assert len(list(app_config.backups_dir.rglob("a.py"))) == 1


async def test_replace_in_file_multiple_matches_fails(fs_tools, app_config):
    write = _tool_by_name(fs_tools, "write_file")
    replace = _tool_by_name(fs_tools, "replace_in_file")

    await write.execute(
        "tc-1", write.parameters(path="baseline/b.py", content="x = 1\nx = 1\n")
    )
    with pytest.raises(ValueError, match="expected exactly one match"):
        await replace.execute(
            "tc-2",
            replace.parameters(
                path="baseline/b.py", old_text="x = 1", new_text="x = 2"
            ),
        )


async def test_path_escape_blocked(fs_tools):
    write = _tool_by_name(fs_tools, "write_file")
    with pytest.raises(ValueError, match="inside the workspace"):
        await write.execute("tc-1", write.parameters(path="../evil.py", content="x"))


async def test_secret_file_blocked(fs_tools):
    write = _tool_by_name(fs_tools, "write_file")
    with pytest.raises(ValueError, match="secret"):
        await write.execute(
            "tc-1", write.parameters(path="baseline/.env", content="KEY=1")
        )


async def test_search_files(fs_tools, app_config):
    write = _tool_by_name(fs_tools, "write_file")
    search = _tool_by_name(fs_tools, "search_files")

    await write.execute(
        "tc-1",
        write.parameters(path="baseline/c.py", content="def foo():\n    return 42\n"),
    )
    result = await search.execute(
        "tc-2", search.parameters(query="foo", path="baseline")
    )
    assert "c.py:1: def foo()" in result.content[0].text
