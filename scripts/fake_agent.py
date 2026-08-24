"""Checklist §0.6 — mock #2: A → B.

Sends 3 hardcoded code blocks to a real `Sandbox` and prints each
`ExecutionResult`. Lets B exercise/debug the sandbox without needing A's LLM
loop at all.

Usage:
    uv run python scripts/fake_agent.py

Requires B's `Sandbox` + `SandboxConfig` to exist (agent_smith.sandbox /
agent_smith.schemas). Swap CODE_BLOCKS below to target whatever you're
currently testing (imports allowlist, FS allowlist, persistence, timeout...).
"""

from agent_smith.schemas import SandboxConfig
from agent_smith.sandbox import Sandbox

CODE_BLOCKS = [
    # 1. basic execution + stdout
    "print('hello from block 1')\nx = 21",
    # 2. state persistence across execute() calls + final_answer()
    "print(x * 2)\nfinal_answer(x * 2)",
    # 3. should be caught by the security layer (import + FS escape)
    "import os\nprint(os.listdir('/etc'))",
]


def main() -> None:
    sandbox = Sandbox(SandboxConfig())
    try:
        for i, code in enumerate(CODE_BLOCKS, start=1):
            print(f"--- block {i} ---\n{code}\n")
            result = sandbox.execute(code)
            print(result.model_dump_json(indent=2))
            print()
            if result.final_answer is not None:
                print(f"final_answer received: {result.final_answer!r} — stopping.")
                break
    finally:
        sandbox.close()


if __name__ == "__main__":
    main()
