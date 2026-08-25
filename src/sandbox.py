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
    class _FinalAnswer(Exception):
        def __init__(self, value: Any) -> None:
            self.value = value

    def __init__(self, config: SandboxConfig = SandboxConfig()) -> None:
        self.config = config
        self._state: Dict[str, Any] = {"final_answer": self._final_answer}

    # TODO refactor: to lower Cognitive complexity
    # and delete the malicious code
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

    def _final_answer(self, answer: Any) -> None:
        raise self._FinalAnswer(answer)

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
        except self._FinalAnswer as fa:
            stdout, stderr, truncated = self._get_stdout_stderr(
                stdout_buf, stderr_buf
            )
            try:
                answer = str(fa.value)
            except Exception:
                answer = "final_answer value could not be converted to string"
            queue.put(
                ExecutionResult(
                    stdout=stdout,
                    stderr=stderr,
                    final_answer=answer,
                    truncated=truncated,
                    duration_ms=(time.time() - start) * 1000,
                )
            )
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
        result: ExecutionResult

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
                result = q.get(timeout=1)
            except Empty:
                result = ExecutionResult(
                    error="Execution timed out.",
                    timed_out=True,
                    duration_ms=self.config.max_execution_time_seconds * 1000,
                )
        else:
            result = q.get()
        return result

    def get_manual(self) -> str:
        return (
            f"Manual for the sandbox environment."
            f"{self.config.max_execution_time_seconds} seconds max"
            f"execution time, {self.config.max_memory_mb} MB max memory."
            f"Authorized imports: {self.config.authorized_imports}."
            f"Authorized builtins: {self.config.authorized_builtins}."
            f"Authorized attributes: {self.config.authorized_attributes}."
            f"Authorized file path: {self.config.allowed_directories}."
            f"{self.config.max_output_length} characters max output."
            "No network access is allowed."
            "Variables persist across execute() calls within the same session "
            "(like a REPL/notebook cell). Do not assume a clean state after a"
            "failed execution. To clear the state, call the close() method."
            "You can use the final_answer(value) function to return a final"
            " answer from your code. But it must be a string or convertible "
            "to a string."
        )

    def close(self) -> None:
        self._state = {"final_answer": self._final_answer}
