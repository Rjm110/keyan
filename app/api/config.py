"""配置路由：provider 选择与 API key 管理。

- GET  /config — 返回可用 provider 列表与当前配置状态（API key 脱敏）
- POST /config — 保存前端提交的 provider 配置（内存 + 持久化到 workspace/config.json）
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.config import (
    PROVIDER_OPTIONS,
    get_runtime_config,
    persist_runtime_config,
    set_runtime_config,
)


class ConfigBody(BaseModel):
    provider: str = Field(min_length=1)
    api_key: str = Field(min_length=1)
    model: str | None = None
    base_url: str | None = None


def create_config_router() -> APIRouter:
    """创建配置路由（无依赖注入，使用全局运行时配置）。"""
    router = APIRouter(prefix="/config", tags=["config"])

    @router.get("")
    async def get_config() -> dict:
        """返回可用 provider 列表与当前配置状态（API key 脱敏）。"""
        runtime = get_runtime_config()
        return {
            "providers": PROVIDER_OPTIONS,
            "current": {
                "provider": runtime.provider,
                "model": runtime.model,
                "base_url": runtime.base_url,
                "configured": runtime.is_configured(),
                "api_key_masked": (
                    f"{runtime.api_key[:4]}…{runtime.api_key[-4:]}"
                    if runtime.api_key and len(runtime.api_key) > 8
                    else "***"
                    if runtime.api_key
                    else None
                ),
            },
        }

    @router.post("")
    async def post_config(body: ConfigBody) -> dict:
        """保存前端提交的 provider 配置（内存 + 持久化到磁盘）。"""
        valid_ids = {p["id"] for p in PROVIDER_OPTIONS}
        if body.provider not in valid_ids:
            raise HTTPException(
                status_code=400, detail=f"未知 provider：{body.provider}"
            )
        set_runtime_config(
            provider=body.provider,
            api_key=body.api_key,
            model=body.model,
            base_url=body.base_url,
        )
        persist_runtime_config()
        return {"status": "ok", "provider": body.provider}

    return router
