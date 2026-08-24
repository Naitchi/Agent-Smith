import contextlib
import io
from typing import Any, Dict

from schemas import SandboxConfig
from schemas.contract_model import ExecutionResult


class _FinalAnswer(Exception):
    def __init__(self, value: str) -> None:
        self.value = value


class FakeSandbox:
    def __init__(self, config: SandboxConfig | None = None) -> None:
        self.config = config
        self._ns: Dict[str, Any] = {}
        self._ns.update({"final_answer": self._final_answer})

    def _final_answer(self, answer: str) -> None:
        raise _FinalAnswer(answer)

    def execute(self, code: str) -> ExecutionResult:
        out = io.StringIO()
        try:
            with contextlib.redirect_stdout(out):
                exec(code, self._ns)
            return ExecutionResult(stdout=out.getvalue())
        except _FinalAnswer as fa:
            return ExecutionResult(
                stdout=out.getvalue(), final_answer=str(fa.value)
            )
        except Exception as e:
            return ExecutionResult(
                stdout=out.getvalue(), error=f"{type(e).__name__}: {e}"
            )

    def get_manual(self) -> str:
        return (
            "FAKE MANUAL (dev only, no real MCP server connected).\n"
            "Available: print(...), final_answer(answer) to stop the loop.\n"
            "No security restrictions here — do not trust this for the exam."
        )

    def close(self) -> None:
        pass
