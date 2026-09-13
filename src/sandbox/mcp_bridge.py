from __future__ import annotations

import base64
import threading
import time
from collections.abc import Callable
from multiprocessing import Queue
from typing import Any

from mcp import MCPError
from mcp_types import BlobResourceContents, TextResourceContents, Tool

from schemas.sandbox_config import SandboxConfig
from src.mcp_client import MCPClient
from src.mcp_sync_client import SyncMCPClient


class SandboxMCPBridgeMixin:
    """Bridges sandboxed code to the MCP server: tool/resource/prompt
    proxies, the request/response bridge thread, and the tool manual."""

    config: SandboxConfig
    mcp_client: MCPClient | None
    sync_client: SyncMCPClient | None
    generation_nb: int
    _tools: list[Tool]
    _mcp_requests: Queue[Any]
    _mcp_responses: Queue[Any]
    _mcp_lock: threading.Lock
    _mcp_wait_total: float
    _mcp_active_since: float | None

    @staticmethod
    def _bridge_call(
        request_q: Queue[Any],
        response_q: Queue[Any],
        generation_nb: int,
        mcp_function: str,
        arg: Any,
        error_context: str,
    ) -> Any:
        request_q.put((generation_nb, mcp_function, arg, None))
        generation_nb_rslt, success, payload = response_q.get()
        while generation_nb_rslt != generation_nb:
            generation_nb_rslt, success, payload = response_q.get()
        if not success:
            raise RuntimeError(
                f"Error: Couldnt {error_context}. Execution failed: {payload}"
            )
        return payload

    @staticmethod
    def proxy_list_resources(
        request_q: Queue[Any],
        response_q: Queue[Any],
        generation_nb: int,
    ) -> Callable[[], list[str]]:
        def list_resources() -> list[str]:
            return SandboxMCPBridgeMixin._bridge_call(
                request_q,
                response_q,
                generation_nb,
                "list_resources",
                None,
                "list resources",
            )

        return list_resources

    @staticmethod
    def proxy_get_resource(
        request_q: Queue[Any],
        response_q: Queue[Any],
        generation_nb: int,
    ) -> Callable[[str], bytes]:
        def get_resource(resource_name: str) -> bytes:
            return SandboxMCPBridgeMixin._bridge_call(
                request_q,
                response_q,
                generation_nb,
                "get_resource",
                resource_name,
                f"get resource '{resource_name}'",
            )

        return get_resource

    @staticmethod
    def proxy_list_prompts(
        request_q: Queue[Any],
        response_q: Queue[Any],
        generation_nb: int,
    ) -> Callable[[], list[str]]:
        def list_prompts() -> list[str]:
            return SandboxMCPBridgeMixin._bridge_call(
                request_q,
                response_q,
                generation_nb,
                "list_prompts",
                None,
                "list prompts",
            )

        return list_prompts

    @staticmethod
    def proxy_get_prompt(
        request_q: Queue[Any],
        response_q: Queue[Any],
        generation_nb: int,
    ) -> Callable[[str], str]:
        def get_prompt(prompt_name: str) -> str:
            return SandboxMCPBridgeMixin._bridge_call(
                request_q,
                response_q,
                generation_nb,
                "get_prompt",
                prompt_name,
                f"get prompt '{prompt_name}'",
            )

        return get_prompt

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
                    if self._mcp_active_since is not None:
                        self._mcp_wait_total += (
                            time.monotonic() - self._mcp_active_since
                        )
                    self._mcp_active_since = None

    def _execute_mcp_call(
        self, mcp_function: str, name: str, kwargs: dict[str, Any]
    ) -> tuple[bool, Any]:
        if self.sync_client is None:
            return False, "Error: No MCP client available."
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
        return base64.b64decode(content.blob).decode("utf-8", errors="replace")

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
