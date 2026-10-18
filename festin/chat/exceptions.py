"""Control exceptions for the chat turn. Strings match live."""


class StaleState(ValueError):
    """Conversation changed on another device or message count drifted."""


class ChatCancelled(Exception):
    """Household stop while a provider call was in flight."""


class StreamBroken(Exception):
    def __init__(self, error_type, showed):
        super().__init__(error_type)
        self.error_type = error_type
        self.showed = showed
