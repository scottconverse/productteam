"""Shared exceptions for ProductTeam."""


class ProductTeamConfigError(Exception):
    """Raised when ProductTeam configuration is invalid or incomplete."""


class BudgetExceededError(Exception):
    """Raised when cumulative API cost exceeds the configured budget.

    This is a hard stop — the pipeline must not make further API calls.
    The partial work is preserved on disk; the user can resume after
    raising the budget or investigating the cost.
    """

    def __init__(self, spent: float, budget: float, stage: str = ""):
        self.spent = spent
        self.budget = budget
        self.stage = stage
        msg = (
            f"Budget exceeded: ${spent:.4f} spent against ${budget:.2f} limit"
        )
        if stage:
            msg += f" (during {stage})"
        super().__init__(msg)
