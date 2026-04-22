"""GuiAdapter — IPC/SHM facade для GuiProcess.

GUI не отправляет IPC-данные напрямую (использует RoutedCommandSender
через GuiCommandHandler). Адаптер — заглушка для единообразия структуры.
Добавляй методы по мере роста исходящих IPC-потоков из GUI.
"""


class GuiAdapter:
    """Заглушка — GUI не шлёт IPC через adapter pattern."""

    def __init__(self, process) -> None:
        self._process = process
