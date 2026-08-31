"""科研助手配置：provider 选择、目录路径、会话存储。

配置优先级：前端运行时配置（POST /config）> 显式环境变量 > 预设默认值。

Provider 选择（与 examples/_provider.py 一致）：
    export CUBEPI_PROVIDER=deepseek        # deepseek | qwen | kimi | glm | anthropic | openai
    export DEEPSEEK_API_KEY=sk-...          # 对应 provider 的 API key
    export MODEL=deepseek-chat              # 可选，覆盖默认模型
    export CUBEPI_BASE_URL=...              # 可选，覆盖 base_url（可指向本地 vLLM/Ollama）
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from cubepi.providers.base import BoundModel
from cubepi.providers.presets import create_provider, get_provider_preset

# 预设 provider 名称（OpenAI 兼容）
_PRESET_NAMES = {
    "deepseek",
    "qwen",
    "bailian",
    "dashscope",
    "kimi",
    "moonshot",
    "glm",
    "zhipu",
    "opencode",
}

# 原生 provider（非 OpenAI 兼容预设）
_NATIVE_PROVIDERS = {"anthropic", "openai"}

# 前端可选的 provider 列表（含显示名）
PROVIDER_OPTIONS: list[dict] = [
    {"id": "deepseek", "name": "DeepSeek", "default_model": "deepseek-v4-flash"},
    {"id": "qwen", "name": "通义千问 Qwen", "default_model": "qwen-plus"},
    {"id": "kimi", "name": "Kimi (月之暗面)", "default_model": "moonshot-v1-8k"},
    {"id": "glm", "name": "智谱 GLM", "default_model": "glm-4-flash"},
    {
        "id": "opencode",
        "name": "OpenCode Go",
        "default_model": "deepseek-v4-flash",
    },
    {
        "id": "anthropic",
        "name": "Anthropic Claude",
        "default_model": "claude-sonnet-4-6",
    },
    {"id": "openai", "name": "OpenAI", "default_model": "gpt-4o"},
]


@dataclass(frozen=True)
class AppConfig:
    """应用配置。"""

    # 论文目录：用户把论文 PDF 放到这里
    papers_dir: Path
    # baseline 代码目录：agent 修改的目标项目
    baseline_dir: Path
    # 会话数据库路径
    db_path: Path
    # 备份目录（写入前自动备份）
    backups_dir: Path
    # 允许 agent 访问的根目录（路径沙箱）
    workspace_root: Path


@dataclass
class RuntimeConfig:
    """前端提交的运行时配置（内存存储，不持久化）。"""

    provider: str | None = None
    api_key: str | None = None
    model: str | None = None
    base_url: str | None = None

    def is_configured(self) -> bool:
        return bool(self.provider and self.api_key)


# 全局运行时配置（单 worker 共享）
_runtime: RuntimeConfig = RuntimeConfig()


def get_runtime_config() -> RuntimeConfig:
    """获取前端提交的运行时配置。"""
    return _runtime


def set_runtime_config(
    provider: str, api_key: str, model: str | None = None, base_url: str | None = None
) -> None:
    """保存前端提交的运行时配置。"""
    _runtime.provider = provider
    _runtime.api_key = api_key
    _runtime.model = model or None
    _runtime.base_url = base_url or None


def _resolve_dir(name: str, default: str) -> Path:
    """解析目录环境变量，不存在则创建。"""
    path = Path(os.environ.get(name, default)).expanduser().resolve()
    path.mkdir(parents=True, exist_ok=True)
    return path


def load_config() -> AppConfig:
    """从环境变量加载配置，默认值面向本地开发。"""
    base = Path(os.environ.get("CUBEPI_WORKSPACE", "workspace")).expanduser().resolve()
    papers_dir = _resolve_dir("CUBEPI_PAPERS_DIR", str(base / "papers"))
    baseline_dir = _resolve_dir("CUBEPI_BASELINE_DIR", str(base / "baseline"))
    backups_dir = _resolve_dir("CUBEPI_BACKUPS_DIR", str(base / "backups"))
    db_path = (
        Path(os.environ.get("CUBEPI_DB_PATH", str(base / "sessions.db")))
        .expanduser()
        .resolve()
    )
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return AppConfig(
        papers_dir=papers_dir,
        baseline_dir=baseline_dir,
        db_path=db_path,
        backups_dir=backups_dir,
        workspace_root=base,
    )


def build_model() -> BoundModel:
    """根据运行时配置（前端提交）或环境变量构建 BoundModel。

    优先级：前端 POST /config 提交的配置 > 环境变量。

    支持：
    - CUBEPI_PROVIDER=deepseek|qwen|kimi|glm（OpenAI 兼容预设）
    - CUBEPI_PROVIDER=anthropic|openai（原生 provider）
    - 未设置时若存在 ANTHROPIC_API_KEY / OPENAI_API_KEY 自动选择
    """
    runtime = get_runtime_config()
    if runtime.is_configured():
        return _build_from_runtime(runtime)

    selected = os.environ.get("CUBEPI_PROVIDER", "").strip().lower()
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY")
    openai_key = os.environ.get("OPENAI_API_KEY")
    base_url = os.environ.get("CUBEPI_BASE_URL") or None

    if selected in _PRESET_NAMES:
        preset = get_provider_preset(selected)
        provider = create_provider(selected, base_url=base_url)
        model_id = os.environ.get("MODEL", preset.model)
        return provider.model(model_id)

    if selected == "anthropic" or (not selected and anthropic_key):
        from cubepi.providers.anthropic import AnthropicProvider

        anthropic_provider = AnthropicProvider(api_key=anthropic_key, base_url=base_url)
        model_id = os.environ.get("MODEL", "claude-sonnet-4-6")
        return anthropic_provider.model(model_id)

    if selected == "openai" or (not selected and openai_key):
        from cubepi.providers.openai import OpenAIProvider

        openai_provider = OpenAIProvider(api_key=openai_key, base_url=base_url)
        model_id = os.environ.get("MODEL", "gpt-4o")
        return openai_provider.model(model_id)

    raise RuntimeError(
        "未配置 LLM provider。请在前端选择大模型厂商并输入 API Key，"
        "或设置 CUBEPI_PROVIDER（deepseek/qwen/kimi/glm/opencode/anthropic/openai）"
        "及对应的 API key 环境变量。"
    )


def _build_from_runtime(runtime: RuntimeConfig) -> BoundModel:
    """根据前端提交的运行时配置构建 BoundModel。"""
    provider_id = runtime.provider or ""
    api_key = runtime.api_key or ""
    model_id = runtime.model or None
    base_url = runtime.base_url or None

    if provider_id in _PRESET_NAMES:
        preset = get_provider_preset(provider_id)
        provider = create_provider(provider_id, api_key=api_key, base_url=base_url)
        return provider.model(model_id or preset.model)

    if provider_id == "anthropic":
        from cubepi.providers.anthropic import AnthropicProvider

        anthropic_provider = AnthropicProvider(api_key=api_key, base_url=base_url)
        return anthropic_provider.model(model_id or "claude-sonnet-4-6")

    if provider_id == "openai":
        from cubepi.providers.openai import OpenAIProvider

        openai_provider = OpenAIProvider(api_key=api_key, base_url=base_url)
        return openai_provider.model(model_id or "gpt-4o")

    raise RuntimeError(f"未知 provider：{provider_id}")
