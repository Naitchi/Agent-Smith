from typing import Any, Optional

from mcp import Client, StdioServerParameters, stdio_client
import asyncio


class MCPClient:

    def __init__(
        self,
        host: Optional[str],
        port: Optional[int],
        server_path: Optional[str] = "./mcp_tools_mbpp.py",
    ) -> None:
        self.port = port
        self.host = host
        self.server_path = server_path
        params: Optional[Any] = None
        if (self.host is None or self.port is None) and self.server_path:
            server = StdioServerParameters(
                command="python", args=[self.server_path]
            )
            params = stdio_client(server)
        elif self.host and self.port:
            params = f"http://{self.host}:{self.port}/mcp"
        else:
            raise ValueError(
                "Either host and port or server_path must be provided."
            )
        self.client = Client(params)

    def connect(self):
        pass

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

    def disconnect(self):
        pass
