import asyncio
import subprocess
import sys

from src.mcp_client import MCPClient

# To launch the test: uv run python ./scripts/test_mcp.py


async def wait_until_up(host: str, port: int, timeout: float = 10.0) -> None:
    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        try:
            _, writer = await asyncio.open_connection(host, port)
            writer.close()
            await writer.wait_closed()
            return
        except OSError:
            await asyncio.sleep(0.2)
    raise TimeoutError(f"serveur pas up sur {host}:{port}")


async def main():
    print("\nTesting stdio connection to MCP server...")
    client = MCPClient(server_path="./mcp_tools_mbpp.py")
    await client.connect()
    tools = await client.get_tools_list()
    print("Available tools:", tools)
    result = await client.use_tool(
        "run_tests",
        {
            "code": "def add(a,b): return a+b",
            "test_list": ["assert add(1,2)==3"],
        },
    )
    print("run_tests:", result)
    resources = await client.get_resources_list()
    print("Available resources:", resources)
    prompts = await client.get_prompt_list()
    print("Available prompts:", prompts)
    await client.disconnect()

    print("\n\nTesting HTTP connection...")
    server = subprocess.Popen(
        [
            sys.executable,
            "mcp_tools_mbpp.py",
            "--http",
            "--host",
            "localhost",
            "--port",
            "8080",
        ]
    )
    try:
        await wait_until_up("localhost", 8080)
        client_http = MCPClient(url="http://localhost:8080/mcp")
        await client_http.connect()
        print("tools:", await client_http.get_tools_list())
        result = await client_http.use_tool(
            "run_tests",
            {
                "code": "def add(a,b): return a+b",
                "test_list": ["assert add(1,2)==3"],
            },
        )
        print("run_tests:", result)
        resources = await client_http.get_resources_list()
        print("Available resources:", resources)
        prompts = await client_http.get_prompt_list()
        print("Available prompts:", prompts)
        await client_http.disconnect()
    finally:
        server.terminate()
        try:
            server.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server.kill()


if __name__ == "__main__":
    asyncio.run(main())
