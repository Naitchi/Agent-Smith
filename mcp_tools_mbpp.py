from contextlib import redirect_stderr, redirect_stdout
from multiprocessing import Process, Queue
from mcp.server import MCPServer
from pydantic import BaseModel
from typing import IO, List
from types import FrameType
from queue import Empty

import tempfile
import signal
import json
import ast

from schemas.mbpp_task_Input import MBPPTaskInput


class ResultMBPPTests(BaseModel):
    success: bool = False
    output: str = ""


class ResultMBPPTest(BaseModel):
    success: bool = False
    error: str | None = None
    error_type: str | None = None


class ResultMBPPWorker(BaseModel):
    tests: List[ResultMBPPTest] = []
    stdout: str = ""
    stderr: str = ""


class MCPServerMBPP:
    def __init__(
        self,
        task: MBPPTaskInput,
        timeout: int = 30,
        max_std_length: int = 1500,
    ):
        self.task = task
        self.timeout_timer = timeout
        self.max_std_length = max_std_length
        self.mcp = MCPServer()
        self.register_tools()

    def register_tools(self):
        @self.mcp.tool()
        def run_tests(
            code: str, test_list: list[str] = self.task.test_list
        ) -> str:
            if self.task.test_imports:
                code = self.task.test_imports + "\n" + code
            try:
                ast.parse(code)
            except SyntaxError as e:
                return json.dumps({"success": False, "output": str(e)})
            test_result = self.execute_test(code, test_list)
            return test_result.model_dump_json()

        @self.mcp.tool()
        def check_syntax(code: str) -> str:
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
        stdout: str = content_stdout[: self.max_std_length]
        stderr: str = content_stderr[: self.max_std_length]
        # TODO prendre les 700 premiers et les 700 derniers caractères pour
        # avoir un aperçu du début et de la fin
        if len(content_stdout) > self.max_std_length:
            stdout += "..."
        if len(content_stderr) > self.max_std_length:
            stderr += "..."
        return stdout, stderr

    def _run_tests(
        self,
        code: str,
        test_list: List[str],
        queue: Queue,
        temp_stdout: IO[str],
        temp_stderr: IO[str],
    ) -> None:
        signal.signal(signal.SIGTERM, self._timeout_handler)
        final_result = ResultMBPPWorker()
        try:
            with (
                redirect_stdout(temp_stdout),
                redirect_stderr(temp_stderr),
            ):
                for test in test_list:
                    result = ResultMBPPTest()
                    try:
                        exec(f"{code} \n{test}", {})
                    except AssertionError:
                        result.error = test
                        result.error_type = "AssertionError"
                    except TimeoutError:
                        raise
                    except Exception as e:
                        result.error = str(e)
                        result.error_type = e.__class__.__name__
                    else:
                        result.success = True
                    finally:
                        final_result.tests.append(result)
        except TimeoutError:
            pass
        except Exception as e:
            final_result.tests.append(
                ResultMBPPTest(
                    success=False,
                    error=str(e),
                    error_type=e.__class__.__name__,
                )
            )
        temp_stderr.close()
        temp_stdout.close()
        queue.put(final_result)

    def execute_test(self, code: str, test_list: List[str]) -> ResultMBPPTests:
        q: Queue[ResultMBPPWorker] = Queue()
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
        result_worker: ResultMBPPWorker = ResultMBPPWorker()

        p.start()
        p.join(timeout=self.timeout_timer)
        if p.is_alive():
            p.terminate()
            p.join(timeout=1)
            p.kill()
            try:
                result_worker = q.get(timeout=1)
            except Empty:
                stdout, stderr = self._get_stdout_stderr(
                    temp_stdout, temp_stderr
                )
                temp_stderr.close()
                temp_stdout.close()
                result = ResultMBPPTests(
                    success=False,
                    output="Process timed out and was terminated.",
                )
                if stdout:
                    result.output += f"\n---- stdout ----\n{stdout}\n"
                if stderr:
                    result.output += f"\n---- stderr ----\n{stderr}\n"
                return result
        else:
            result_worker = q.get()
        result_worker.stdout, result_worker.stderr = self._get_stdout_stderr(
            temp_stdout, temp_stderr
        )
        temp_stderr.close()
        temp_stdout.close()
        return self.change_to_final_result(result_worker, test_list)

    def change_to_final_result(
        self, result_worker: ResultMBPPWorker, test_list: List[str]
    ) -> ResultMBPPTests:
        final_result = ResultMBPPTests()
        final_result.success = len(result_worker.tests) == len(
            test_list
        ) and all(test.success for test in result_worker.tests)
        for key, test in enumerate(result_worker.tests, 1):
            if not test.success:
                final_result.output += f"Test {key}/{len(test_list)} failed: "
                if test.error_type:
                    final_result.output += f"{test.error_type}: "
                if test.error:
                    final_result.output += f"{test.error}\n"
                break
        if result_worker.stdout:
            final_result.output += (
                f"---- stdout ----\n{result_worker.stdout}\n"
            )
        if result_worker.stderr:
            final_result.output += (
                f"---- stderr ----\n{result_worker.stderr}\n"
            )
        return final_result


if __name__ == "__main__":
    server = MCPServerMBPP()
    server.mcp.run()
