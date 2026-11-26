"""Hook registry: the points where a client package can add behaviour to the core.

Core and module code *declare* a hook, then call ``run`` or ``pipe`` where it should fire.
Client packages ``register`` functions for declared hooks only, so a mistyped hook name
fails loudly instead of silently never running.

Hook names are dotted and lowercase, for example ``payroll.before_calculate``.
"""
from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

_NAME = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$")


class HookError(Exception):
    """A hook was misnamed, undeclared or given something that is not callable."""


class HookRegistry:
    def __init__(self) -> None:
        self._declared: dict[str, str] = {}
        self._hooks: dict[str, list[tuple[int, int, Callable[..., Any]]]] = {}
        self._counter = 0

    def declare(self, name: str, description: str = "") -> None:
        """Announce a hook. Declaring the same name twice is harmless."""
        if not _NAME.match(name):
            raise HookError(
                f"Invalid hook name {name!r}: use dotted lowercase names like 'payroll.before_calculate'"
            )
        self._declared.setdefault(name, description)

    def declared(self) -> dict[str, str]:
        return dict(self._declared)

    def _require_declared(self, name: str) -> None:
        if name not in self._declared:
            known = ", ".join(sorted(self._declared)) or "none"
            raise HookError(f"Unknown hook {name!r}. Declared hooks: {known}")

    def register(self, name: str, func: Callable[..., Any], *, order: int = 100) -> None:
        """Attach ``func`` to a declared hook. Lower ``order`` runs first; ties run in
        registration order."""
        self._require_declared(name)
        if not callable(func):
            raise HookError(f"Hook {name!r} needs a callable, got {type(func).__name__}")
        self._counter += 1
        entries = self._hooks.setdefault(name, [])
        entries.append((order, self._counter, func))
        entries.sort(key=lambda entry: (entry[0], entry[1]))

    def register_once(self, name: str, func: Callable[..., Any], *, order: int = 100) -> bool:
        """Like ``register`` but does nothing if ``func`` is already on the hook. Lets a module
        register itself at start-up and again in tests without running twice. Returns True if added."""
        self._require_declared(name)
        if func in self.functions(name):
            return False
        self.register(name, func, order=order)
        return True

    def hook(self, name: str, *, order: int = 100) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        """Decorator form of ``register``."""

        def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
            self.register(name, func, order=order)
            return func

        return decorator

    def functions(self, name: str) -> list[Callable[..., Any]]:
        self._require_declared(name)
        return [entry[2] for entry in self._hooks.get(name, [])]

    def run(self, name: str, *args: Any, **kwargs: Any) -> list[Any]:
        """Call every function on the hook and return their results in order."""
        return [func(*args, **kwargs) for func in self.functions(name)]

    def pipe(self, name: str, value: Any, *args: Any, **kwargs: Any) -> Any:
        """Pass ``value`` through every function on the hook; each returns the new value."""
        for func in self.functions(name):
            value = func(value, *args, **kwargs)
        return value

    def clear(self) -> None:
        """Remove registered functions but keep declarations. Used by tests."""
        self._hooks.clear()


registry = HookRegistry()
registry.declare("ems.ready", "Fired once after Django has started and the client extension has loaded.")
