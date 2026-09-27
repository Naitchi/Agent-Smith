"""Errors raised by AgentLoop."""


class AgentLoopError(Exception):
    """Base class of every AgentLoop error."""


class SigStopError(AgentLoopError):
    """Raised on Ctrl-C, after the backup is saved."""


class NoModelAvailableError(AgentLoopError):
    """Raised when every fallback model has failed."""

    def __init__(self, exhausted: list[str]) -> None:
        self.exhausted = exhausted
        super().__init__(
            f"plus aucun modele disponible, {len(exhausted)} ecartes -> "
            f"{', '.join(exhausted)}"
        )


class BudgetExceededError(AgentLoopError):
    """Base class of token and time budget errors."""


class MaxInputTokensError(BudgetExceededError):
    """Raised when input tokens reach max_input_tokens."""

    def __init__(self, used: int, limit: int) -> None:
        self.used = used
        self.limit = limit
        super().__init__(f"max_input_tokens exceeded ({used}/{limit})")


class MaxOutputTokensError(BudgetExceededError):
    """Raised when output tokens reach max_output_tokens."""

    def __init__(self, used: int, limit: int) -> None:
        self.used = used
        self.limit = limit
        super().__init__(f"max_output_tokens exceeded ({used}/{limit})")


class MaxWallTimeError(BudgetExceededError):
    """Raised when the loop reaches max_wall_time_seconds."""

    def __init__(self, elapsed: float, limit: float) -> None:
        self.elapsed = elapsed
        self.limit = limit
        super().__init__(
            f"max_wall_time_seconds exceeded ({elapsed:.1f}s/{limit}s)")


class MaxIterationsError(AgentLoopError):
    """Raised when max_iterations is reached without final_answer."""

    def __init__(self, max_iterations: int,
                 last_error: str | None = None) -> None:
        self.max_iterations = max_iterations
        self.last_error = last_error
        message = ("max_iterations reached without final_answer "
                   f"({max_iterations})")
        if last_error is not None:
            message += f", derniere erreur -> {last_error}"
        super().__init__(message)


class ConsecutiveErrorsError(AgentLoopError):
    """Raised after too many consecutive errors."""

    def __init__(self, count: int, last_error: str | None = None) -> None:
        self.count = count
        self.last_error = last_error
        message = f"{count} erreurs consecutives"
        if last_error is not None:
            message += f", derniere -> {last_error}"
        super().__init__(message)
