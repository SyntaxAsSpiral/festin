"""Named tool handlers for the chat turn.

Plugins add tools with register_tool and opening text with
register_opening_contributor. They do not keep a second registry.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


Handler = Callable[[dict, Any], Any]
OpeningContributor = Callable[[Any], str | None]


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters: dict
    handler: Handler
    label: str | None = None
    failure_label: str | None = None


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}
        self._opening: list[OpeningContributor] = []

    def register_tool(
        self,
        name: str,
        description: str,
        parameters: dict,
        handler: Handler,
        label: str | None = None,
        failure_label: str | None = None,
    ) -> None:
        if name in self._tools:
            raise ValueError(f"tool already registered: {name}")
        self._tools[name] = ToolSpec(
            name=name,
            description=description,
            parameters=parameters,
            handler=handler,
            label=label,
            failure_label=failure_label,
        )

    def register_opening_contributor(self, fn: OpeningContributor) -> None:
        self._opening.append(fn)

    def openai_tools(self) -> list[dict]:
        return [
            {
                "type": "function",
                "function": {
                    "name": spec.name,
                    "description": spec.description,
                    "parameters": spec.parameters,
                },
            }
            for spec in self._tools.values()
        ]

    def dispatch(self, name: str, args: dict | None, ctx: Any) -> Any:
        spec = self._tools.get(name)
        if spec is None:
            raise ValueError("Unknown tool")
        return spec.handler(args or {}, ctx)

    def tool_label(self, name: str, result: Any = None) -> str:
        spec = self._tools.get(name)
        if spec is None:
            return name
        if isinstance(result, dict) and result.get("error") and spec.failure_label:
            return spec.failure_label
        return spec.label or name

    def opening_snippets(self, ctx: Any) -> list[str]:
        found = []
        for fn in self._opening:
            text = fn(ctx)
            if isinstance(text, str) and text.strip():
                found.append(text)
        return found

    def names(self) -> list[str]:
        return list(self._tools)
