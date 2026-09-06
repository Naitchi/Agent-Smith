from mcp import Client, StdioServerParameters, stdio_client
from typing import Any, Dict, Optional
from functools import wraps

import sys


def guarded(action: str):
    def decorator(func):
        @wraps(func)
        async def wrapper(self, *args, **kwargs):
            try:
                if not self.client or not self.connected:
                    raise RuntimeError(f"No client available to {action}.")
                return await func(self, *args, **kwargs)
            except Exception as e:
                print(f"Failed to {action}: {e}", file=sys.stderr)
                raise

        return wrapper

    return decorator


class MCPClient:
    def __init__(
        self,
        server_path: Optional[str] = "./mcp_tools_mbpp.py",
        url: Optional[str] = None,
    ) -> None:
        self.url = url
        self.server_path = server_path
        self.client: Optional[Client] = self.build_client()
        self.connected = False

    def build_client(self):
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

    @guarded("get tools list")
    async def get_tools_list(self):
        return (await self.client.list_tools()).tools

    @guarded("use tool")
    async def use_tool(
        self, tool_name: str, params: Optional[Dict[str, Any]] = None
    ):
        return await self.client.call_tool(tool_name, params or {})

    @guarded("get resources list")
    async def get_resources_list(self):
        return (await self.client.list_resources()).resources

    @guarded("get resource")
    async def get_resource(self, uri: str):
        return (await self.client.read_resource(uri)).contents

    @guarded("get prompt list")
    async def get_prompt_list(self):
        return (await self.client.list_prompts()).prompts

    @guarded("get prompt")
    async def get_prompt(
        self, prompt_name: str, arguments: Optional[Dict[str, Any]] = None
    ):
        return await self.client.get_prompt(
            prompt_name, arguments=arguments or {}
        )

    async def disconnect(self):
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
