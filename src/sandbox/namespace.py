"""Sandbox namespace bootstrap and persistence across `execute()` calls.

Each `execute()` runs in a brand-new `multiprocessing.Process`, so
"variables persist between calls" has to mean something concrete here:
the namespace is serialized with `dill` at the end of one call and
restored into the next process at the start of the next one.
"""

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

    def _final_answer(self, answer: Any) -> None:
        """Placeholder satisfying the mixin's attribute type; see `core.py`.

        The real implementation (raising `Sandbox._FinalAnswer`) lives on
        `Sandbox` itself — this stub only exists so type checkers see a
        `_final_answer` method on the mixin.
        """

    def _save_namespace(self, namespace: dict[str, Any]) -> bytes:
        """Serialize a namespace with `dill`.

        Args:
            namespace: The dict to serialize (typically already filtered
                down to just the user's persisted variables).

        Returns:
            The `dill`-pickled bytes, ready to hand to the next worker
            process.
        """
        return dill.dumps(namespace, recurse=True)

    @staticmethod
    def _restore_namespace(
        namespace: dict[str, Any], namespace_save: bytes
    ) -> None:
        """Unpickle a saved namespace into a fresh worker's namespace.

        Args:
            namespace: The new process's namespace dict, updated in place.
            namespace_save: Bytes produced by an earlier `_save_namespace`.

        Rebinds any restored function's `__globals__` to this namespace
        (`dill` restores the function object, but its globals still point
        at the pickling process's dict) so a function defined in a
        previous call can see variables (re)defined in this one.
        """
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
        """Strip transient entries out of a namespace and serialize it.

        Args:
            namespace: The worker's namespace after running the user's
                code.
            tool_names: Names of the MCP tool proxies injected for this
                call — these (plus the resource/prompt proxies,
                `final_answer`, and the builtins/`__name__` bootstrap
                keys) are rebuilt fresh every call, so they're dropped
                here rather than persisted.

        Returns:
            A `(saved_bytes, note)` pair: the `dill`-serialized remaining
            namespace, and either an empty string or a note appended to
            `ExecutionResult.stderr` when some variable couldn't be
            pickled at all and had to be silently dropped.
        """
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
        """Build the namespace a brand-new sandbox session starts from.

        Returns:
            A dict with a restricted `__builtins__` (only names in
            `config.authorized_builtins`, with `open`/`__import__`
            swapped for the restricted versions when authorized),
            `__name__` set to a sandbox marker, and `final_answer`
            already bound.
        """
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
        """Check whether `value` survives a `dill` round-trip.

        Args:
            value: The candidate namespace value.

        Returns:
            True if `dill.dumps` succeeds on it, False otherwise.
        """
        try:
            dill.dumps(value, recurse=True)
            return True
        except Exception:
            return False
