"""Утилиты сообщений на границе процесса (dict / MessageAdapter)."""


def message_as_dict(msg) -> dict:
    if msg is None:
        return {}
    if isinstance(msg, dict):
        return msg
    if hasattr(msg, "to_dict"):
        return msg.to_dict()
    return {}
