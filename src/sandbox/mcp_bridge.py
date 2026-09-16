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
        """Send one request to the bridge thread and block for its reply.

        Shared by the `proxy_*` resource/prompt proxies (tool calls have
        their own inline version in `_make_tool_proxy`, since they also
        need to map positional args to keyword args first).

        Args:
            request_q: Queue read by `_bridge_loop` in the parent.
            response_q: Queue the parent's `_bridge_loop` replies on.
            generation_nb: This `execute()` call's generation number —
                replies tagged with an older one are discarded, so a
                response arriving after this call's worker was already
                killed on timeout doesn't get misrouted into the next
                call.
            mcp_function: Which `_execute_mcp_call` branch to run
                (``"list_resources"``, ``"get_resource"``, etc.).
            arg: The single positional argument for that operation (a
                resource URI or prompt name), or None.
            error_context: Human-readable description used in the
                exception message on failure.

        Returns:
            The call's result payload.

        Raises:
            RuntimeError: If the parent reports failure.
        """
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
        """Build the `list_resources()` sandbox-namespace function.

        Args:
            request_q: Queue to the parent's bridge thread.
            response_q: Queue back from the parent's bridge thread.
            generation_nb: This call's generation number.

        Returns:
            A zero-argument callable that fetches the connected MCP
            server's resource list.
        """

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
        """Build the `get_resource(uri)` sandbox-namespace function.

        Args:
            request_q: Queue to the parent's bridge thread.
            response_q: Queue back from the parent's bridge thread.
            generation_nb: This call's generation number.

        Returns:
            A callable taking a resource URI and returning its content.
        """

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
        """Build the `list_prompts()` sandbox-namespace function.

        Args:
            request_q: Queue to the parent's bridge thread.
            response_q: Queue back from the parent's bridge thread.
            generation_nb: This call's generation number.

        Returns:
            A zero-argument callable that fetches the connected MCP
            server's prompt list.
        """

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
        """Build the `get_prompt(name)` sandbox-namespace function.

        Args:
            request_q: Queue to the parent's bridge thread.
            response_q: Queue back from the parent's bridge thread.
            generation_nb: This call's generation number.

        Returns:
            A callable taking a prompt name and returning its rendered
            messages (as a string).
        """

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
        """Parent-side thread: relay tool/resource/prompt requests to the MCP
        server.

        Runs for the lifetime of the sandbox once an MCP server is
        connected (started in `Sandbox.__init__`, stopped via a `None`
        sentinel on `_mcp_requests` in `close()`). Reads
        `(generation_nb, mcp_function, name, kwargs)` tuples put there
        by a worker's proxy function or by `_bridge_call`, ignores any
        whose `generation_nb` is stale (from an already-superseded
        `execute()` call), and puts `(generation_nb, success, payload)`
        back on `_mcp_responses`. Tracks how long each call took
        (`_mcp_wait_total`/`_mcp_active_since`) so `_wait_for_worker` can
        exclude that time from the sandbox's own timeout.
        """
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
        """Dispatch one bridge request to the matching `SyncMCPClient` call.

        Args:
            mcp_function: Which operation to run (``"use_tool"``,
                ``"list_resources"``, ``"list_prompts"``,
                ``"get_resource"``, or ``"get_prompt"``).
            name: The tool/resource/prompt name (ignored for the
                ``list_*`` operations).
            kwargs: Keyword arguments for a tool call; ignored
                otherwise.

        Returns:
            A `(success, payload)` pair. For `"use_tool"`, `payload` is
            the first content block's text (or None if the tool
            returned nothing) and `success` is False when
            `CallToolResult.is_error` is set — guarding against an empty
            `content` list before indexing into it.
        """
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
        """Turn one resource content block into a plain string.

        Args:
            content: A resource's content, either already text or
                base64-encoded binary.

        Returns:
            The text as-is, or the binary payload base64-decoded and
            decoded as UTF-8 (with invalid bytes replaced, not raised
            on).
        """
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
        tool_docs: dict[str, str],
    ) -> Callable[..., Any]:
        """Build the sandbox-namespace function proxying one MCP tool.

        Args:
            name: The MCP tool's name — what the sandboxed code calls
                it as, and the key `use_tool` requests are tagged with.
            request_q: Queue to the parent's bridge thread.
            response_q: Queue back from the parent's bridge thread.
            generation_nb: This call's generation number (see
                `_bridge_loop`).
            tool_param_names: Tool name -> ordered parameter names, so
                positional arguments (e.g. `read_file("add.py", 1, 5)`,
                the way the subject shows tool calls) can be mapped to
                the right keyword before the request is sent.
            tool_docs: Tool name -> description, used to set the
                returned function's `__doc__`.

        Returns:
            A callable accepting the tool's real parameters (by
            position or keyword), with `__name__`/`__doc__` set to the
            real tool's — so introspecting the proxy from sandboxed code
            shows the actual MCP tool, not a generic `proxy`.

        Raises:
            TypeError: If called with more positional arguments than
                the tool has parameters, or with a keyword that
                duplicates one already filled positionally.
        """

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

        proxy.__name__ = name
        proxy.__doc__ = tool_docs.get(name, "")
        return proxy

    @staticmethod
    def _param_type(prop: dict[str, Any]) -> str:
        """Resolve one JSON-schema property's type, `anyOf` unions included.

        A plain-typed parameter (``{"type": "string"}``) has a top-level
        `"type"` key, but an `Optional`/`X | None` parameter is instead
        represented as an `"anyOf"` union with no top-level `"type"` at
        all (e.g. ``{"anyOf": [{"type": "array", "items": {...}},
        {"type": "null"}]}``) — without this, such a parameter falls
        back to a useless ``"unknown"`` in the manual.

        Args:
            prop: One entry from a tool's `input_schema["properties"]`.

        Returns:
            The plain `"type"` value when present; otherwise every
            branch of an `"anyOf"` union joined with ``" | "`` (an
            `"array"` branch is expanded to ``array[item_type]``); or
            ``"unknown"`` if neither shape is present.
        """
        if "type" in prop:
            return prop["type"]
        if "anyOf" in prop:
            branches: list[str] = []
            for branch in prop["anyOf"]:
                branch_type = branch.get("type", "unknown")
                if branch_type == "array":
                    item_type = branch.get("items", {}).get("type", "unknown")
                    branch_type = f"array[{item_type}]"
                branches.append(branch_type)
            return " | ".join(branches)
        return "unknown"

    def _format_tool(self, tool: Tool) -> str:
        """Render one MCP tool's schema as a one-line manual entry.

        Args:
            tool: The tool, as reported by the connected MCP server's
                `list_tools()`.

        Returns:
            ``"tool_name(param: type (required), ...) - description"``,
            built entirely from `tool.input_schema`/`tool.description` —
            never from a hardcoded tool name.
        """
        description: str = ""
        schema = tool.input_schema or {}
        properties = schema.get("properties", {})
        required = set(schema.get("required", []))

        params: list[Any] = []
        for name, prop in properties.items():
            param_type = self._param_type(prop)
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
        """Build the sandbox manual fed into the LLM's system prompt.

        Generated dynamically from `self.config` (limits, allowlists)
        and whichever MCP server is currently connected (`self._tools`)
        — never hardcoded, so connecting a different MCP server changes
        this automatically.

        Returns:
            A plain-text manual: execution limits, authorized
            imports/builtins/attributes/directories, `final_answer`'s
            usage, one line per available MCP tool (via
            `_format_tool`), and — if an MCP server is connected — a
            reminder that `list_resources`/`get_resource`/
            `list_prompts`/`get_prompt` are also available.
        """
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
