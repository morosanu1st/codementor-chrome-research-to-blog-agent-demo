class AgentError(RuntimeError):
    """Base error. `retryable=False` stops the step retry loop immediately."""

    retryable = True


class NotLoggedIn(AgentError):
    retryable = False


class LocatorNotFound(AgentError):
    pass


class WaitTimeout(AgentError):
    retryable = False


class StepFailed(AgentError):
    retryable = False
