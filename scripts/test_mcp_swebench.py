"""Smoke test for the SWE-bench MCP server (mcp_tools_swebench.py).

Unlike scripts/test_mcp.py (MBPP), this talks to MCPServerSWEBench
in-process instead of over stdio/HTTP: mcp_tools_swebench.py has no
``if __name__ == "__main__":`` entry point yet, so there is no process to
launch as a subprocess. Once one is added (mirroring mcp_tools_mbpp.py),
this can be pointed at a real MCPClient/subprocess the same way.

Point TESTBED_PATH (and whatever your DockerManager reads) at a running
container before running this, e.g.:
    uv run python ./scripts/docker_testbed.py start

To launch: uv run python ./scripts/test_mcp_swebench.py
"""

from __future__ import annotations

import asyncio

from mcp_tools_swebench import MCPServerSWEBench
from schemas import SWEBenchTaskInput

FAKE_TASK = SWEBenchTaskInput(
    instance_id="fake__test-1",
    problem_statement="add(a, b) returns a - b instead of a + b.",
    docker_image="agent-smith/testbed:latest",
    eval_script="bash eval.sh",
    hints_text="",
    repo="fake/test",
)

# Mandatory tools (subject section V.5), with a harmless smoke-test call
# for each read-only/idempotent one. Matched against the seed repo from
# scripts/docker_testbed.py. edit_file is left out since it mutates the
# testbed and isn't idempotent across repeated runs.
SMOKE_CALLS = {
    "read_file": {"filepath": "add.py", "start_line": 1, "end_line": 5},
    "list_files": {"directory": ".", "pattern": "*.py"},
    "search_code": {"pattern": "def add", "file_pattern": "*.py"},
    "search_function_or_class_definition_in_code": {"name": "add"},
    "find_references": {"name": "add", "filepath": "add.py", "line": 1},
    "run_command": {"command": "echo hello", "workdir": "."},
    "run_tests": {},
    "get_patch": {},
}


async def main() -> None:
    server = MCPServerSWEBench(task=FAKE_TASK)

    tools = await server.mcp.list_tools()
    print(f"Tools registered: {len(tools)}")
    for tool in tools:
        print(" -", tool.name)

    resources = await server.mcp.list_resources()
    print(f"\nResources registered: {len(resources)}")
    for resource in resources:
        print(" -", resource.name, resource.uri)

    prompts = await server.mcp.list_prompts()
    print(f"\nPrompts registered: {len(prompts)}")
    for prompt in prompts:
        print(" -", prompt.name)

    tool_names = {tool.name for tool in tools}
    print("\nSmoke-calling registered mandatory tools:")
    for name, args in SMOKE_CALLS.items():
        if name not in tool_names:
            print(f" - {name}: not registered yet, skipped")
            continue
        try:
            result = await server.mcp.call_tool(name, args)
            print(f" - {name}: {result}")
        except Exception as e:
            print(f" - {name}: raised {e.__class__.__name__}: {e}")


if __name__ == "__main__":
    asyncio.run(main())
