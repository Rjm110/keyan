"""配置持久化测试：RuntimeConfig 落盘 / 加载 / 容错。"""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest

from app.config import AppConfig, RuntimeConfig


def test_save_creates_file_with_600_permission(tmp_path: Path) -> None:
    """保存后文件存在，且权限为 600（保护 API key）。"""
    path = tmp_path / "config.json"
    cfg = RuntimeConfig(
        provider="opencode",
        api_key="sk-test-key-123456",
        model="deepseek-v4-flash",
        base_url="https://example.com/v1",
    )
    cfg.save_to_file(path)

    assert path.exists()
    mode = stat.S_IMODE(os.stat(path).st_mode)
    assert mode == 0o600


def test_save_then_load_roundtrip(tmp_path: Path) -> None:
    """保存后重新加载能读到完整配置。"""
    path = tmp_path / "config.json"
    original = RuntimeConfig(
        provider="deepseek",
        api_key="sk-roundtrip-key",
        model="deepseek-chat",
        base_url=None,
    )
    original.save_to_file(path)

    loaded = RuntimeConfig.load_from_file(path)
    assert loaded.provider == "deepseek"
    assert loaded.api_key == "sk-roundtrip-key"
    assert loaded.model == "deepseek-chat"
    assert loaded.base_url is None
    assert loaded.is_configured()


def test_load_missing_file_returns_empty(tmp_path: Path) -> None:
    """文件不存在时优雅降级：返回空配置，不崩溃。"""
    loaded = RuntimeConfig.load_from_file(tmp_path / "nope.json")
    assert loaded == RuntimeConfig()
    assert not loaded.is_configured()


def test_load_corrupted_file_returns_empty(tmp_path: Path) -> None:
    """文件损坏（非法 JSON）时优雅降级：返回空配置，不崩溃。"""
    path = tmp_path / "config.json"
    path.write_text("{ not valid json !!!", encoding="utf-8")
    loaded = RuntimeConfig.load_from_file(path)
    assert loaded == RuntimeConfig()
    assert not loaded.is_configured()


def test_load_ignores_unknown_fields(tmp_path: Path) -> None:
    """文件含未知字段时忽略，不崩溃。"""
    path = tmp_path / "config.json"
    path.write_text(
        json.dumps(
            {
                "provider": "kimi",
                "api_key": "sk-unknown-fields",
                "hacker_field": "evil",
            }
        ),
        encoding="utf-8",
    )
    loaded = RuntimeConfig.load_from_file(path)
    assert loaded.provider == "kimi"
    assert loaded.api_key == "sk-unknown-fields"
    assert not hasattr(loaded, "hacker_field")


def test_save_skips_none_fields(tmp_path: Path) -> None:
    """序列化时跳过 None 字段，文件保持精简。"""
    path = tmp_path / "config.json"
    RuntimeConfig(provider="glm", api_key="sk-none-fields").save_to_file(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data == {"provider": "glm", "api_key": "sk-none-fields"}


def test_app_config_has_config_path(app_config: AppConfig) -> None:
    """AppConfig 提供 config_path（workspace/config.json）。"""
    assert app_config.config_path == app_config.workspace_root / "config.json"


@pytest.mark.parametrize(
    "data",
    [
        "not json",
        '{"provider": 123}',
        "[1, 2, 3]",
        "",
    ],
)
def test_load_various_corruptions_graceful(tmp_path: Path, data: str) -> None:
    """多种损坏形态均优雅降级。"""
    path = tmp_path / "config.json"
    path.write_text(data, encoding="utf-8")
    loaded = RuntimeConfig.load_from_file(path)
    assert isinstance(loaded, RuntimeConfig)
