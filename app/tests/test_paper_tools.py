"""论文工具集测试。"""

from __future__ import annotations

import pytest

from app.tools.paper_tools import make_paper_tools


@pytest.fixture
def paper_tools(app_config):
    return make_paper_tools(app_config.papers_dir)


def _tool_by_name(tools, name):
    return next(t for t in tools if t.name == name)


def _make_pdf(path, pages_text: list[str]) -> None:
    """用 pypdf 生成一个最小 PDF（每页一段文本）。"""
    from pypdf import PdfWriter

    writer = PdfWriter()
    for _text in pages_text:
        writer.add_blank_page(width=200, height=200)
    with open(path, "wb") as f:
        writer.write(f)


async def test_list_papers_empty(paper_tools):
    tool = _tool_by_name(paper_tools, "list_papers")
    result = await tool.execute("tc-1", tool.parameters())
    assert "<no papers found>" in result.content[0].text


async def test_read_paper_not_found(paper_tools):
    tool = _tool_by_name(paper_tools, "read_paper")
    with pytest.raises(ValueError, match="not a PDF"):
        await tool.execute("tc-1", tool.parameters(filename="missing.pdf"))


async def test_read_paper_path_escape(paper_tools):
    tool = _tool_by_name(paper_tools, "read_paper")
    with pytest.raises(ValueError, match="inside the papers directory"):
        await tool.execute("tc-1", tool.parameters(filename="../evil.pdf"))
