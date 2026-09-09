from typing import Any, Dict, List, Optional
from mcp import (
    StdioServerParameters,
    GetPromptResult,
    stdio_client,
    Client,
    Tool,
)
from mcp_types import (
    TextResourceContents,
    BlobResourceContents,
    CallToolResult,
    Resource,
    Prompt,
)

import sys


class MCPClient:
    def __init__(
        self,
        server_path: Optional[str] = None,
        url: Optional[str] = None,
    ) -> None:
        self.url = url
        self.server_path = server_path
        self.client: Optional[Client] = self.build_client()
        self.connected = False

    def build_client(self) -> Optional[Client]:
        try:
            params: Optional[Any] = None
            if (self.url is None) and self.server_path:
                server = StdioServerParameters(
                    command="python", args=[self.server_path]
                )
                params = stdio_client(server)
            elif self.url:
                params = self.url
            else:
                raise ValueError("Either url or server_path must be provided.")
        except ValueError as e:
            print(f"Error building client: {e}", file=sys.stderr)
            return None
        except Exception as e:
            print(f"Unexpected error: {e}", file=sys.stderr)
            return None
        return Client(params)

    async def connect(self):
        if not self.client:
            print("No client to connect.", file=sys.stderr)
            return
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
        if self.client is None:
            raise RuntimeError("No client available.")
        if not self.connected:
            raise RuntimeError("Not connected to the MCP server.")
        return self.client

    async def get_tools_list(self) -> List[Tool]:
        client = self._require_client()
        return (await client.list_tools()).tools

    async def use_tool(
        self, tool_name: str, params: Optional[Dict[str, Any]] = None
    ) -> CallToolResult:
        client = self._require_client()
        return await client.call_tool(tool_name, params or {})

    async def get_resources_list(self) -> List[Resource]:
        client = self._require_client()
        return (await client.list_resources()).resources

    async def get_resource(
        self, uri: str
    ) -> List[TextResourceContents | BlobResourceContents]:
        client = self._require_client()
        return (await client.read_resource(uri)).contents

    async def get_prompt_list(self) -> List[Prompt]:
        client = self._require_client()
        return (await client.list_prompts()).prompts

    async def get_prompt(
        self, prompt_name: str, arguments: Optional[Dict[str, Any]] = None
    ) -> GetPromptResult:
        client = self._require_client()
        return await client.get_prompt(prompt_name, arguments=arguments or {})

    async def disconnect(self) -> None:
        if not self.client:
            print("No client to disconnect.", file=sys.stderr)
            return
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
