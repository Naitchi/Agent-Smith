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
    def __init__(
        self,
        command_stdio: str | None = None,
        url: str | None = None,
    ) -> None:
        self.url = url
        self.command_stdio = command_stdio
        self.client: Client = self.build_client()
        self.connected = False

    def build_client(self) -> Client:
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
        if not self.connected:
            raise RuntimeError("Not connected to the MCP server.")
        return self.client

    async def get_tools_list(self) -> list[Tool]:
        client = self._require_client()
        return (await client.list_tools()).tools

    async def use_tool(
        self, tool_name: str, params: dict[str, Any] | None = None
    ) -> CallToolResult:
        client = self._require_client()
        return await client.call_tool(tool_name, params or {})

    async def get_resources_list(self) -> list[Resource]:
        client = self._require_client()
        return (await client.list_resources()).resources

    async def get_resource(
        self, uri: str
    ) -> list[TextResourceContents | BlobResourceContents]:
        client = self._require_client()
        return (await client.read_resource(uri)).contents

    async def get_prompt_list(self) -> list[Prompt]:
        client = self._require_client()
        return (await client.list_prompts()).prompts

    async def get_prompt(
        self, prompt_name: str, arguments: dict[str, Any] | None = None
    ) -> GetPromptResult:
        client = self._require_client()
        return await client.get_prompt(prompt_name, arguments=arguments or {})

    async def disconnect(self) -> None:
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
