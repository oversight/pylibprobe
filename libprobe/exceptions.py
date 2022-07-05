class IgnoreResultException(Exception):
    """IgnoreResultException should be raised by a check if the result needs
    to be ignored.

    - Nothing for this check will be returned to the AgentCore.
    - The check remains scheduled so there will be a next attempt.
    """
    pass


class IgnoreCheckException(Exception):
    """IgnoreResultException should be raised by a check if the result needs
    to be ignored and we no longer want this check to run.

    - Nothing for this check will be returned to the AgentCore.
    - The check will no longer be scheduled, unless new check configuration is
      received.
    """
    pass
