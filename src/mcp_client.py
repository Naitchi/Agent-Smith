"""Async MCP client: connect to an MCP server over stdio or HTTP.

Thin wrapper around the `mcp` package's high-level `Client`, exposing
tools/resources/prompts as plain `async def` methods. Lives in the
Sandbox's parent process, never in the sandboxed worker — see
`SyncMCPClient` for the synchronous façade used to drive it from the
bridge thread.
"""

import sys
from shlex import split
from typing import Any

from mcp import (
    Client,
    GetPromptResult,
    StdioServerParameters,
    Tool,
    stdio_client,
)
from mcp_types import (
    BlobResourceContents,
    CallToolResult,
    Prompt,
    Resource,
    TextResourceContents,
)


class MCPClient:
    """Wraps `mcp.Client`, connected over stdio or HTTP.

    Attributes:
        url: HTTP URL of the MCP server, or None when connecting over
            stdio.
        command_stdio: Shell command that launches the MCP server as a
            subprocess, or None when connecting over HTTP.
        client: The underlying `mcp.Client`. Rebuilt on every
            `disconnect()`, since a `Client` instance is single-use.
        connected: Whether `connect()` has been called without a
            matching `disconnect()` since.
    """

    def __init__(
        self,
        command_stdio: str | None = None,
        url: str | None = None,
    ) -> None:
        """Args:
        command_stdio: Shell command to launch the MCP server over
            stdio (e.g. ``"python mcp_tools_mbpp.py"``), split with
            `shlex.split`. Ignored if `url` is set.
        url: HTTP URL of an already-running MCP server. Takes
            priority over `command_stdio` when both are given.
        """
        self.url = url
        self.command_stdio = command_stdio
        self.client: Client = self.build_client()
        self.connected = False

    def build_client(self) -> Client:
        """Build a fresh, not-yet-connected `mcp.Client`.

        Called once from `__init__`, and again from `disconnect()` so
        this instance can be reconnected afterwards (`mcp.Client` is
        single-use).

        Returns:
            A `Client` configured for stdio (via `stdio_client` +
            `StdioServerParameters`) or HTTP (a plain URL string),
            depending on which of `self.url`/`self.command_stdio` is
            set.

        Raises:
            ValueError: If neither `url` nor `command_stdio` was
                provided.
        """
        params: Any | None = None
        if (self.url is None) and self.command_stdio:
            try:
                command, *args = split(self.command_stdio)
            except Exception as e:
                print(f"Error splitting command_stdio: {e}", file=sys.stderr)
                raise
            server = StdioServerParameters(command=command, args=args)
            params = stdio_client(server)
        elif self.url:
            params = self.url
        else:
            raise ValueError("Either url or command_stdio must be provided.")
        return Client(params)

    async def connect(self):
        """Open the connection and keep it open across calls.

        Calls `client.__aenter__` directly (rather than using the
        client as a context manager per call) so the same connection
        can be reused for `get_tools_list`/`use_tool`/etc. across many
        calls instead of reconnecting every time.

        Raises:
            RuntimeError: If already connected.
        """
        try:
            if self.connected:
                raise RuntimeError("Already connected to the MCP server.")
            await self.client.__aenter__()
            self.connected = True
            if self.client.server_info:
                print(
                    f"Connected to MCP server: {self.client.server_info}",
                    file=sys.stderr,
                )
            else:
                print(
                    "Connected to MCP server, but no server info available.",
                    file=sys.stderr,
                )
        except Exception as e:
            print(f"Failed to connect to the MCP server: {e}", file=sys.stderr)
            raise

    def _require_client(self) -> Client:
        """Return `self.client`, guarding against calls before `connect()`.

        Returns:
            The connected `Client`.

        Raises:
            RuntimeError: If `connect()` hasn't been called yet (or was
                followed by `disconnect()`).
        """
        if not self.connected:
            raise RuntimeError("Not connected to the MCP server.")
        return self.client

    async def get_tools_list(self) -> list[Tool]:
        """Returns:
        The MCP server's tools, as reported by `list_tools()`.
        """
        client = self._require_client()
        return (await client.list_tools()).tools

    async def use_tool(
        self, tool_name: str, params: dict[str, Any] | None = None
    ) -> CallToolResult:
        """Call one MCP tool.

        Args:
            tool_name: Name of the tool to call.
            params: Keyword arguments for the tool, or None for no
                arguments.

        Returns:
            The full `CallToolResult` (content blocks + `is_error`) —
            unwrapping it into a plain string, and checking `is_error`,
            is left to the caller.
        """
        client = self._require_client()
        return await client.call_tool(tool_name, params or {})

    async def get_resources_list(self) -> list[Resource]:
        """Returns:
        The MCP server's resources, as reported by `list_resources()`.
        """
        client = self._require_client()
        return (await client.list_resources()).resources

    async def get_resource(
        self, uri: str
    ) -> list[TextResourceContents | BlobResourceContents]:
        """Read one resource.

        Args:
            uri: The resource's URI (e.g. ``"mbpp://task"``).

        Returns:
            Its contents — text or base64-encoded binary, depending on
            the resource.
        """
        client = self._require_client()
        return (await client.read_resource(uri)).contents

    async def get_prompt_list(self) -> list[Prompt]:
        """Returns:
        The MCP server's prompts, as reported by `list_prompts()`.
        """
        client = self._require_client()
        return (await client.list_prompts()).prompts

    async def get_prompt(
        self, prompt_name: str, arguments: dict[str, Any] | None = None
    ) -> GetPromptResult:
        """Fetch one prompt, rendered with `arguments`.

        Args:
            prompt_name: Name of the prompt to fetch.
            arguments: Template arguments for the prompt, or None for
                none.

        Returns:
            The rendered prompt's messages.
        """
        client = self._require_client()
        return await client.get_prompt(prompt_name, arguments=arguments or {})

    async def disconnect(self) -> None:
        """Close the connection and rebuild `self.client` for reuse.

        Raises:
            RuntimeError: If already disconnected.
        """
        try:
            if not self.connected:
                raise RuntimeError("Already disconnected from the MCP server.")
            await self.client.__aexit__(None, None, None)
            print("Disconnected from MCP server.", file=sys.stderr)
            self.connected = False
            self.client = self.build_client()
        except Exception as e:
            print(
                f"Failed to disconnect from the MCP server: {e}",
                file=sys.stderr,
            )
            raise
