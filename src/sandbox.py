from __future__ import annotations

import argparse
import ast
import builtins
import json
import os
import resource
import signal
import socket
import sys
import tempfile
import threading
import time
import types
from collections.abc import Callable
from contextlib import redirect_stderr, redirect_stdout
from multiprocessing import Process, Queue
from queue import Empty
from types import FrameType
from typing import IO, Any

import dill
from mcp import MCPError
from mcp_types import BlobResourceContents, TextResourceContents, Tool

from schemas import ExecutionResult, SandboxConfig
from schemas.contract_model import SandboxProtocol
from src.mcp_client import MCPClient
from src.mcp_sync_client import SyncMCPClient


class Sandbox(SandboxProtocol):
    class _FinalAnswer(Exception):
        def __init__(self, value: Any) -> None:
            self.value = value

    def __init__(
        self,
        url: str | None = None,
        server_path: str | None = None,
        config: SandboxConfig = None,
    ) -> None:
        if config:
            self.config = config
        else:
            self.config = SandboxConfig()
        self.mcp_client: MCPClient | None = (
            MCPClient(url=url, server_path=server_path)
            if (url or server_path)
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
        self._tool_param_names: dict[str, list[str]] = {
            tool.name: list((tool.input_schema.get("properties") or {}).keys())
            for tool in self._tools
        }
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
    def proxy_list_resources(
        request_q: Queue[Any],
        response_q: Queue[Any],
        generation_nb: int,
    ) -> list[str]:
        def list_resources() -> list[str]:
            request_q.put((generation_nb, "list_resources", None, None))
            generation_nb_rslt, success, payload = response_q.get()
            while generation_nb_rslt != generation_nb:
                generation_nb_rslt, success, payload = response_q.get()
            if not success:
                raise RuntimeError(
                    f"Error: Couldnt list resources. "
                    f"Execution failed: {payload}"
                )
            return payload

        return list_resources

    @staticmethod
    def proxy_get_resource(
        request_q: Queue[Any],
        response_q: Queue[Any],
        generation_nb: int,
    ) -> callable[[str], bytes]:
        def get_resource(resource_name: str) -> bytes:
            request_q.put((generation_nb, "get_resource", resource_name, None))
            generation_nb_rslt, success, payload = response_q.get()
            while generation_nb_rslt != generation_nb:
                generation_nb_rslt, success, payload = response_q.get()
            if not success:
                raise RuntimeError(
                    f"Error: Couldnt get resource '{resource_name}'"
                    f". Execution failed: {payload}"
                )
            return payload

        return get_resource

    @staticmethod
    def proxy_list_prompts(
        request_q: Queue[Any],
        response_q: Queue[Any],
        generation_nb: int,
    ) -> callable[[], list[str]]:
        def list_prompts() -> list[str]:
            request_q.put((generation_nb, "list_prompts", None, None))
            generation_nb_rslt, success, payload = response_q.get()
            while generation_nb_rslt != generation_nb:
                generation_nb_rslt, success, payload = response_q.get()
            if not success:
                raise RuntimeError(
                    f"Error: Couldnt list prompts. Execution failed: {payload}"
                )
            return payload

        return list_prompts

    @staticmethod
    def proxy_get_prompt(
        request_q: Queue[Any],
        response_q: Queue[Any],
        generation_nb: int,
    ) -> callable[[str], str]:
        def get_prompt(prompt_name: str) -> str:
            request_q.put((generation_nb, "get_prompt", prompt_name, None))
            generation_nb_rslt, success, payload = response_q.get()
            while generation_nb_rslt != generation_nb:
                generation_nb_rslt, success, payload = response_q.get()
            if not success:
                raise RuntimeError(
                    f"Error: Couldnt get prompt '{prompt_name}'."
                    f" Execution failed: {payload}"
                )
            return payload

        return get_prompt

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

    def _bridge_loop(self) -> None:
        if self.sync_client is None:
            return

        while True:
            item = self._mcp_requests.get()
            if item is None:
                break
            generation_nb, mcp_function, name, kwargs = item
            if generation_nb < self.generation_nb:
                continue
            try:
                with self._mcp_lock:
                    self._mcp_active_since = time.monotonic()
                success, payload = self._execute_mcp_call(
                    mcp_function, name, kwargs
                )
                self._mcp_responses.put((generation_nb, success, payload))
            except MCPError as e:
                self._mcp_responses.put((generation_nb, False, str(e)))
            except Exception as e:
                self._mcp_responses.put((generation_nb, False, str(e)))
            finally:
                with self._mcp_lock:
                    self._mcp_wait_total += (
                        time.monotonic() - self._mcp_active_since
                    )
                    self._mcp_active_since = None

    def _execute_mcp_call(
        self, mcp_function: str, name: str, kwargs: dict[str, Any]
    ) -> tuple[bool, Any]:
        match mcp_function:
            case "use_tool":
                rslt = self.sync_client.use_tool(name, kwargs)
                text = rslt.content[0].text if rslt.content else None
                if rslt.is_error:
                    return False, text or "Tool error"
                return True, text
            case "list_resources":
                return True, self.sync_client.get_resources_list()
            case "list_prompts":
                return True, self.sync_client.get_prompt_list()
            case "get_resource":
                content = self.sync_client.get_resource(name)[0]
                return True, self._extract_resource_text(content)
            case "get_prompt":
                return True, str(self.sync_client.get_prompt(name).messages)
            case _:
                return False, f"Error: Unknown MCP operation '{mcp_function}'."

    @staticmethod
    def _extract_resource_text(
        content: TextResourceContents | BlobResourceContents,
    ) -> str | None:
        if isinstance(content, TextResourceContents):
            return content.text
        if isinstance(content, BlobResourceContents):
            return content.blob
        return None

    @staticmethod
    def _make_tool_proxy(
        name: str,
        request_q: Queue[Any],
        response_q: Queue[Any],
        generation_nb: int,
        tool_param_names: dict[str, list[str]],
    ) -> Callable[..., Any]:
        def proxy(*args: Any, **kwargs: Any) -> Any:
            params: list[str] = tool_param_names.get(name, [])
            if len(args) > len(params):
                raise TypeError(f"Error: Too many args for {name}.")
            args_kw = dict(zip(params, args))
            if args_kw.keys() & kwargs.keys():
                raise TypeError(
                    f"Error: Multipule values for the same kw in {name}."
                )
            kwargs = {**args_kw, **kwargs}

            request_q.put((generation_nb, "use_tool", name, kwargs))
            generation_nb_rslt, success, payload = response_q.get()
            while generation_nb_rslt != generation_nb:
                generation_nb_rslt, success, payload = response_q.get()
            if not success:
                raise RuntimeError(
                    f"Error: Tool '{name}' execution failed: {payload}"
                )
            return payload

        return proxy

    def _save_namespace(self, namespace: dict[str, Any]) -> bytes:
        return dill.dumps(namespace, recurse=True)

    @staticmethod
    def _restore_namespace(
        namespace: dict[str, Any], namespace_save: bytes
    ) -> None:
        namespace.update(dill.loads(namespace_save))
        for key, value in list(namespace.items()):
            if isinstance(value, types.FunctionType):
                namespace[key] = types.FunctionType(
                    value.__code__,
                    namespace,
                    value.__name__,
                    value.__defaults__,
                    value.__closure__,
                )

    def _persist_namespace(
        self, namespace: dict[str, Any], tool_names: list[str]
    ) -> tuple[bytes, str]:
        live_keys = (
            set(tool_names)
            | {
                "list_resources",
                "get_resource",
                "list_prompts",
                "get_prompt",
            }
            | {
                "final_answer",
                "__builtins__",
                "__name__",
            }
        )
        persisted = {k: v for k, v in namespace.items() if k not in live_keys}
        try:
            return self._save_namespace(persisted), ""
        except Exception:
            pickable = {
                k: v for k, v in persisted.items() if self._can_pickle(v)
            }
            return (
                self._save_namespace(pickable),
                "\n[Note: some variables could not be persisted]",
            )

    def _make_initial_namespace(self) -> dict[str, Any]:
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
        raise PermissionError(
            "Error: Network access is disabled in the sandbox."
        )

    def _final_answer(self, answer: Any) -> None:
        raise self._FinalAnswer(answer)

    @staticmethod
    def _can_pickle(value: Any) -> bool:
        try:
            dill.dumps(value, recurse=True)
            return True
        except Exception:
            return False

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
            self._restore_namespace(namespace, namespace_save)

        for name in tool_names:
            namespace[name] = self._make_tool_proxy(
                name,
                tool_requests,
                tool_responses,
                generation_nb,
                tool_param_names,
            )
        if self.mcp_client:
            namespace["list_resources"] = self.proxy_list_resources(
                tool_requests,
                tool_responses,
                generation_nb,
            )
            namespace["get_resource"] = self.proxy_get_resource(
                tool_requests,
                tool_responses,
                generation_nb,
            )
            namespace["list_prompts"] = self.proxy_list_prompts(
                tool_requests,
                tool_responses,
                generation_nb,
            )
            namespace["get_prompt"] = self.proxy_get_prompt(
                tool_requests,
                tool_responses,
                generation_nb,
            )

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

    def _format_tool(self, tool: Tool) -> str:
        description: str = ""
        schema = tool.input_schema or {}
        properties = schema.get("properties", {})
        required = set(schema.get("required", []))

        params: list[Any] = []
        for name, prop in properties.items():
            param_type = prop.get("type", "unknown")
            required_str = " (required)" if name in required else ""
            params.append(f"{name}: {param_type}{required_str}")
        signature = f"{tool.name}({', '.join(params)})"
        if tool.description:
            description = tool.description.split("\n\n", 1)[0]
            description = description.replace("\n", " ").strip()
        else:
            description = "No description provided."
        return f"{signature} - {description}"

    def get_manual(self) -> str:
        tools_section: str = ""
        base: str = (
            f"Manual for the sandbox environment. "
            f"{self.config.max_execution_time_seconds} seconds max "
            f"execution time, {self.config.max_memory_mb} MB max memory. "
            f"Authorized imports: {self.config.authorized_imports}. "
            f"Authorized builtins: {self.config.authorized_builtins}. "
            f"Authorized attributes: {self.config.authorized_attributes}. "
            f"Authorized file path: {self.config.allowed_directories}. "
            f"{self.config.max_output_length} characters max output. "
            "No network access is allowed. "
            "Variables persist across execute() calls within the same session."
            " Do not assume a clean namespace after a failed execution."
            " You can use the final_answer(value) function to"
            " return a final answer from your code. But it must be a string "
            "or convertible to a string."
        )
        if self._tools:
            tools_section = (
                " Available MCP tools (call them directly as "
                "Python functions with keyword arguments):\n"
            )
            for tool in self._tools:
                tools_section += f"  - {self._format_tool(tool)}\n"
        if self.mcp_client:
            tools_section += (
                " You can use list_resources(), get_resource(uri), "
                "list_prompts(), and get_prompt(name) to access more"
                " data from the MCP server."
            )

        return f"{base}\n\n{tools_section}"

    def close(self) -> None:
        if self.mcp_client:
            self._mcp_requests.put(None)
            self.bridge_thread.join(timeout=1)
        if self.sync_client is not None:
            self.sync_client.stop()


def main() -> None:
    parser = argparse.ArgumentParser(prog="sandbox")
    parser.add_argument(
        "config",
        nargs="?",
        default=None,
        help="Path to a JSON SandBoxConfig file.",
    )
    parser.add_argument(
        "--mcp-stdio",
        default=None,
        help="Command to launch an MCP server over stdio.",
    )
    parser.add_argument(
        "--mcp-server",
        default=None,
        help="URL of an MCP server to connect to.",
    )
    sandbox: SandboxProtocol
    args = parser.parse_args()
    if args.config:
        try:
            with open(args.config, "r") as f:
                config = SandboxConfig(**json.load(f))
        except Exception as e:
            print(f"Error loading config: {e}", file=sys.stderr)
            return
        sandbox = Sandbox(
            config=config, server_path=args.mcp_stdio, url=args.mcp_server
        )
    else:
        sandbox = Sandbox(server_path=args.mcp_stdio, url=args.mcp_server)
    try:
        # TODO voir pour tester avec du code avec des fonctions de plusieurs
        # lignes avec codeop ? ou code.InteractiveConsole ?
        print(
            "\nSandbox REPL. Enter the code you need to execute. Each line "
            "will be executed and remenbered. Type 'exit' to exit."
        )
        while True:
            line_of_code = input(">>>")
            if line_of_code.strip() == "exit":
                raise KeyboardInterrupt
            print(sandbox.execute(line_of_code), "\n")
    except (KeyboardInterrupt, EOFError):
        print("\nExiting.")
    except Exception as e:
        print(f"\nError in sandbox: {e}", file=sys.stderr)
    finally:
        sandbox.close()
