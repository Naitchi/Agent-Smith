from __future__ import annotations

from contextlib import redirect_stdout, redirect_stderr
from multiprocessing import Process, Queue
from typing import Any, Dict
from types import FrameType
from queue import Empty
import resource
import signal
import socket
import time
import ast
import io

from schemas import ExecutionResult
from schemas import SandboxConfig


class Sandbox:
    def __init__(self, config: SandboxConfig = SandboxConfig()) -> None:
        self.config = config
        self._state: Dict[str, Any] = {}

    # TODO refactor: to lower Cognitive complexity
    def _is_code_safe(self, code: str) -> bool:
        try:
            tree = ast.parse(code)
        except SyntaxError:
            return False

        for node in ast.walk(tree):
            if (
                isinstance(node, ast.ImportFrom)
                and node.module not in self.config.authorized_imports
            ):
                return False
            elif isinstance(node, ast.Call) and (
                (
                    isinstance(node.func, ast.Name)
                    and node.func.id not in self.config.authorized_builtins
                )
                or (
                    isinstance(node.func, ast.Attribute)
                    and node.func.attr not in self.config.authorized_attributes
                )
            ):
                return False
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name not in self.config.authorized_imports:
                        return False
        return True

    @staticmethod
    def _timeout_handler(signum: int, frame: FrameType | None) -> None:
        raise TimeoutError

    def _get_stdout_stderr(
        self, stdout_buf: io.StringIO, stderr_buf: io.StringIO
    ) -> tuple[str, str, bool]:
        stdout = stdout_buf.getvalue()[: self.config.max_output_length]
        stderr = stderr_buf.getvalue()[: self.config.max_output_length]
        truncated = (
            len(stdout_buf.getvalue()) > self.config.max_output_length
            or len(stderr_buf.getvalue()) > self.config.max_output_length
        )
        return stdout, stderr, truncated

    @staticmethod
    def _blocked_call(*args: Any, **kwargs: Any) -> None:
        raise PermissionError("Network access is disabled in the sandbox.")

    def _worker(
        self, code: str, state: Dict[str, Any], queue: Queue[ExecutionResult]
    ) -> None:
        socket.socket = self._blocked_call
        signal.signal(signal.SIGTERM, self._timeout_handler)
        limit_bytes = self.config.max_memory_mb * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_AS, (limit_bytes, limit_bytes))
        stderr_buf = io.StringIO()
        stdout_buf = io.StringIO()

        start = time.time()
        try:
            with redirect_stdout(stdout_buf), redirect_stderr(stderr_buf):
                exec(code, state)
        except TimeoutError:
            stdout, stderr, truncated = self._get_stdout_stderr(
                stdout_buf, stderr_buf
            )
            queue.put(
                ExecutionResult(
                    stdout=stdout,
                    stderr=stderr,
                    error="Execution timed out.",
                    timed_out=True,
                    truncated=truncated,
                    duration_ms=self.config.max_execution_time_seconds * 1000,
                )
            )
        except MemoryError:
            stdout, stderr, truncated = self._get_stdout_stderr(
                stdout_buf, stderr_buf
            )
            queue.put(
                ExecutionResult(
                    stdout=stdout,
                    stderr=stderr,
                    error="Memory limit exceeded.",
                    truncated=truncated,
                    duration_ms=(time.time() - start) * 1000,
                )
            )
        except Exception as e:
            stdout, stderr, truncated = self._get_stdout_stderr(
                stdout_buf, stderr_buf
            )
            queue.put(
                ExecutionResult(
                    stdout=stdout,
                    stderr=stderr,
                    error=str(e),
                    truncated=truncated,
                    duration_ms=(time.time() - start) * 1000,
                )
            )
        else:
            stdout, stderr, truncated = self._get_stdout_stderr(
                stdout_buf, stderr_buf
            )
            queue.put(
                ExecutionResult(
                    stdout=stdout,
                    stderr=stderr,
                    truncated=truncated,
                    duration_ms=(time.time() - start) * 1000,
                )
            )

    def execute(self, code: str) -> ExecutionResult:
        q: Queue[ExecutionResult] = Queue()
        p = Process(target=self._worker, args=(code, self._state, q))

        if not self._is_code_safe(code):
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
                q.get(timeout=1)
            except Empty:
                return ExecutionResult(
                    error="Execution timed out.",
                    timed_out=True,
                    duration_ms=self.config.max_execution_time_seconds * 1000,
                )
        return q.get()
