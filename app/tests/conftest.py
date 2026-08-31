"""测试共享 fixture。"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# 确保 app 包可导入（项目根目录）
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import AppConfig  # noqa: E402


@pytest.fixture
def app_config(tmp_path: Path) -> AppConfig:
    """临时目录配置：papers / baseline / backups / db 都在 tmp_path 下。"""
    papers = tmp_path / "papers"
    baseline = tmp_path / "baseline"
    backups = tmp_path / "backups"
    db = tmp_path / "sessions.db"
    for d in (papers, baseline, backups):
        d.mkdir(parents=True, exist_ok=True)
    return AppConfig(
        papers_dir=papers,
        baseline_dir=baseline,
        db_path=db,
        backups_dir=backups,
        workspace_root=tmp_path,
    )
