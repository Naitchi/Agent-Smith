"""MBPP agent CLI: solve one task file and write solution.json.

API keys are read from the environment, never from the command line.
"""
from __future__ import annotations

from agent import (
    MBPP_LIMITS,
    MBPP_MCP_SERVER,
    SYSTEM_PROMPT_MBPP,
    AgentLoop,
    MBPPTaskInput,
    Sandbox,
    build_user_prompt,
    check_api_key,
    default_conf,
    load_task,
    mcp_stdio_command,
    mcp_target,
    parse_args,
    run_cli,
    show_summary,
    write_output,
)


def main() -> None:
    args = parse_args("agent_mbpp")
    check_api_key()

    task = load_task(args.task_file, MBPPTaskInput)
    sandbox = Sandbox(**mcp_target(
        args, mcp_stdio_command(MBPP_MCP_SERVER, args.task_file)))
    conf = default_conf(args.model_name, args.provider_url, sandbox,
                        SYSTEM_PROMPT_MBPP, MBPP_LIMITS)

    try:
        out = AgentLoop(conf).run(
            task_id=str(task.task_id),
            benchmark="mbpp",
            user_prompt=build_user_prompt(task),
            resume=False,
        )
        if not out.solution:
            for step in reversed(out.steps):
                if step.sandbox_input:
                    out.solution = step.sandbox_input
                    break
        write_output(out, args.output)
    finally:
        conf.sandbox.close()
    show_summary(out, MBPP_LIMITS)


if __name__ == "__main__":
    run_cli(main)
