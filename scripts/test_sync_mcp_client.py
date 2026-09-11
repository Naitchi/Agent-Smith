from src.mcp_client import MCPClient
from src.mcp_sync_client import SyncMCPClient


def main():
    sc = SyncMCPClient(MCPClient(server_path="./mcp_tools_mbpp.py"))
    sc.start()
    try:
        tools = sc.get_tools_list()
        print("outils:", [t.name for t in tools])

        res = sc.use_tool(
            "run_tests",
            {
                "code": "def add(a, b): return a + b",
                "test_list": ["assert add(1, 2) == 3"],
            },
        )
        print("run_tests:", res)
    finally:
        sc.stop()


main()
