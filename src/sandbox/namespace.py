from __future__ import annotations

import builtins
import types
from collections.abc import Callable
from typing import IO, Any

import dill

from schemas.sandbox_config import SandboxConfig


class SandboxNamespaceMixin:
    """Saves, restores and bootstraps the persisted execution namespace."""

    config: SandboxConfig
    _restricted_import: Callable[..., types.ModuleType]
    _restricted_open: Callable[..., IO[str] | IO[bytes]]

    def _final_answer(self, answer: Any) -> None: ...

    def _save_namespace(self, namespace: dict[str, Any]) -> bytes:
        return dill.dumps(namespace, recurse=True)

    @staticmethod
    def _restore_namespace(
        namespace: dict[str, Any], namespace_save: bytes
    ) -> None:
        namespace.update(dill.loads(namespace_save))
        for key, value in list(namespace.items()):
            if isinstance(value, types.FunctionType):
                namespace[key] = types.FunctionType(
                    value.__code__,
                    namespace,
                    value.__name__,
                    value.__defaults__,
                    value.__closure__,
                )

    def _persist_namespace(
        self, namespace: dict[str, Any], tool_names: list[str]
    ) -> tuple[bytes, str]:
        live_keys = (
            set(tool_names)
            | {
                "list_resources",
                "get_resource",
                "list_prompts",
                "get_prompt",
            }
            | {
                "final_answer",
                "__builtins__",
                "__name__",
            }
        )
        persisted = {k: v for k, v in namespace.items() if k not in live_keys}
        try:
            return self._save_namespace(persisted), ""
        except Exception:
            pickable = {
                k: v for k, v in persisted.items() if self._can_pickle(v)
            }
            return (
                self._save_namespace(pickable),
                "\n[Note: some variables could not be persisted]",
            )

    def _make_initial_namespace(self) -> dict[str, Any]:
        allowed_builtins = {
            name: getattr(builtins, name)
            for name in self.config.authorized_builtins
            if hasattr(builtins, name)
        }
        if "__import__" in self.config.authorized_builtins:
            allowed_builtins["__import__"] = self._restricted_import
        if "open" in self.config.authorized_builtins:
            allowed_builtins["open"] = self._restricted_open
        return {
            "__builtins__": allowed_builtins,
            "__name__": "__sandbox__",
            "final_answer": self._final_answer,
        }

    @staticmethod
    def _can_pickle(value: Any) -> bool:
        try:
            dill.dumps(value, recurse=True)
            return True
        except Exception:
            return False
