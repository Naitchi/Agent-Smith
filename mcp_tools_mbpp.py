"""MCP server exposing MBPP tools.

Runs candidate solutions to "Mostly Basic Python Problems" tasks against
their test assertions inside an isolated child process, and exposes the
result through an MCP ``run_tests`` tool over stdio or streamable HTTP.
"""

from __future__ import annotations

import argparse
import ast
import json
import signal
import sys
import tempfile
from contextlib import redirect_stderr, redirect_stdout
from multiprocessing import Process, Queue
from queue import Empty
from types import FrameType
from typing import IO

from mcp.server import MCPServer
from pydantic import BaseModel

from schemas.mbpp_task_Input import MBPPTaskInput


class ResultMBPPTests(BaseModel):
    """Aggregated outcome of a ``run_tests`` call.

    Attributes:
        success: True only if every assertion in the test list passed.
        output: Human-readable report: first failing test (if any) followed
            by captured stdout/stderr.
    """

    success: bool = False
    output: str = ""


class ResultMBPPTest(BaseModel):
    """Outcome of a single test assertion.

    Attributes:
        success: True if the assertion executed without raising.
        error: The failing assertion source, or the exception message.
        error_type: Exception class name (e.g. ``"AssertionError"``), or
            None when the test passed.
    """

    success: bool = False
    error: str | None = None
    error_type: str | None = None


class ResultMBPPWorker(BaseModel):
    """Raw results collected by the child worker process.

    Attributes:
        tests: Per-assertion results, in execution order.
        stdout: Text written to stdout by the candidate code (truncated).
        stderr: Text written to stderr by the candidate code (truncated).
    """

    tests: list[ResultMBPPTest] = []
    stdout: str = ""
    stderr: str = ""


class MCPServerMBPP:
    def __init__(
        self,
        task: MBPPTaskInput | None = None,
        timeout: int = 30,
        max_std_length: int = 1500,
    ):
        """Build the MCP server and register its tools, resources, prompt.

        Args:
            task: Optional task the server was started for. When set, its
                ``test_imports`` and ``test_list`` are used as defaults and
                exposed through the ``mbpp://task`` resource.
            timeout: Wall-clock limit, in seconds, for one ``run_tests``
                execution before the worker process is killed.
            max_std_length: Maximum number of characters of captured
                stdout/stderr kept in the result before truncation.
        """
        self.task = task
        self.timeout_timer = timeout
        self.max_std_length = max_std_length
        self.mcp = MCPServer("MBPP-tools")
        self.register_tools()
        self.register_resources()
        self.register_prompt()

    def register_prompt(self):
        """Register the MCP prompt that guides an LLM through an MBPP task.

        The prompt describes the Thought -> Code -> Observation loop, the
        available tools, and how to submit a solution with ``final_answer``.
        """

        @self.mcp.prompt()
        def mbpp_methodology() -> str:
            """Give a prompt about the methodology to solve MBPP tasks"""
            return (
                "You are solving a Mostly Basic Python Problems (MBPP) "
                "task, using the Thought -> Code -> Observation loop.\n\n"
                '1. Fetch the task with get_resource("mbpp://task"). It '
                "returns the task description, the expected function "
                "signature, and (when available) the test imports and "
                "test list.\n"
                "2. Write a Python implementation that satisfies the "
                "described function signature.\n"
                "3. Validate your code with check_syntax(code=...) before "
                "running the tests, to catch syntax errors early and save "
                "an iteration.\n"
                "4. Run your candidate solution with run_tests(code=...). "
                "You can omit test_list: it falls back to the task's own "
                "tests automatically. The tool returns "
                '{"success": bool, "output": str} as JSON — on '
                'failure, "output" holds the first failing assertion '
                "plus any captured stdout/stderr.\n"
                "5. If a test fails, use that output to revise your code "
                "and try again.\n"
                '6. Once run_tests reports "success": true, submit your '
                "final answer by calling final_answer(your_solution_code) "
                "— pass the raw Python source of your solution as a "
                "string, not a patch or an explanation.\n\n"
                "Repeat Thought (what to try next), Code (what you send "
                "to the sandbox), and Observation (the tool's output) "
                "until the tests pass."
            )

    def register_resources(self):
        """Register the ``mbpp://task`` resource.

        Exposes the current task as a JSON document, or ``"{}"`` when the
        server was started without a task.
        """

        @self.mcp.resource(
            "mbpp://task", name="task", mime_type="application/json"
        )
        def get_task() -> str:
            """The MBPP task the server is solving, as a JSON object.

            Returns the serialized ``MBPPTaskInput`` (task_id,
            task_definition, function_definition, test_imports, test_list),
            or ``"{}"`` when the server was started without a task.
            """
            if self.task:
                return self.task.model_dump_json()
            else:
                return "{}"

    def register_tools(self):
        """Register the MBPP MCP tools on the server.

        Registers:
            run_tests: Execute a candidate solution against test assertions.
            check_syntax: Parse a code string and report syntax errors.
        """

        @self.mcp.tool()
        def run_tests(code: str, test_list: list[str] | None = None) -> str:
            """Run a candidate solution against test assertions.

            Args:
                code: Python source defining the required function(s).
                test_list: ``assert`` statements to run against ``code``.
                    When None, falls back to the server task's test list.

            Returns:
                A JSON string ``{"success": bool, "output": str}``.
                ``success`` is True only if every assertion passed;
                ``output`` holds the first failing test and any captured
                stdout/stderr, or an error message on syntax error or crash.
            """
            if test_list is None and self.task and self.task.test_list:
                test_list = self.task.test_list
            if test_list is None or len(test_list) == 0:
                return json.dumps(
                    {"success": False, "output": "No tests to run."}
                )
            if self.task and self.task.test_imports:
                code = "\n".join(self.task.test_imports) + "\n" + code
            try:
                ast.parse(code)
            except SyntaxError as e:
                return json.dumps({"success": False, "output": str(e)})
            test_result = self.execute_test(code, test_list)
            return test_result.model_dump_json()

        @self.mcp.tool()
        def check_syntax(code: str) -> str:
            """Check whether a code string is syntactically valid Python.

            Args:
                code: The Python source to parse.

            Returns:
                ``"ok"`` if the code parses, otherwise the ``SyntaxError``
                message.
            """
            try:
                ast.parse(code)
                return "ok"
            except SyntaxError as e:
                return str(e)

    @staticmethod
    def _timeout_handler(signum: int, frame: FrameType | None) -> None:
        """Signal handler that converts a termination signal into an error.

        Args:
            signum: The signal number received (expected: ``SIGTERM``).
            frame: The interrupted stack frame, unused.

        Raises:
            TimeoutError: Always, so the worker unwinds and reports partial
                results instead of dying silently.
        """
        raise TimeoutError

    def _get_stdout_stderr(
        self,
        temp_stdout: IO[str],
        temp_stderr: IO[str],
    ) -> tuple[str, str]:
        """Read and truncate the captured output streams.

        Args:
            temp_stdout: Open temporary file holding captured stdout.
            temp_stderr: Open temporary file holding captured stderr.

        Returns:
            A ``(stdout, stderr)`` tuple, each truncated to
            ``max_std_length`` characters with a trailing ``"..."`` when
            content was cut.
        """
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
        test_list: list[str],
        queue: Queue[ResultMBPPWorker],
        temp_stdout: IO[str],
        temp_stderr: IO[str],
    ) -> None:
        """Execute the candidate code and every test in a worker process.

        Runs in a separate process. Each test is executed as
        ``exec(code + "\\n" + test)``; failures are recorded per test
        rather than aborting the batch. On ``SIGTERM`` (timeout) the
        results gathered so far are still delivered.

        Args:
            code: Python source defining the function(s) under test.
            test_list: ``assert`` statements to execute.
            queue: Channel used to send the ``ResultMBPPWorker`` back to
                the parent process.
            temp_stdout: Temporary file receiving redirected stdout.
            temp_stderr: Temporary file receiving redirected stderr.
        """
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
                        result.error = (
                            "execution timed out (possible infinite loop)"
                        )
                        result.error_type = "TimeoutError"
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

    def execute_test(self, code: str, test_list: list[str]) -> ResultMBPPTests:
        """Run the tests in a child process under a wall-clock timeout.

        Spawns :meth:`_run_tests`, waits up to ``timeout`` seconds, then
        terminates and kills the process if still alive.

        Args:
            code: Python source defining the function(s) under test.
            test_list: ``assert`` statements to execute.

        Returns:
            A :class:`ResultMBPPTests`. ``success`` is False when the
            worker crashed or timed out before producing a result.
        """
        q: Queue[ResultMBPPWorker] = Queue()
        with (
            tempfile.TemporaryFile(mode="w+", buffering=1) as temp_stderr,
            tempfile.TemporaryFile(mode="w+", buffering=1) as temp_stdout,
        ):
            p = Process(
                target=self._run_tests,
                args=(
                    code,
                    test_list,
                    q,
                    temp_stdout,
                    temp_stderr,
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
            except (TimeoutError, Empty):
                stdout, stderr = self._get_stdout_stderr(
                    temp_stdout, temp_stderr
                )
                result = ResultMBPPTests(
                    success=False,
                    output=(
                        "Process ended without producing a result (crash or"
                        " timeout)"
                    ),
                )
                if stdout:
                    result.output += f"\n---- stdout ----\n{stdout}\n"
                if stderr:
                    result.output += f"\n---- stderr ----\n{stderr}\n"
                return result
            result_worker.stdout, result_worker.stderr = (
                self._get_stdout_stderr(temp_stdout, temp_stderr)
            )
        return self._change_to_final_result(result_worker, test_list)

    def _change_to_final_result(
        self, result_worker: ResultMBPPWorker, test_list: list[str]
    ) -> ResultMBPPTests:
        """Fold raw worker results into the public ``run_tests`` result.

        Args:
            result_worker: Per-test results and captured output from the
                worker process.
            test_list: The assertions that were requested, used to detect
                a short (crashed) run.

        Returns:
            A :class:`ResultMBPPTests` whose ``success`` is True only if
            every requested assertion ran and passed, and whose ``output``
            reports the first failure plus any captured stdout/stderr.
        """
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

        if final_result.success:
            final_result.output += (
                "No tests to run.\n"
                if len(test_list) == 0
                else (
                    f"Test {len(result_worker.tests)}/{len(test_list)} "
                    "passed!\n"
                )
            )
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
    parser = argparse.ArgumentParser(prog="server-mbpp")
    parser.add_argument(
        "--task-file",
        default=None,
        help="Path to a JSON task file.",
    )
    parser.add_argument(
        "--http",
        default=False,
        action="store_true",
        help="Command to launch an MCP server with http.",
    )
    parser.add_argument(
        "--host",
        default="localhost",
        help="host to bind the server to (default: localhost)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8080,
        help="Config the port to bind the server to (default: 8080).",
    )
    args = parser.parse_args()

    task = None
    if args.task_file:
        try:
            with open(args.task_file) as f:
                task_data = json.load(f)
            task = MBPPTaskInput.model_validate(task_data)
        except Exception as e:
            print(f"Error loading task file: {e}", file=sys.stderr)
            sys.exit(1)
    server = MCPServerMBPP(task=task)

    if args.http:
        server.mcp.run("streamable-http", host=args.host, port=args.port)
    else:
        server.mcp.run()
