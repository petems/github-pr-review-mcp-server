"""Normalized MCP tool error helpers."""

from __future__ import annotations

from dataclasses import dataclass, field

from .models import ToolErrorDetailsModel


@dataclass(frozen=True)
class ToolExecutionError(Exception):
    """Actionable error information for canonical MCP tool responses."""

    code: str
    message: str
    next_steps: list[str] = field(default_factory=list)

    def to_model(self) -> ToolErrorDetailsModel:
        """Convert error details to the normalized response model."""
        return ToolErrorDetailsModel(
            code=self.code,  # type: ignore[arg-type]
            message=self.message,
            next_steps=self.next_steps,
        )
