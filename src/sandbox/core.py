"""The Sandbox: isolated execution of LLM-generated Python code.

Each `execute()` call runs the given code in a fresh `multiprocessing.Process`
under hard resource limits (timeout, RAM, open files, process count), with
variables persisted across calls via a `dill`-serialized namespace rather
than by keeping the process itself alive. MCP tools reachable from that
namespace are proxied over a request/response Queue pair to a bridge thread
running in this (the parent) process — see `mcp_bridge.py`.
"""

from __future__ import annotations

import resource
import signal
import socket
import sys
import tempfile
import threading
import time
from collections.abc import Callable
from contextlib import redirect_stderr, redirect_stdout
from multiprocessing import Process, Queue
from queue import Empty
from types import FrameType
from typing import IO, Any

from mcp_types import Tool

from schemas import ExecutionResult, SandboxConfig
from schemas.contract_model import SandboxProtocol
from src.mcp_client import MCPClient
from src.mcp_sync_client import SyncMCPClient

from .mcp_bridge import SandboxMCPBridgeMixin
from .namespace import SandboxNamespaceMixin
from .security import SandboxSecurityMixin


class Sandbox(
    SandboxSecurityMixin,
    SandboxNamespaceMixin,
    SandboxMCPBridgeMixin,
    SandboxProtocol,
):
    """Isolated Python execution environment, wrapping an optional MCP client.

    Satisfies `SandboxProtocol`: `execute(code) -> ExecutionResult`,
    `get_manual() -> str`, `close()`. The sandbox wraps the MCP client, not
    the other way around — connecting a different MCP server changes which
    tools show up in the namespace and in `get_manual()`, with no tool name
    ever hardcoded here.
    """

    class _FinalAnswer(Exception):
        """Raised by `_final_answer` to unwind `exec()` with a final value.

        Caught in `_worker`, which turns it into
        `ExecutionResult.final_answer` — this is how `final_answer(value)`
        (always present in the namespace, independent of any MCP tool)
        stops the agent loop.
        """

        def __init__(self, value: Any) -> None:
            self.value = value

    def __init__(
        self,
        url: str | None = None,
        command_stdio: str | None = None,
        config: SandboxConfig | None = None,
    ) -> None:
        """Build the sandbox, optionally connecting an MCP server.

        Args:
            url: HTTP URL of an MCP server to connect to.
            command_stdio: Shell command launching an MCP server over
                stdio. Ignored if `url` is set. If neither `url` nor
                `command_stdio` is given, the sandbox runs with no MCP
                tools at all — `final_answer` is still available.
            config: Sandbox limits/allowlists. Defaults to
                `SandboxConfig()` (its own built-in defaults) if omitted.
        """
        if config:
            self.config = config
        else:
            self.config = SandboxConfig()
        self.mcp_client: MCPClient | None = (
            MCPClient(url=url, command_stdio=command_stdio)
            if (url or command_stdio)
            else None
        )
        self.sync_client: SyncMCPClient | None = (
            SyncMCPClient(self.mcp_client) if self.mcp_client else None
        )
        self._namespace: dict[str, Any] = self._make_initial_namespace()
        self._namespace_save: bytes | None = None
        self.generation_nb: int = 0
        self._tools: list[Tool] = []
        if self.sync_client is not None:
            try:
                self.sync_client.start()
                self._tools = self.sync_client.get_tools_list()
            except Exception as e:
                print(
                    f"Error while fetching tools: {e}",
                    file=sys.stderr,
                )
        self.tool_names: list[str] = [tool.name for tool in self._tools]
        self._tool_param_names: dict[str, list[str]] = {}
        self._tool_docs: dict[str, str] = {}
        for tool in self._tools:
            properties: dict[str, Any] = (
                tool.input_schema.get("properties") or {}
            )
            self._tool_param_names[tool.name] = list(properties.keys())
            self._tool_docs[tool.name] = tool.description or ""
        self._mcp_requests: Queue[Any] = Queue()
        self._mcp_responses: Queue[Any] = Queue()
        self._mcp_wait_total: float = 0.0
        self._mcp_active_since: float | None = None
        self._mcp_lock: threading.Lock = threading.Lock()
        if self.sync_client:
            self.bridge_thread = threading.Thread(
                target=self._bridge_loop, daemon=True
            )
            self.bridge_thread.start()

    @staticmethod
    def _timeout_handler(signum: int, frame: FrameType | None) -> None:
        """Signal handler that converts SIGTERM into a `TimeoutError`.

        Args:
            signum: The signal number received (expected: `SIGTERM`,
                sent by the parent when a worker overruns its timeout).
            frame: The interrupted stack frame, unused.

        Raises:
            TimeoutError: Always, so `_worker`'s `exec()` unwinds and
                still reports partial stdout/stderr instead of just
                dying silently.
        """
        raise TimeoutError

    def _get_stdout_stderr(
        self,
        temp_stdout: IO[str],
        temp_stderr: IO[str],
    ) -> tuple[str, str, bool]:
        """Read back and truncate the worker's captured output streams.

        Args:
            temp_stdout: Temporary file the worker's stdout was
                redirected into.
            temp_stderr: Temporary file the worker's stderr was
                redirected into.

        Returns:
            A `(stdout, stderr, truncated)` triple, each stream capped
            at `config.max_output_length` characters; `truncated` is
            True if either stream actually exceeded that length.
        """
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

    def _final_answer(self, answer: Any) -> None:
        """Implementation of the `final_answer(value)` sandbox builtin.

        Args:
            answer: The value the sandboxed code wants to submit.

        Raises:
            _FinalAnswer: Always — caught in `_worker`, which is how
                this stops the current `execute()` call and reports
                `answer` back as `ExecutionResult.final_answer`.
        """
        raise self._FinalAnswer(answer)

    def _worker(
        self,
        code: str,
        namespace: dict[str, Any],
        namespace_save: bytes | None,
        queue: Queue[tuple[ExecutionResult, bytes]],
        temp_stderr: IO[str],
        temp_stdout: IO[str],
        tool_requests: Queue[Any],
        tool_responses: Queue[Any],
        tool_names: list[str],
        generation_nb: int,
        tool_param_names: dict[str, list[str]],
        tool_docs: dict[str, str],
    ) -> None:
        """Process entry point: apply restrictions, run `code`, report back.

        Runs in a brand-new `multiprocessing.Process` spawned by
        `execute()`. Everything here executes with the sandbox's
        restrictions already active — imports, filesystem, network,
        memory/process/file-descriptor limits — before `code` itself
        ever runs.

        Args:
            code: The Python source to execute.
            namespace: The persisted namespace dict to restore into
                (from the previous call), then execute `code` against.
            namespace_save: `dill`-serialized namespace from the
                previous call, or None on the first call.
            queue: Channel to send the `(ExecutionResult, saved_bytes)`
                pair back to the parent.
            temp_stderr: Temp file `code`'s stderr is redirected into.
            temp_stdout: Temp file `code`'s stdout is redirected into.
            tool_requests: Queue this worker sends MCP tool call
                requests on.
            tool_responses: Queue this worker reads MCP tool call
                results from.
            tool_names: Names of the connected MCP server's tools —
                each gets a proxy function injected into `namespace`.
            generation_nb: This `execute()` call's generation number,
                tagged onto every tool request so late responses from a
                killed/timed-out previous call can't be misrouted here.
            tool_param_names: Tool name -> ordered parameter names, so
                proxies can accept positional arguments.
            tool_docs: Tool name -> description, propagated onto each
                proxy's `__doc__` (see `_make_tool_proxy`).
        """
        socket.socket = self._blocked_call  # type: ignore[misc, assignment]
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
            self._restore_namespace(namespace, namespace_save)

        for name in tool_names:
            namespace[name] = self._make_tool_proxy(
                name,
                tool_requests,
                tool_responses,
                generation_nb,
                tool_param_names,
                tool_docs,
            )
        if self.mcp_client:

            def make_mcp_proxy(
                factory: Callable[
                    [Queue[Any], Queue[Any], int], Callable[..., Any]
                ],
            ) -> Callable[..., Any]:
                return factory(tool_requests, tool_responses, generation_nb)

            namespace["list_resources"] = make_mcp_proxy(
                self.proxy_list_resources
            )
            namespace["get_resource"] = make_mcp_proxy(
                self.proxy_get_resource
            )
            namespace["list_prompts"] = make_mcp_proxy(
                self.proxy_list_prompts
            )
            namespace["get_prompt"] = make_mcp_proxy(self.proxy_get_prompt)

        start = time.monotonic()
        result = ExecutionResult()
        with redirect_stdout(temp_stdout), redirect_stderr(temp_stderr):
            try:
                exec(code, namespace)
            except self._FinalAnswer as fa:
                try:
                    result.final_answer = str(fa.value)
                except Exception:
                    result.final_answer = (
                        "final_answer value could not be converted to string"
                    )
            except TimeoutError:
                result.error = "Error: Execution timed out."
                result.timed_out = True
                result.duration_ms = (
                    self.config.max_execution_time_seconds * 1000
                )
            except MemoryError:
                result.error = "Error: Memory limit exceeded."
            except Exception as e:
                msg = str(e)
                result.error = (
                    msg if msg.startswith("Error:") else f"Error: {msg}"
                )

            if not result.timed_out:
                result.duration_ms = (time.monotonic() - start) * 1000
            result.stdout, result.stderr, result.truncated = (
                self._get_stdout_stderr(temp_stdout, temp_stderr)
            )
        saved, note = self._persist_namespace(namespace, tool_names)
        result.stderr += note
        queue.put((result, saved))

    def execute(self, code: str) -> ExecutionResult:
        """Run `code` in an isolated, resource-limited child process.

        Args:
            code: Python source to execute. Rejected up front (without
                even spawning a process) if it fails to parse or
                contains a disallowed dunder-attribute access.

        Returns:
            An `ExecutionResult` — `stdout`/`stderr` (possibly
            truncated), `error` (a message for the LLM if something
            went wrong), `final_answer` (set if the code called
            `final_answer(...)`), `timed_out`, and `duration_ms`. Never
            raises: a crashed or non-terminating worker still comes
            back as an `ExecutionResult` with `error` set, never an
            exception out of `execute()` itself.
        """
        rslt_icns: str | None = self._is_code_not_safe(code)
        if rslt_icns:
            return ExecutionResult(error=rslt_icns, duration_ms=0.0)

        q: Queue[tuple[ExecutionResult, bytes]] = Queue()
        with (
            tempfile.TemporaryFile(mode="w+", buffering=1) as temp_stderr,
            tempfile.TemporaryFile(mode="w+", buffering=1) as temp_stdout,
        ):
            self._mcp_wait_total = 0.0
            self.generation_nb += 1
            p = Process(
                target=self._worker,
                args=(
                    code,
                    self._namespace,
                    self._namespace_save,
                    q,
                    temp_stderr,
                    temp_stdout,
                    self._mcp_requests,
                    self._mcp_responses,
                    self.tool_names,
                    self.generation_nb,
                    self._tool_param_names,
                    self._tool_docs,
                ),
            )
            result: ExecutionResult
            namespace_bytes: bytes | None = None
            did_timeout: bool = False

            p.start()
            did_timeout = self._wait_for_worker(p)
            try:
                result, namespace_bytes = q.get(timeout=5)
                self._namespace_save = namespace_bytes
            except Empty:
                namespace_bytes = None
                result = ExecutionResult(
                    error=(
                        "Error: Execution timed out."
                        if did_timeout
                        else (
                            "Error: Sandbox process died"
                            " without returning a result."
                        )
                    ),
                    timed_out=did_timeout,
                    duration_ms=self.config.max_execution_time_seconds * 1000,
                )
                result.stdout, result.stderr, result.truncated = (
                    self._get_stdout_stderr(temp_stdout, temp_stderr)
                )
            finally:
                p.close()
                q.close()
        return result

    def _wait_for_worker(self, p: Process) -> bool:
        """Wait for the worker, enforcing the timeout net of MCP wait time.

        Args:
            p: The worker process to wait on.

        Returns:
            True if the worker had to be force-killed (`terminate()`
            then `kill()`) for overrunning `max_execution_time_seconds`;
            False if it finished on its own.

        Time spent blocked on an MCP tool call (tracked via
        `_mcp_wait_total`/`_mcp_active_since`, updated by the bridge
        thread) is subtracted from the elapsed time before comparing
        against the limit — MCP tool calls run outside the sandbox and
        aren't subject to its timeout, so a legitimately slow tool
        (e.g. `run_tests` pulling a Docker image) doesn't cause a false
        timeout here.
        """
        offset: float = 0.0
        start: float = time.monotonic()
        while p.is_alive():
            with self._mcp_lock:
                offset = self._mcp_wait_total
                if self._mcp_active_since:
                    offset += time.monotonic() - self._mcp_active_since
            if (
                time.monotonic() - start
            ) - offset >= self.config.max_execution_time_seconds:
                break
            p.join(timeout=0.1)
        if p.is_alive():
            p.terminate()
            p.join(timeout=1)
            p.kill()
            p.join(timeout=1)
            return True
        return False

    def close(self) -> None:
        """Tear down the MCP connection and bridge thread, if any.

        Safe to call even when no MCP server was ever connected. Should
        be called exactly once, when the sandbox itself is done with
        (e.g. from the agent CLI's `finally`, or the REPL's).
        """
        if self.mcp_client:
            self._mcp_requests.put(None)
            self.bridge_thread.join(timeout=1)
        if self.sync_client is not None:
            self.sync_client.stop()
