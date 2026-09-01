# TODO faire le serveur MCP ici. Et le client avec stdio et http ?

from contextlib import redirect_stderr, redirect_stdout
from multiprocessing import Process, Queue
from mcp.server import MCPServer
from typing import IO, List
from types import FrameType
from queue import Empty

import tempfile
import signal
import time
import ast

from schemas.contract_model import RunTestsResult


class MCPServerMBPP:
    def __init__(self, timeout: int = 30):
        self.timeout_timer = timeout
        self.mcp = MCPServer()
        self.register_tools()

    def register_tools(self):
        @self.mcp.tool()
        def run_tests(code: str, test_list: list[str]) -> str:
            print(self.execute_test(code, test_list))

        @self.mcp.tool()
        def check_syntax(code) -> str:
            try:
                ast.parse(code)
                return "ok"
            except SyntaxError as e:
                return str(e)

    @staticmethod
    def _timeout_handler(signum: int, frame: FrameType | None) -> None:
        raise TimeoutError

    def _get_stdout_stderr(
        self,
        temp_stdout: IO[str],
        temp_stderr: IO[str],
    ) -> tuple[str, str]:
        temp_stdout.seek(0)
        temp_stderr.seek(0)
        content_stdout = temp_stdout.read()
        content_stderr = temp_stderr.read()
        stdout: str = content_stdout
        stderr: str = content_stderr
        return stdout, stderr

    # TODO faire un autre objet pydantic qui siait plus a nos besoins comparer
    # a ExecutionResult
    def _run_tests(
        self,
        code: str,
        test_list: List[str],
        queue: Queue,
        temp_stdout: IO[str],
        temp_stderr: IO[str],
    ) -> None:
        signal.signal(signal.SIGTERM, self._timeout_handler)
        failed: List[str] = []
        start = time.time()
        result = RunTestsResult()
        for test in test_list:
            try:
                with (
                    redirect_stdout(temp_stdout),
                    redirect_stderr(temp_stderr),
                ):
                    exec(f"{code} \n{test}")
            except AssertionError:
                failed.append(test)
            except TimeoutError:
                result.error = "Execution timed out."
                result.timed_out = True
                result.duration_ms = self.timeout_timer * 1000
            except Exception as e:
                result.error = str(e)

            if not result.timed_out:
                result.duration_ms = (time.time() - start) * 1000
            result.stdout, result.stderr = self._get_stdout_stderr(
                temp_stdout, temp_stderr
            )
        temp_stderr.close()
        temp_stdout.close()
        queue.put((result))

    def execute_test(self, code: str, test_list: List[str]) -> RunTestsResult:
        q: Queue[tuple[RunTestsResult, bytes]] = Queue()
        temp_stderr: IO[str] = tempfile.TemporaryFile(mode="w+", buffering=1)
        temp_stdout: IO[str] = tempfile.TemporaryFile(mode="w+", buffering=1)
        p = Process(
            target=self._run_tests,
            args=(
                code,
                test_list,
                q,
                temp_stderr,
                temp_stdout,
            ),
        )
        result: RunTestsResult

        p.start()
        p.join(timeout=self.timeout_timer)
        if p.is_alive():
            p.terminate()
            p.join(timeout=1)
            p.kill()
            try:
                result = q.get(timeout=1)
            except Empty:
                result = RunTestsResult(
                    error="Execution timed out.",
                    timed_out=True,
                    duration_ms=self.timeout_timer * 1000,
                )
                result.stdout, result.stderr = self._get_stdout_stderr(
                    temp_stdout, temp_stderr
                )
        else:
            result = q.get()
        temp_stderr.close()
        temp_stdout.close()
        return result
