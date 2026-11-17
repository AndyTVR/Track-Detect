"""Errors meant for the person using the program."""


class UserError(Exception):
    """Something the user can put right, shown to them as it is (with an HTTP status)."""

    def __init__(self, msg, code=400):
        super().__init__(msg)
        self.code = code
