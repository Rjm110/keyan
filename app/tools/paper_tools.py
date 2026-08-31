"""论文工具集：列出论文目录、读取 PDF 论文文本。

- 论文放在 papers_dir（配置中 CUBEPI_PAPERS_DIR，默认 workspace/papers）
- read_paper 用 pypdf 提取文本，按 (文件名, 修改时间) 缓存，避免重复解析
- 支持按页读取（start_page/end_page），避免一次塞入过多 token
"""

from __future__ import annotations

from pathlib import Path

from cubepi import AgentToolResult, TextContent, tool

MAX_PAGES_PER_READ = 20


def _text_result(text: str, *, is_error: bool = False) -> AgentToolResult:
    return AgentToolResult(content=[TextContent(text=text)], is_error=is_error)


def _extract_pdf_text(pdf_path: Path) -> list[str]:
    """提取 PDF 每页文本，返回 list[str]（每页一个元素）。"""
    from pypdf import PdfReader

    reader = PdfReader(str(pdf_path))
    return [page.extract_text() or "" for page in reader.pages]


def make_paper_tools(papers_dir: Path) -> list:
    """创建论文工具集（闭包注入论文目录）。

    返回 list[AgentTool]，可直接传给 Agent(tools=[...])。
    """
    papers = papers_dir.resolve()
    papers.mkdir(parents=True, exist_ok=True)
    # 缓存：{缓存键: (mtime_ns, [每页文本])}
    _cache: dict[str, tuple[int, list[str]]] = {}

    def _cache_key(pdf_path: Path) -> str:
        return f"{pdf_path}:{pdf_path.stat().st_mtime_ns}"

    def _load_pages(pdf_path: Path) -> list[str]:
        key = _cache_key(pdf_path)
        cached = _cache.get(key)
        if cached is not None:
            return cached[1]
        pages = _extract_pdf_text(pdf_path)
        _cache[key] = (pdf_path.stat().st_mtime_ns, pages)
        return pages

    @tool
    async def list_papers() -> str:
        """List PDF papers in the papers directory."""
        entries = []
        for child in sorted(papers.iterdir()):
            if child.is_file() and child.suffix.lower() == ".pdf":
                entries.append(child.name)
        return "\n".join(entries) or "<no papers found>"

    @tool
    async def read_paper(
        filename: str,
        start_page: int = 1,
        end_page: int | None = None,
    ) -> str:
        """Read text from a PDF paper (one-based inclusive page numbers).

        filename must be a PDF file in the papers directory. Use start_page/
        end_page to read a range; at most 20 pages per call.
        """
        pdf_path = (papers / filename).resolve()
        try:
            pdf_path.relative_to(papers)
        except ValueError as exc:
            raise ValueError("filename must stay inside the papers directory") from exc
        if not pdf_path.is_file() or pdf_path.suffix.lower() != ".pdf":
            raise ValueError(f"not a PDF file in papers dir: {filename}")

        pages = _load_pages(pdf_path)
        total = len(pages)
        if start_page < 1 or start_page > total:
            raise ValueError(f"start_page must be between 1 and {total}")
        end = (
            end_page
            if end_page is not None
            else min(start_page + MAX_PAGES_PER_READ - 1, total)
        )
        if end < start_page or end - start_page + 1 > MAX_PAGES_PER_READ:
            raise ValueError(
                f"page range too large; at most {MAX_PAGES_PER_READ} pages per call"
            )
        end = min(end, total)

        parts = [f"--- {filename} pages {start_page}-{end} (of {total}) ---"]
        for number in range(start_page, end + 1):
            text = pages[number - 1].strip()
            if text:
                parts.append(f"[page {number}]\n{text}")
        return "\n\n".join(parts)

    @tool
    async def paper_summary(filename: str) -> str:
        """Get a quick structural summary of a PDF paper (title, sections, length)."""
        pdf_path = (papers / filename).resolve()
        try:
            pdf_path.relative_to(papers)
        except ValueError as exc:
            raise ValueError("filename must stay inside the papers directory") from exc
        if not pdf_path.is_file() or pdf_path.suffix.lower() != ".pdf":
            raise ValueError(f"not a PDF file in papers dir: {filename}")

        pages = _load_pages(pdf_path)
        total = len(pages)
        first_text = pages[0].strip() if pages else ""
        # 粗略提取标题：第一页前几行非空文本
        lines = [ln.strip() for ln in first_text.splitlines() if ln.strip()]
        title = lines[0][:200] if lines else "<unknown>"
        # 统计总字符数
        char_count = sum(len(p) for p in pages)
        return (
            f"filename: {filename}\n"
            f"pages: {total}\n"
            f"approx chars: {char_count}\n"
            f"first page title guess: {title}"
        )

    return [list_papers, read_paper, paper_summary]
