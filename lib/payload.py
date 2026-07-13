"""StatusPayload — typed dataclass tree for Claude Code Status hook payloads."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

DEFAULT_CONTEXT_WINDOW = 200_000


@dataclass(frozen=True)
class ModelInfo:
    id: str = ""
    display_name: str = ""

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> ModelInfo:
        if not data:
            return cls()
        return cls(
            id=data.get("id", ""),
            display_name=data.get("display_name", ""),
        )


@dataclass(frozen=True)
class WorkspaceInfo:
    current_dir: str = ""
    project_dir: str = ""

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> WorkspaceInfo:
        if not data:
            return cls()
        return cls(
            current_dir=data.get("current_dir", ""),
            project_dir=data.get("project_dir", ""),
        )


@dataclass(frozen=True)
class CostInfo:
    total_cost_usd: float = 0.0
    total_duration_ms: int = 0
    total_api_duration_ms: int = 0
    total_lines_added: int = 0
    total_lines_removed: int = 0

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> CostInfo:
        if not data:
            return cls()
        return cls(
            total_cost_usd=float(data.get("total_cost_usd", 0) or 0),
            total_duration_ms=int(data.get("total_duration_ms", 0) or 0),
            total_api_duration_ms=int(data.get("total_api_duration_ms", 0) or 0),
            total_lines_added=int(data.get("total_lines_added", 0) or 0),
            total_lines_removed=int(data.get("total_lines_removed", 0) or 0),
        )


@dataclass(frozen=True)
class CurrentUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> CurrentUsage:
        if not data:
            return cls()
        return cls(
            input_tokens=int(data.get("input_tokens", 0) or 0),
            output_tokens=int(data.get("output_tokens", 0) or 0),
            cache_creation_input_tokens=int(data.get("cache_creation_input_tokens", 0) or 0),
            cache_read_input_tokens=int(data.get("cache_read_input_tokens", 0) or 0),
        )


@dataclass(frozen=True)
class ContextWindowInfo:
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    context_window_size: int = DEFAULT_CONTEXT_WINDOW
    used_percentage: Optional[float] = None
    remaining_percentage: Optional[float] = None
    current_usage: CurrentUsage = field(default_factory=CurrentUsage)

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> ContextWindowInfo:
        if not data:
            return cls()
        return cls(
            total_input_tokens=int(data.get("total_input_tokens", 0) or 0),
            total_output_tokens=int(data.get("total_output_tokens", 0) or 0),
            context_window_size=int(data.get("context_window_size", DEFAULT_CONTEXT_WINDOW) or DEFAULT_CONTEXT_WINDOW),
            used_percentage=data.get("used_percentage"),
            remaining_percentage=data.get("remaining_percentage"),
            current_usage=CurrentUsage.from_dict(data.get("current_usage")),
        )


@dataclass(frozen=True)
class RateLimitWindow:
    used_percentage: float = 0.0
    resets_at: int = 0

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> RateLimitWindow:
        if not data:
            return cls()
        return cls(
            used_percentage=float(data.get("used_percentage", 0) or 0),
            resets_at=int(data.get("resets_at", 0) or 0),
        )


@dataclass(frozen=True)
class RateLimitsInfo:
    five_hour: RateLimitWindow = field(default_factory=RateLimitWindow)
    seven_day: RateLimitWindow = field(default_factory=RateLimitWindow)

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> RateLimitsInfo:
        if not data:
            return cls()
        return cls(
            five_hour=RateLimitWindow.from_dict(data.get("five_hour")),
            seven_day=RateLimitWindow.from_dict(data.get("seven_day")),
        )


@dataclass(frozen=True)
class VimInfo:
    mode: str = "NORMAL"

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> VimInfo:
        if not data:
            return cls()
        return cls(mode=data.get("mode", "NORMAL"))


@dataclass(frozen=True)
class AgentInfo:
    name: str = ""

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> AgentInfo:
        if not data:
            return cls()
        return cls(name=data.get("name", ""))


@dataclass(frozen=True)
class WorktreeInfo:
    name: str = ""
    path: str = ""
    branch: str = ""
    original_cwd: str = ""
    original_branch: str = ""

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> WorktreeInfo:
        if not data:
            return cls()
        return cls(
            name=data.get("name", ""),
            path=data.get("path", ""),
            branch=data.get("branch", ""),
            original_cwd=data.get("original_cwd", ""),
            original_branch=data.get("original_branch", ""),
        )


@dataclass(frozen=True)
class StatusPayload:
    """Full parsed Status hook payload from Claude Code.

    The ``_raw`` dict holds the unmodified input dict — it is the source of
    truth for logging. Typed fields above are convenience accessors with safe
    defaults; ``_raw`` is never truncated or filtered.
    """

    cwd: str = ""
    session_id: str = ""
    transcript_path: str = ""
    model: ModelInfo = field(default_factory=ModelInfo)
    workspace: WorkspaceInfo = field(default_factory=WorkspaceInfo)
    version: str = ""
    output_style: str = "default"
    cost: CostInfo = field(default_factory=CostInfo)
    context_window: ContextWindowInfo = field(default_factory=ContextWindowInfo)
    exceeds_200k_tokens: bool = False
    rate_limits: Optional[RateLimitsInfo] = None
    vim: Optional[VimInfo] = None
    agent: Optional[AgentInfo] = None
    worktree: Optional[WorktreeInfo] = None
    # Fields discovered in live data (not yet in official docs)
    agent_type: str = ""
    session_name: str = ""
    _raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> StatusPayload:
        if not data:
            return cls()
        raw = data

        # output_style can be {"name": "default"} or missing
        output_style_val = data.get("output_style")
        if isinstance(output_style_val, dict):
            output_style_str = output_style_val.get("name", "default")
        elif isinstance(output_style_val, str):
            output_style_str = output_style_val
        else:
            output_style_str = "default"

        # Optional sections — only parse if present
        rate_limits = None
        if "rate_limits" in data and data["rate_limits"]:
            rate_limits = RateLimitsInfo.from_dict(data["rate_limits"])

        vim = None
        if "vim" in data and data["vim"]:
            vim = VimInfo.from_dict(data["vim"])

        agent = None
        if "agent" in data and data["agent"]:
            agent = AgentInfo.from_dict(data["agent"])

        worktree = None
        if "worktree" in data and data["worktree"]:
            worktree = WorktreeInfo.from_dict(data["worktree"])

        return cls(
            cwd=data.get("cwd", ""),
            session_id=data.get("session_id", ""),
            transcript_path=data.get("transcript_path", ""),
            model=ModelInfo.from_dict(data.get("model")),
            workspace=WorkspaceInfo.from_dict(data.get("workspace")),
            version=data.get("version", ""),
            output_style=output_style_str,
            cost=CostInfo.from_dict(data.get("cost")),
            context_window=ContextWindowInfo.from_dict(data.get("context_window")),
            exceeds_200k_tokens=bool(data.get("exceeds_200k_tokens", False)),
            rate_limits=rate_limits,
            vim=vim,
            agent=agent,
            worktree=worktree,
            agent_type=str(data.get("agent_type", "")),
            session_name=str(data.get("session_name", "")),
            _raw=raw,
        )

    @classmethod
    def from_json(cls, raw: str) -> StatusPayload:
        """Parse a JSON string into a StatusPayload. Returns empty payload on bad input."""
        if not raw or not raw.strip():
            return cls()
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return cls()
        if not isinstance(data, dict):
            return cls()
        return cls.from_dict(data)
