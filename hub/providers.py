"""Phase 6: explicit provider registry. Safe by default: no network/API calls.

A provider is a *capability* with an operator-supplied callable. This does
not magically link the ChatGPT app, Codex CLI, or Claude Code; actual adapters
must later be installed and authorized independently.
"""
from dataclasses import dataclass
from .dispatcher import WorkResult

class ProviderDisabled(PermissionError):
    pass

@dataclass(frozen=True)
class Provider:
    name: str
    mode: str = "disabled"  # disabled | mock
    can_execute: bool = False
    transport: str = "none"

    def __post_init__(self):
        if self.mode not in {"disabled", "mock"}:
            raise ValueError("live providers not enabled")
        if not self.name.strip():
            raise ValueError("provider name required")
        if self.mode == "disabled" and self.can_execute:
            raise ValueError("disabled provider cannot execute")

class ProviderRegistry:
    def __init__(self):
        self._providers = {}
        self._mock_handlers = {}

    def register(self, provider: Provider, *, handler=None):
        if provider.name in self._providers:
            raise ValueError("provider already registered")
        if provider.mode == "mock" and provider.can_execute and not callable(handler):
            raise ValueError("mock handler required")
        if provider.mode != "mock" and handler is not None:
            raise ValueError("handler forbidden in disabled mode")
        self._providers[provider.name] = provider
        if handler is not None:
            self._mock_handlers[provider.name] = handler

    def manifest(self):
        return [{"name": p.name, "mode": p.mode,
                 "can_execute": p.can_execute, "transport": p.transport}
                for p in self._providers.values()]

    def execute(self, name, task):
        provider = self._providers.get(name)
        if provider is None or provider.mode != "mock" or not provider.can_execute:
            raise ProviderDisabled("provider not connected or authorized")
        if not isinstance(task, dict) or not isinstance(task.get("task_id"), str):
            raise ValueError("structured task with task_id required")
        outcome = self._mock_handlers[name](dict(task))
        if not isinstance(outcome, WorkResult) or not outcome.output_ref:
            raise ValueError("provider mock must produce WorkResult")
        return outcome

def default_registry():
    registry = ProviderRegistry()
    for name in ("gpt", "claude-code", "codex"):
        registry.register(Provider(name=name))
    return registry
