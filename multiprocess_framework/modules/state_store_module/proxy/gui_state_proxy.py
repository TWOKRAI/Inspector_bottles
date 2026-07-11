"""gui_state_proxy.py — StateProxy для GUI-процесса с инъекцией delta-sink.

GuiStateProxy переопределяет on_state_changed():
  - обновление кэша происходит в текущем потоке (IO/worker thread, безопасно)
  - дельты передаются в delta_sink — generic callback, инжектируемый GUI-процессом

delta_sink отвечает за маршалинг в Qt main thread (в прототипе — через
DataReceiverBridge, тот же проверенный механизм, что доставляет кадры). Модуль
сам PySide6 НЕ импортирует (sink — обычный Callable), поэтому GuiStateProxy
тестируется без установленного Qt.

Пример использования в GuiProcess:
    def _on_state_deltas_to_bridge(deltas):
        # Вызывается в IO-потоке; bridge.dispatch маршалит в Qt main thread.
        for d in deltas:
            bridge.dispatch({"data_type": "state_delta", "path": d.path, "value": d.new_value})

    proxy = GuiStateProxy("gui", router=router, delta_sink=_on_state_deltas_to_bridge)
    router.register_message_handler("state.changed", proxy.on_state_changed)
"""

from __future__ import annotations

from typing import Any, Callable

from ..interfaces import IRouter
from .state_proxy import StateProxy


class GuiStateProxy(StateProxy):
    """StateProxy с инъекцией delta_sink для доставки дельт в GUI.

    Вместо прямого вызова локальных callbacks в on_state_changed(),
    передаёт дельты в delta_sink — callback, который сам решает, как
    маршалить данные в Qt main thread (в прототипе — через DataReceiverBridge,
    единый проверенный механизм пересечения IO→Qt, как у кадров).

    При delta_sink=None — fallback к прямому вызову локальных callbacks
    (для тестов без Qt и legacy-сценариев).
    """

    def __init__(
        self,
        process_name: str,
        router: IRouter | None = None,
        delta_sink: "Callable[[list], None] | None" = None,
        server_target: str = "ProcessManager",
        manager_name: str | None = None,
        logger: Any = None,
    ) -> None:
        """
        Args:
            process_name: имя GUI-процесса.
            router: реализация IRouter для IPC.
            delta_sink: callback, принимающий список дельт (list[Delta]).
                Вызывается в текущем (IO) потоке; ответственность за маршалинг
                в Qt main thread — на стороне sink (через bridge). При None —
                fallback к прямому вызову локальных callbacks.
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
        self._delta_sink = delta_sink

    # -------------------------------------------------------------------
    # Переопределение on_state_changed — доставка через delta_sink
    # -------------------------------------------------------------------

    def on_state_changed(self, msg: dict) -> None:
        """Обработка state.changed с доставкой дельт в delta_sink.

        1. Десериализует дельты (текущий поток — безопасно).
        2. Устаревший пакет (MED-3, унаследовано из StateProxy) — игнорируется
           целиком, без обновления кэша и без доставки в sink/callbacks.
        3. Иначе — дельты пакета ВСЕГДА обновляют кэш и доставляются в
           delta_sink/callbacks (инвариант (б), унаследовано из StateProxy —
           решение о resync никогда не стоит потери текущего пакета).
        4. Проверяется непрерывность revision (диапазон [first_revision,
           revision], унаследовано из StateProxy) — при разрыве resync
           запускается ДОПОЛНИТЕЛЬНО, как подстраховка.

        Args:
            msg: IPC-сообщение state.changed.
        """
        deltas = self._deserialize_deltas(msg)
        if not deltas:
            return

        data = msg.get("data", {})
        envelope_revision = data.get("revision")

        if envelope_revision is not None and self._is_stale_envelope(envelope_revision):
            self._log_debug(
                f"StateProxy '{self._process_name}': устаревший пакет revision={envelope_revision} "
                f"(last={self._last_revision}) — игнорирую (в полёте до предыдущего resync)"
            )
            return

        # Обновление кэша безопасно из любого потока (только dict-операции)
        self._update_cache(deltas)

        if self._delta_sink is not None:
            # Доставка через sink; маршалинг в Qt main thread — ответственность sink
            self._delta_sink(deltas)
        else:
            # Fallback: прямой вызов локальных callbacks (тесты без Qt)
            self._invoke_callbacks(deltas)

        if envelope_revision is not None:
            first_revision = data.get("first_revision", envelope_revision)
            self._advance_revision_and_maybe_resync(first_revision, envelope_revision)
