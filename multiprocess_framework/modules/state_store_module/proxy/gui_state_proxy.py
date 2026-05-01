"""gui_state_proxy.py — Qt-safe StateProxy для GUI-процесса.

GuiStateProxy переопределяет on_state_changed():
  - обновление кэша происходит в текущем потоке (IO/worker thread, безопасно)
  - вызов callbacks маршрутизируется в Qt main thread через QMetaObject.invokeMethod

PySide6 НЕ импортируется на верхнем уровне — только lazily внутри методов.
Это позволяет тестировать GuiStateProxy без установленного Qt.

Пример использования в GuiProcess:
    class GuiEmitter(QObject):
        state_deltas = Signal(list)

        @Slot(list)
        def _on_state_deltas(self, deltas):
            # Вызывается в main thread
            pass

    emitter = GuiEmitter()
    proxy = GuiStateProxy("gui", router=router, signal_emitter=emitter)
    router.register_message_handler("state.changed", proxy.on_state_changed)
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..interfaces import IRouter
from .state_proxy import StateProxy

if TYPE_CHECKING:
    from PySide6.QtCore import QObject


class GuiStateProxy(StateProxy):
    """Qt-safe StateProxy. Callbacks маршрутизируются в Qt main thread.

    Вместо прямого вызова callback в on_state_changed(),
    emit'ит Qt signal через QMetaObject.invokeMethod (QueuedConnection),
    чтобы избежать race condition при обновлении GUI из worker-потока.

    При signal_emitter=None — fallback к прямому вызову (для тестов без Qt).
    """

    def __init__(
        self,
        process_name: str,
        router: IRouter | None = None,
        signal_emitter: "QObject | None" = None,
        server_target: str = "ProcessManager",
        manager_name: str | None = None,
        logger: Any = None,
    ) -> None:
        """
        Args:
            process_name: имя GUI-процесса.
            router: реализация IRouter для IPC.
            signal_emitter: QObject с методом _on_state_deltas(deltas: list).
                            Должен быть создан в Qt main thread.
            server_target: имя процесса-сервера StateStore (ADR-SS-002).
            manager_name: имя для BaseManager.
            logger: LoggerManager или ObservableMixin-совместимый объект.
        """
        super().__init__(
            process_name,
            router,
            server_target=server_target,
            manager_name=manager_name,
            logger=logger,
        )
        self._signal_emitter = signal_emitter

    # -------------------------------------------------------------------
    # Переопределение on_state_changed — Qt-safe версия
    # -------------------------------------------------------------------

    def on_state_changed(self, msg: dict) -> None:
        """Обработка state.changed с маршрутизацией callbacks в Qt main thread.

        1. Десериализует дельты (текущий поток — безопасно).
        2. Обновляет кэш (только dict-операция — безопасно).
        3. Если signal_emitter задан — вызывает _on_state_deltas через
           QMetaObject.invokeMethod с QueuedConnection.
        4. Иначе — прямой вызов callbacks (fallback для тестов без Qt).

        Args:
            msg: IPC-сообщение state.changed.
        """
        deltas = self._deserialize_deltas(msg)
        if not deltas:
            return

        # Обновление кэша безопасно из любого потока (только dict-операции)
        self._update_cache(deltas)

        if self._signal_emitter is not None:
            # Маршрутизация в Qt main thread через invokeMethod
            self._dispatch_via_qt(deltas)
        else:
            # Fallback: прямой вызов (тесты без Qt, или нет emitter'а)
            self._invoke_callbacks(deltas)

    # -------------------------------------------------------------------
    # Вспомогательные методы
    # -------------------------------------------------------------------

    def _dispatch_via_qt(self, deltas: list) -> None:
        """Передать дельты в Qt main thread через QMetaObject.invokeMethod.

        Использует QueuedConnection — вызов будет выполнен при следующей итерации
        event loop главного потока. Это гарантирует thread-safety для Qt GUI.

        Args:
            deltas: список Delta для передачи в callbacks.
        """
        try:
            from PySide6.QtCore import QMetaObject, Qt, Q_ARG  # type: ignore[import]

            QMetaObject.invokeMethod(
                self._signal_emitter,
                "_on_state_deltas",
                Qt.ConnectionType.QueuedConnection,
                Q_ARG(list, deltas),
            )
        except ImportError:
            self._log_warning(
                f"GuiStateProxy '{self._process_name}': PySide6 недоступен, прямой вызов callbacks"
            )
            self._invoke_callbacks(deltas)
        except Exception as exc:
            self._log_error(
                f"GuiStateProxy '{self._process_name}': ошибка invokeMethod, прямой вызов callbacks: {exc}"
            )
            self._invoke_callbacks(deltas)
