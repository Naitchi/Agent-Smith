"""Sandbox security primitives: import, filesystem and attribute allowlists.

Everything here is stdlib-only (no `RestrictedPython` or similar) and runs
inside the worker process, on the LLM-generated code it's asked to execute.
"""

from __future__ import annotations

import ast
import builtins
import os
import sys
import types
from collections.abc import Callable
from typing import IO, Any

from schemas.sandbox_config import SandboxConfig


class SandboxSecurityMixin:
    """Enforces the sandbox's import, attribute and filesystem allowlists."""

    config: SandboxConfig

    def _restricted_import(
        self,
        name: str,
        globals: dict[str, object] | None = None,
        locals: dict[str, object] | None = None,
        fromlist: tuple[str, ...] = (),
        level: int = 0,
    ) -> types.ModuleType:
        """Import allowlist, installed in place of the `__import__` builtin.

        Args:
            name: Module being imported (e.g. ``"math"`` or ``"os.path"``).
            globals: Passed through to the real `__import__`, unused here.
            locals: Passed through to the real `__import__`, unused here.
            fromlist: Names requested via ``from name import fromlist``;
                each submodule pulled in this way is checked too.
            level: Relative-import level, passed through unchanged.

        Returns:
            The imported module, with any unauthorized submodule pulled in
            via `fromlist` stripped back out of it and `sys.modules`.

        Raises:
            ImportError: If `name` (or, for a dotted name, its top-level
                package) isn't in `config.authorized_imports` — a
                ``"pkg.*"`` entry authorizes `pkg`'s submodules too — or if
                any name in `fromlist` resolves to an unauthorized submodule.
        """
        if "." in name:
            if f"{name.split('.')[0]}.*" not in self.config.authorized_imports:
                raise ImportError(
                    f"Error: Import of module '{name}' is not allowed."
                )
        else:
            if name not in self.config.authorized_imports:
                raise ImportError(
                    f"Error: Import of module '{name}' is not allowed."
                )
        module = builtins.__import__(name, globals, locals, fromlist, level)
        unauthorized: list[str] = []
        for from_name in fromlist or ():
            attr = getattr(module, from_name, None)
            if isinstance(attr, types.ModuleType):
                sub_name = f"{name}.{from_name}"
                if f"{name}.*" not in self.config.authorized_imports:
                    delattr(module, from_name)
                    sys.modules.pop(sub_name, None)
                    unauthorized.append(sub_name)
        if unauthorized:
            raise ImportError(
                "Error: Import of module/s "
                f"{', '.join(unauthorized)} is not allowed."
            )
        return module

    def _restricted_open(
        self,
        file: str,
        mode: str = "r",
        buffering: int = -1,
        encoding: str | None = None,
        errors: str | None = None,
        newline: str | None = None,
        closefd: bool = True,
        opener: Callable[[str, int], int] | None = None,
    ) -> IO[str] | IO[bytes]:
        """Filesystem allowlist, installed in place of the `open` builtin.

        Args:
            file: Path to open.
            mode, buffering, encoding, errors, newline, closefd, opener:
                Forwarded as-is to the real `builtins.open` once `file`
                clears the allowlist check.

        Returns:
            The open file handle, exactly as `builtins.open` would return
            it.

        Raises:
            PermissionError: If `file`'s real path (after resolving `..`
                and symlinks via `os.path.realpath`, so a traversal like
                ``/testbed/../etc/passwd`` can't escape the check) isn't
                inside one of `config.allowed_directories`.
        """
        real_path = os.path.realpath(file)
        for allowed_dir in self.config.allowed_directories:
            if real_path == allowed_dir or real_path.startswith(
                f"{allowed_dir}/"
            ):
                return builtins.open(
                    file,
                    mode,
                    buffering,
                    encoding,
                    errors,
                    newline,
                    closefd,
                    opener,
                )
        raise PermissionError(
            f"Error: Access to file '{file}' is not allowed."
        )

    def _check_disallowed_attributes(self, node: ast.AST) -> bool:
        """Check one AST node for a dunder-attribute sandbox escape.

        Args:
            node: An `ast.Call` (on an attribute) or `ast.Attribute` node
                from a parsed code tree.

        Returns:
            True if the node accesses a dunder attribute (e.g.
            ``__class__``, ``__bases__``, ``__subclasses__``) that isn't
            explicitly in `config.authorized_attributes` — the classic
            ``().__class__.__bases__[0].__subclasses__()`` escape route.
        """
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr.startswith("__")
            and node.func.attr not in self.config.authorized_attributes
        ):
            return True
        return (
            isinstance(node, ast.Attribute)
            and node.attr.startswith("__")
            and node.attr not in self.config.authorized_attributes
        )

    def _is_code_not_safe(self, code: str) -> str | None:
        """Parse `code` and scan it for disallowed dunder-attribute access.

        Args:
            code: The Python source about to be executed.

        Returns:
            None if `code` parses and contains no disallowed attribute
            access; otherwise a human-readable error string (syntax error
            message, or a generic "disallowed operations" notice — this
            check runs before execution, so which particular attribute
            tripped it isn't surfaced to the caller).
        """
        try:
            tree = ast.parse(code)
        except SyntaxError as e:
            return f"Error: SyntaxError in code: {e}"

        for node in ast.walk(tree):
            if (
                (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                )
                or isinstance(node, ast.Attribute)
            ) and self._check_disallowed_attributes(node):
                return "Error: Code contains disallowed operations."
        return None

    @staticmethod
    def _blocked_call(*args: Any, **kwargs: Any) -> None:
        """Stand-in for `socket.socket` inside the worker process.

        Args:
            *args: Ignored.
            **kwargs: Ignored.

        Raises:
            PermissionError: Always — this is what makes network access
                unavailable to sandboxed code.
        """
        raise PermissionError(
            "Error: Network access is disabled in the sandbox."
        )
