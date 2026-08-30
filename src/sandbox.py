from __future__ import annotations

from contextlib import redirect_stdout, redirect_stderr
from typing import Any, Callable, Dict, IO, Optional
from multiprocessing import Process, Queue
from types import FrameType
from queue import Empty
import tempfile
import builtins
import resource
import signal
import socket
import types
import dill
import time
import ast
import sys
import os

from schemas import ExecutionResult
from schemas import SandboxConfig


class Sandbox:
    class _FinalAnswer(Exception):
        def __init__(self, value: Any) -> None:
            self.value = value

    def __init__(self, config: SandboxConfig = SandboxConfig()) -> None:
        self.config = config
        self._namespace: Dict[str, Any] = self._make_initial_namespace()
        self._namespace_save: Optional[bytes] = None

    def _restricted_import(
        self,
        name: str,
        globals: Dict[str, object] | None = None,
        locals: Dict[str, object] | None = None,
        fromlist: tuple[str, ...] = (),
        level: int = 0,
    ) -> types.ModuleType:
        if "." in name:
            if f"{name.split('.')[0]}.*" not in self.config.authorized_imports:
                raise ImportError(f"Import of module '{name}' is not allowed.")
        else:
            if name not in self.config.authorized_imports:
                raise ImportError(f"Import of module '{name}' is not allowed.")
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
                f"Import of module/s {', '.join(unauthorized)} is not allowed."
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
        raise PermissionError(f"Access to file '{file}' is not allowed.")

    def _save_namespace(self, namespace: Dict[str, Any]) -> bytes:
        return dill.dumps(namespace)

    def _make_initial_namespace(self) -> Dict[str, Any]:
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

    def _check_disallowed_attributes(self, node: ast.AST) -> bool:
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr.startswith("__")
            and node.func.attr not in self.config.authorized_attributes
        ):
            return True
        if (
            isinstance(node, ast.Attribute)
            and node.attr.startswith("__")
            and node.attr not in self.config.authorized_attributes
        ):
            return True
        return False

    def _is_code_not_safe(self, code: str) -> bool:
        try:
            tree = ast.parse(code)
        except SyntaxError:
            return True

        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
            ) or isinstance(node, ast.Attribute):
                node = self._check_disallowed_attributes(node)
                if node:
                    return True
        return False

    @staticmethod
    def _timeout_handler(signum: int, frame: FrameType | None) -> None:
        raise TimeoutError

    def _get_stdout_stderr(
        self,
        temp_stdout: IO[str],
        temp_stderr: IO[str],
    ) -> tuple[str, str, bool]:
        temp_stdout.seek(0)
        temp_stderr.seek(0)
        content_stdout = temp_stdout.read()
        content_stderr = temp_stderr.read()
        stdout: str = content_stdout[: self.config.max_output_length]
        stderr: str = content_stderr[: self.config.max_output_length]
        truncated: bool = (
            len(content_stdout) > self.config.max_output_length
            or len(content_stderr) > self.config.max_output_length
        )
        return stdout, stderr, truncated

    @staticmethod
    def _blocked_call(*args: Any, **kwargs: Any) -> None:
        raise PermissionError("Network access is disabled in the sandbox.")

    def _final_answer(self, answer: Any) -> None:
        raise self._FinalAnswer(answer)

    def _worker(
        self,
        code: str,
        namespace: Dict[str, Any],
        namespace_save: Optional[bytes],
        queue: Queue[tuple[ExecutionResult, bytes]],
        temp_stderr: IO[str],
        temp_stdout: IO[str],
    ) -> None:
        socket.socket = self._blocked_call
        signal.signal(signal.SIGTERM, self._timeout_handler)
        limit_bytes = self.config.max_memory_mb * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_AS, (limit_bytes, limit_bytes))
        resource.setrlimit(
            resource.RLIMIT_NPROC,
            (self.config.max_processes, self.config.max_processes),
        )
        resource.setrlimit(
            resource.RLIMIT_NOFILE,
            (self.config.max_open_files, self.config.max_open_files),
        )
        if namespace_save is not None:
            namespace.update(dill.loads(namespace_save))

        start = time.time()
        result = ExecutionResult()
        try:
            with redirect_stdout(temp_stdout), redirect_stderr(temp_stderr):
                exec(code, namespace)
        except self._FinalAnswer as fa:
            try:
                result.final_answer = str(fa.value)
            except Exception:
                result.final_answer = (
                    "final_answer value could not be converted to string"
                )
        except TimeoutError:
            result.error = "Execution timed out."
            result.timed_out = True
            result.duration_ms = self.config.max_execution_time_seconds * 1000
        except MemoryError:
            result.error = "Memory limit exceeded."
        except Exception as e:
            result.error = str(e)

        if not result.timed_out:
            result.duration_ms = (time.time() - start) * 1000
        result.stdout, result.stderr, result.truncated = (
            self._get_stdout_stderr(temp_stdout, temp_stderr)
        )
        temp_stderr.close()
        temp_stdout.close()
        queue.put((result, self._save_namespace(namespace)))

    def execute(self, code: str) -> ExecutionResult:
        q: Queue[tuple[ExecutionResult, bytes]] = Queue()
        temp_stderr: IO[str] = tempfile.TemporaryFile(mode="w+", buffering=1)
        temp_stdout: IO[str] = tempfile.TemporaryFile(mode="w+", buffering=1)
        p = Process(
            target=self._worker,
            args=(
                code,
                self._namespace,
                self._namespace_save,
                q,
                temp_stderr,
                temp_stdout,
            ),
        )
        result: ExecutionResult
        namespace_bytes: Optional[bytes] = None

        if self._is_code_not_safe(code):
            return ExecutionResult(
                error="Code contains disallowed operations."
            )

        p.start()
        p.join(timeout=self.config.max_execution_time_seconds)
        if p.is_alive():
            p.terminate()
            p.join(timeout=1)
            p.kill()
            try:
                result, namespace_bytes = q.get(timeout=1)
            except Empty:
                namespace_bytes = None
                result = ExecutionResult(
                    error="Execution timed out.",
                    timed_out=True,
                    duration_ms=self.config.max_execution_time_seconds * 1000,
                )
                result.stdout, result.stderr, result.truncated = (
                    self._get_stdout_stderr(temp_stdout, temp_stderr)
                )
        else:
            result, namespace_bytes = q.get()
        if namespace_bytes is not None:
            self._namespace_save = namespace_bytes
        temp_stderr.close()
        temp_stdout.close()
        return result

    def get_manual(self) -> str:
        return (
            f"Manual for the sandbox environment. "
            f"{self.config.max_execution_time_seconds} seconds max "
            f"execution time, {self.config.max_memory_mb} MB max memory. "
            f"Authorized imports: {self.config.authorized_imports}. "
            f"Authorized builtins: {self.config.authorized_builtins}. "
            f"Authorized attributes: {self.config.authorized_attributes}. "
            f"Authorized file path: {self.config.allowed_directories}. "
            f"{self.config.max_output_length} characters max output. "
            "No network access is allowed. "
            "Variables persist across execute() calls within the same session "
            "(like a REPL/notebook cell). Do not assume a clean namespace"
            " after a failed execution. To clear the namespace, call the "
            "close() method. You can use the final_answer(value) function to"
            " return a final answer from your code. But it must be a string "
            "or convertible to a string."
        )

    def close(self) -> None:
        self._namespace = self._make_initial_namespace()
        self._namespace_save = None
