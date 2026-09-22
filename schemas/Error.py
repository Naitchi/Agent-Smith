"""Erreurs custom levees par AgentLoop."""


class AgentLoopError(Exception):
    """Base de toutes les erreurs levees par AgentLoop."""


class SigStopError(AgentLoopError):
    """Levee quand la boucle est interrompue (Ctrl-C) apres sauvegarde du backup."""


class NoModelAvailableError(AgentLoopError):
    """Tous les modeles du pool ont ete ecartes (429 / 5xx)."""

    def __init__(self, exhausted: list[str]) -> None:
        self.exhausted = exhausted
        super().__init__(
            f"plus aucun modele disponible, {len(exhausted)} ecartes -> "
            f"{', '.join(exhausted)}"
        )


class BudgetExceededError(AgentLoopError):
    """Base des depassements de budget (tokens, temps)."""


class MaxInputTokensError(BudgetExceededError):
    """Le total de tokens d'entree a atteint `max_input_tokens`."""

    def __init__(self, used: int, limit: int) -> None:
        self.used = used
        self.limit = limit
        super().__init__(f"max_input_tokens exceeded ({used}/{limit})")


class MaxOutputTokensError(BudgetExceededError):
    """Le total de tokens de sortie a atteint `max_output_tokens`."""

    def __init__(self, used: int, limit: int) -> None:
        self.used = used
        self.limit = limit
        super().__init__(f"max_output_tokens exceeded ({used}/{limit})")


class MaxWallTimeError(BudgetExceededError):
    """La boucle a atteint `max_wall_time_seconds`."""

    def __init__(self, elapsed: float, limit: float) -> None:
        self.elapsed = elapsed
        self.limit = limit
        super().__init__(f"max_wall_time_seconds exceeded ({elapsed:.1f}s/{limit}s)")


class MaxIterationsError(AgentLoopError):
    """`max_iterations` atteint sans que le modele appelle final_answer."""

    def __init__(self, max_iterations: int, last_error: str | None = None) -> None:
        self.max_iterations = max_iterations
        self.last_error = last_error
        message = f"max_iterations reached without final_answer ({max_iterations})"
        if last_error is not None:
            message += f", derniere erreur -> {last_error}"
        super().__init__(message)


class ConsecutiveErrorsError(AgentLoopError):
    """Trop d'erreurs consecutives dans la boucle."""

    def __init__(self, count: int, last_error: str | None = None) -> None:
        self.count = count
        self.last_error = last_error
        message = f"{count} erreurs consecutives"
        if last_error is not None:
            message += f", derniere -> {last_error}"
        super().__init__(message)
