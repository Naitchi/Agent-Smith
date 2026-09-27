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

DISALLOWED_ATTRS = frozenset(
    {
        "gi_frame",
        "gi_code",
        "gi_yieldfrom",
        "cr_frame",
        "cr_code",
        "cr_await",
        "cr_origin",
        "cr_running",
        "ag_frame",
        "ag_code",
        "ag_await",
        "ag_running",
        "f_back",
        "f_globals",
        "f_locals",
        "f_builtins",
        "f_code",
        "f_trace",
        "tb_frame",
        "tb_next",
    }
)

BLOCKED_AUDIT_EVENTS = frozenset(
    {
        "socket.connect",
        "socket.bind",
        "socket.getaddrinfo",
        "socket.gethostbyname",
        "socket.sethostname",
        "os.system",
        "os.exec",
        "os.spawn",
        "os.posix_spawn",
        "subprocess.Popen",
        "ctypes.dlopen",
        "ctypes.dlsym",
        "ctypes.dlsym/handle",
        "ctypes.call_function",
        "ctypes.set_errno",
    }
)

PYTHON_PREFIXES = tuple(
    dict.fromkeys(
        os.path.realpath(path)
        for path in (
            sys.prefix,
            sys.base_prefix,
            sys.exec_prefix,
            os.path.dirname(os.__file__),
        )
    )
)


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
        file: str | bytes,
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
        name = os.fsdecode(file)
        real_path = os.path.realpath(name)
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
            f"Error: Access to file '{name}' is not allowed."
        )

    def _attr_disallowed(self, attr: str) -> bool:
        """Return True if `attr` must not be accessed by sandbox code.

        Blocks both the frame/code/traceback introspection attributes in
        `DISALLOWED_ATTRS` and any dunder attribute not explicitly listed in
        `config.authorized_attributes`.
        """
        if attr in DISALLOWED_ATTRS:
            return True
        return attr.startswith("__") and (
            attr not in self.config.authorized_attributes
        )

    def _check_disallowed_attributes(self, node: ast.AST) -> bool:
        """Check one AST node for a disallowed-attribute sandbox escape.

        Args:
            node: An `ast.Call` (on an attribute) or `ast.Attribute` node
                from a parsed code tree.

        Returns:
            True if the node accesses a dunder attribute (e.g.
            ``__class__``, ``__bases__``, ``__subclasses__``) that isn't
            explicitly in `config.authorized_attributes` — the classic
            ``().__class__.__bases__[0].__subclasses__()`` escape route — or
            a frame/code introspection attribute from `DISALLOWED_ATTRS`.
        """
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            return self._attr_disallowed(node.func.attr)
        if isinstance(node, ast.Attribute):
            return self._attr_disallowed(node.attr)
        return False

    def _install_audit_hook(self) -> None:
        """Install the process-wide audit hook backstop.

        Called once inside the worker process, right before the untrusted
        code runs. Enforces the filesystem allowlist on every `open` (not
        just the `open` builtin, so `os.open`/`pathlib` are covered too) and
        blocks the network, process-spawn and `ctypes` audit events in
        `BLOCKED_AUDIT_EVENTS`. Because an audit hook cannot be removed, this
        holds for the rest of the worker's life — which is fine, the worker
        only serializes its namespace and exits afterwards.
        """
        allowed = tuple(self.config.allowed_directories) + PYTHON_PREFIXES

        def _open_allowed(path: Any) -> bool:
            if isinstance(path, int):
                return True
            try:
                name = os.fsdecode(path)
            except (TypeError, ValueError):
                return True
            real = os.path.realpath(name)
            return any(
                real == directory or real.startswith(f"{directory}/")
                for directory in allowed
            )

        def hook(event: str, args: tuple[Any, ...]) -> None:
            if event == "open":
                if args and not _open_allowed(args[0]):
                    raise PermissionError(
                        f"Error: Access to file '{args[0]}' is not allowed."
                    )
            elif event in BLOCKED_AUDIT_EVENTS:
                raise PermissionError(
                    f"Error: Operation '{event}' is disabled in the sandbox."
                )

        sys.addaudithook(hook)

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
