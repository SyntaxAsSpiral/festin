"""Shared API errors."""


class StaleState(ValueError):
    """Client stamp does not match the stored updated_at."""


class NotFound(KeyError):
    """Missing shared row. str() is the public error message."""

    def __str__(self):
        if self.args:
            return str(self.args[0])
        return "Not found"
