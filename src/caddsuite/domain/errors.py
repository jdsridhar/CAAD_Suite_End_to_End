"""Domain-level execution lifecycle signals shared across workflow and execution layers."""


class ExecutionCancelled(RuntimeError):
    """Raised only after a requested local process cancellation has been confirmed."""
