# -*- coding: utf-8 -*-
"""RequestRunner — блокирующий request() на worker-потоке, результат в Qt main-thread.

command-result-bridge P2. `CommandSender.request_*` (P1) блокирует поток до ответа
PM. Звать его из Qt main-thread = фриз UI на время операции (`blueprint.replace` —
секунды). RequestRunner гонит request на потоке `QThreadPool`, а результат доставляет
обратно в main-thread через internal `Signal` с `AutoConnection` (тот же приём, что
`DataReceiverBridge` для кадров/телеметрии).

Контракт потока (P0.5): `request()` НЕ должен вызываться из приёмного потока процесса.
Здесь он исполняется на потоке пула — отдельном и от Qt main, и от system/data
receive-потоков GuiProcess. Дедлока нет, UI не фризится.
"""

from __future__ import annotations

from typing import Any, Callable

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, Signal, Slot

__all__ = ["RequestRunner"]

ResultCallback = Callable[[dict[str, Any]], None]


class _RequestTask(QRunnable):
    """QRunnable: выполняет блокирующий ``fn`` (request) на потоке пула.

    Любое исключение превращается в error-result — поток пула не падает,
    инициатор всегда получает ответ (success=False), а не виснет.
    """

    def __init__(self, fn: Callable[[], dict[str, Any]], on_done: ResultCallback) -> None:
        super().__init__()
        self._fn = fn
        self._on_done = on_done

    def run(self) -> None:  # noqa: D401 — Qt-хук
        try:
            result = self._fn()
        except Exception as exc:  # noqa: BLE001 — любую ошибку → error-result (не валить поток пула)
            result = {"success": False, "error": str(exc)}
        if not isinstance(result, dict):
            result = {"success": True, "result": result}
        self._on_done(result)


class RequestRunner(QObject):
    """Запускает блокирующий request на worker-потоке; ответ — в Qt main-thread.

    Использование::

        runner = RequestRunner()
        runner.submit(lambda: sender.request_system_command({...}), on_result=cb)
        # cb(result_dict) будет вызван в Qt main-thread

    ``_delivered``-сигнал с ``AutoConnection`` пересекает поток: emit идёт из
    потока пула, slot исполняется в потоке, которому принадлежит RequestRunner
    (main-thread, если создан там).
    """

    # (result_dict, on_result_callback | None) — callback переносится через сигнал,
    # чтобы исполниться строго в main-thread вместе с результатом.
    _delivered = Signal(object, object)

    def __init__(self, parent: QObject | None = None, pool: QThreadPool | None = None) -> None:
        super().__init__(parent)
        self._pool = pool or QThreadPool.globalInstance()
        self._delivered.connect(self._on_delivered, Qt.ConnectionType.AutoConnection)

    def submit(self, fn: Callable[[], dict[str, Any]], on_result: ResultCallback | None = None) -> None:
        """Выполнить ``fn`` на worker-потоке; ``on_result`` — в main-thread.

        Args:
            fn: блокирующий вызов (обычно ``lambda: sender.request_system_command(...)``),
                возвращает dict-ответ.
            on_result: callback результата; вызывается в main-thread. None → fire-and-go
                (результат просто игнорируется, но request всё равно выполнен off-main).
        """
        task = _RequestTask(fn, lambda result: self._delivered.emit(result, on_result))
        self._pool.start(task)

    @Slot(object, object)
    def _on_delivered(self, result: dict[str, Any], on_result: ResultCallback | None) -> None:
        """Slot в main-thread: вызвать callback результата."""
        if on_result is not None:
            on_result(result)
