from typing import Any, Optional

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
                raise ValueError(
                    "Either host and port or server_path must be provided."
                )
        except ValueError as e:
            print(f"Error building client: {e}")
            return None
        return Client(params)

    async def connect(self):
        if not self.client:
            print("No client to disconnect.")
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

    def get_tools_list(self):
        pass

    def use_tool(self, tool_name: str, *args: Any, **kwargs: Any):
        pass

    def get_resources_list(self):
        pass

    def get_resource(self, resource_name: str):
        pass

    def get_prompt(self):
        pass

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
