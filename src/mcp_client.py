from typing import Any, Dict, Optional

from mcp import Client, StdioServerParameters, stdio_client


class MCPClient:

    def __init__(
        self,
        url: Optional[str],
        server_path: Optional[str] = "./mcp_tools_mbpp.py",
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
            print(f"Error building client: {e}")
            return None
        return Client(params)

    async def connect(self):
        if not self.client:
            print("No client to connect.")
            return
        try:
            if self.connected:
                raise RuntimeError("Already connected to the MCP server.")
            await self.client.__aenter__()
            self.connected = True
            if self.client.server_info:
                print(f"Connected to MCP server: {self.client.server_info}")
            else:
                print("Connected to MCP server, but no server info available.")
        except Exception as e:
            print(f"Failed to connect to the MCP server: {e}")
            raise

    async def get_tools_list(self):
        try:
            if not self.client or not self.connected:
                raise RuntimeError("No client available to get tools list.")
            return (await self.client.list_tools()).tools
        except Exception as e:
            print(f"Failed to get tools list: {e}")
            raise

    async def use_tool(
        self, tool_name: str, params: Optional[Dict[str, Any]] = None
    ):
        try:
            if not self.client or not self.connected:
                raise RuntimeError("No client available to use tool.")
            return await self.client.call_tool(tool_name, params or {})
        except Exception as e:
            print(f"Failed to use tool: {e}")
            raise

    async def get_resources_list(self):
        try:
            if not self.client or not self.connected:
                raise RuntimeError(
                    "No client available to get resources list."
                )
            return (await self.client.list_resources()).resources
        except Exception as e:
            print(f"Failed to get resources list: {e}")
            raise

    async def get_resource(self, uri: str):
        try:
            if not self.client or not self.connected:
                raise RuntimeError("No client available to get resource.")
            return (await self.client.read_resource(uri)).contents
        except Exception as e:
            print(f"Failed to get resource: {e}")
            raise

    async def get_prompt_list(self):
        try:
            if not self.client or not self.connected:
                raise RuntimeError("No client available to get prompt list.")
            return (await self.client.list_prompts()).prompts
        except Exception as e:
            print(f"Failed to get prompt list: {e}")
            raise

    async def get_prompt(
        self, prompt_name: str, arguments: Optional[Dict[str, Any]] = None
    ):
        try:
            if not self.client or not self.connected:
                raise RuntimeError("No client available to get prompt.")
            return await self.client.get_prompt(
                prompt_name, arguments=arguments or {}
            )
        except Exception as e:
            print(f"Failed to get prompt: {e}")
            raise

    async def disconnect(self):
        if not self.client:
            print("No client to disconnect.")
            return
        try:
            if not self.connected:
                raise RuntimeError("Already disconnected from the MCP server.")
            await self.client.__aexit__(None, None, None)
            print("Disconnected from MCP server.")
            self.connected = False
            self.client = self.build_client()
        except Exception as e:
            print(f"Failed to disconnect from the MCP server: {e}")
            raise
