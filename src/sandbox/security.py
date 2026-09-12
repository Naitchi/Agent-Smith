from __future__ import annotations

import ast
import builtins
import os
import sys
import types
from collections.abc import Callable
from typing import IO, Any


class SandboxSecurityMixin:
    """Enforces the sandbox's import, attribute and filesystem allowlists."""

    def _restricted_import(
        self,
        name: str,
        globals: dict[str, object] | None = None,
        locals: dict[str, object] | None = None,
        fromlist: tuple[str, ...] = (),
        level: int = 0,
    ) -> types.ModuleType:
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
        raise PermissionError(
            "Error: Network access is disabled in the sandbox."
        )
