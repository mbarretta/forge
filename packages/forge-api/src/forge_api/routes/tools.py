"""Tool listing endpoint."""

from __future__ import annotations

from fastapi import APIRouter

from forge_api.models import ParamInfo, ToolInfo
from forge_core.registry import discover_plugins

router = APIRouter()


@router.get("/tools", response_model=list[ToolInfo])
async def list_tools() -> list[ToolInfo]:
    """List all available tools and their parameters."""
    plugins = discover_plugins()
    result = []
    for plugin in sorted(plugins.values(), key=lambda p: p.name):
        params = [
            ParamInfo(
                name=p.name,
                description=p.description,
                type=p.type,
                required=p.required,
                default=p.default,
                choices=p.choices,
            )
            for p in plugin.get_params()
        ]
        result.append(
            ToolInfo(
                name=plugin.name,
                description=plugin.description,
                version=plugin.version,
                params=params,
            )
        )
    return result
