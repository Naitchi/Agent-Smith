"""Checklist §0.6 — mock #1: B → A.

Naive stand-in for the real `Sandbox`. No security, no MCP tools, no
timeout/RAM limits. Just enough (SandboxProtocol-compatible) for A to write
and test the whole AgentLoop before B's real sandbox exists.

NEVER use this for grading/exam — it has zero restrictions.
"""

import contextlib
import io

from agent_smith.contract import ExecutionResult


class _FinalAnswer(Exception):
    def __init__(self, value: str) -> None:
        self.value = value


class FakeSandbox:
    def __init__(self) -> None:
        self._ns: dict = {"final_answer": self._final_answer}

    def _final_answer(self, answer: str) -> None:
        raise _FinalAnswer(answer)

    def execute(self, code: str) -> ExecutionResult:
        out = io.StringIO()
        try:
            with contextlib.redirect_stdout(out):
                exec(code, self._ns)  # noqa: S102 — deliberately naive, see docstring
            return ExecutionResult(stdout=out.getvalue())
        except _FinalAnswer as fa:
            return ExecutionResult(stdout=out.getvalue(), final_answer=str(fa.value))
        except Exception as e:  # noqa: BLE001 — feedback to the LLM, not a crash
            return ExecutionResult(stdout=out.getvalue(), error=f"{type(e).__name__}: {e}")

    def get_manual(self) -> str:
        return (
            "FAKE MANUAL (dev only, no real MCP server connected).\n"
            "Available: print(...), final_answer(answer) to stop the loop.\n"
            "No security restrictions here — do not trust this for the exam."
        )

    def close(self) -> None:
        pass
