from schemas import SandboxConfig
from scripts.fake_sandbox import FakeSandbox
from src.agent_loop import AgentLoop
from src.llm import LLMResult


class FakeLLM:
    """Returns scripted responses in order, no network involved."""

    def __init__(self, responses: list[str]) -> None:
        self.responses = list(responses)
        self.calls = 0

    def __call__(self, system: str, messages: list[dict]) -> LLMResult:
        text = self.responses[self.calls]
        self.calls += 1
        return LLMResult(text=text, input_tokens=10, output_tokens=5, latency_ms=1.0)


def make_sandbox() -> FakeSandbox:
    return FakeSandbox(SandboxConfig())


def test_happy_path_stops_on_final_answer():
    llm = FakeLLM(["```\nfinal_answer('42')\n```"])
    loop = AgentLoop(llm, make_sandbox(), system_prompt="sys", max_iterations=5)

    output = loop.run(task_id="1", benchmark="mbpp", user_prompt="do the thing")

    assert output.success is True
    assert output.solution == "42"
    assert output.iterations == 1
    assert output.error is None
    assert len(output.steps) == 1
    assert output.steps[0].sandbox_input == "final_answer('42')"


def test_no_code_block_records_error_observation_and_continues():
    llm = FakeLLM([
        "I think I should write some code but forgot to.",
        "```\nfinal_answer('done')\n```",
    ])
    loop = AgentLoop(llm, make_sandbox(), system_prompt="sys", max_iterations=5)

    output = loop.run(task_id="1", benchmark="mbpp", user_prompt="do the thing")

    assert output.success is True
    assert output.iterations == 2
    assert "No valid code block" in output.steps[0].sandbox_output
    assert output.steps[0].sandbox_input == ""


def test_max_iterations_reached_returns_failure_without_crash():
    llm = FakeLLM(["```\nprint('still working')\n```"] * 3)
    loop = AgentLoop(llm, make_sandbox(), system_prompt="sys", max_iterations=3)

    output = loop.run(task_id="1", benchmark="mbpp", user_prompt="do the thing")

    assert output.success is False
    assert "max_iterations" in output.error
    assert output.iterations == 3


def test_runtime_error_is_reported_as_observation_not_crash():
    # FakeSandbox has no security layer (real Sandbox is bclairot's lot) — this
    # exercises a plain runtime error instead, which FakeSandbox does surface.
    llm = FakeLLM([
        "```\nprint(1 / 0)\n```",
        "```\nfinal_answer('recovered')\n```",
    ])
    loop = AgentLoop(llm, make_sandbox(), system_prompt="sys", max_iterations=5)

    output = loop.run(task_id="1", benchmark="mbpp", user_prompt="do the thing")

    assert output.success is True
    assert "error:" in output.steps[0].sandbox_output


def test_token_budget_exceeded_stops_before_max_iterations():
    llm = FakeLLM(["```\nprint('x')\n```"] * 10)
    loop = AgentLoop(
        llm, make_sandbox(), system_prompt="sys",
        max_iterations=10, max_input_tokens=25, max_output_tokens=None, max_wall_time_seconds=None,
    )

    output = loop.run(task_id="1", benchmark="mbpp", user_prompt="do the thing")

    assert output.success is False
    assert "max_input_tokens" in output.error
    assert output.iterations < 10
