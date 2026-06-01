"""GuiProcess — ProcessModule с Qt event loop в main thread.

Архитектура:
  - main thread: Qt event loop (QApplication.exec())
  - data_receiver worker: получает IPC data-сообщения, emit'ит через DataReceiverBridge
  - _init_system_threads() НЕ переопределён — стандартный framework message_processor
  - FrameShmMiddleware.on_receive — автоматически извлекает numpy frame из SHM
"""

from __future__ import annotations

import sys
import time

from PySide6.QtCore import QObject, Slot

from multiprocess_framework.modules.process_module.core.process_module import ProcessModule
from multiprocess_framework.modules.router_module.middleware import FrameShmMiddleware
from multiprocess_framework.modules.worker_module import ThreadConfig, ThreadPriority

from .bridge import DataReceiverBridge
from . import app as gui_app


class _StateDeltaEmitter(QObject):
    """Qt main-thread приёмник дельт StateStore → bridge.dispatch(state_delta).

    GuiStateProxy.on_state_changed (system/IO-поток) маршрутизирует дельты сюда через
    QMetaObject.invokeMethod(QueuedConnection) — слот исполняется в main thread.
    Каждая дельта конвертируется в state_delta-сообщение и уходит в существующий
    bridge → GuiStateBindings (реактивные подписки виджетов карточек/воркеров).
    """

    def __init__(self, bridge: DataReceiverBridge) -> None:
        super().__init__()
        self._bridge = bridge

    @Slot(list)
    def _on_state_deltas(self, deltas: list) -> None:
        for d in deltas:
            self._bridge.dispatch({"data_type": "state_delta", "path": d.path, "value": d.new_value})


class GuiProcess(ProcessModule):
    """ProcessModule с Qt event loop в main thread.

    run() запускает Qt event loop и блокирует main thread до закрытия окна.
    Данные от других процессов поступают через data_receiver worker (отдельный поток),
    который emit'ит Qt signals через DataReceiverBridge (queued connection).

    FrameShmMiddleware.on_receive подключён к router — входящие frame_ready
    автоматически обогащаются numpy frame из SHM (msg["frame"]).
    """

    # _init_system_threads() — НЕ переопределён: стандартный framework message_processor

    def _init_application_threads(self) -> None:
        """Создать DataReceiverBridge, SHM middleware и worker data_receiver."""
        super()._init_application_threads()

        # SHM receive middleware: при получении данных — читать кадр из SHM
        # owner/slot — fallback, реальные координаты берутся из msg["data"]
        if self.router_manager and self.memory_manager:
            self._recv_frame_mw = FrameShmMiddleware(self.memory_manager, owner=self.name, slot="output_frames")
            self.router_manager.add_receive_middleware(self._recv_frame_mw.on_receive)

        # Создаём bridge в main thread — он будет использоваться из worker
        self._bridge = DataReceiverBridge()

        # StateStore-подписчик: live-телеметрия процессов/воркеров.
        # ProcessMonitor публикует processes.X.state.* / processes.X.workers.Y.* →
        # DeltaDispatcher шлёт state.changed (через queue_registry, U1) → handler здесь →
        # emitter (Qt main thread) → bridge → GuiStateBindings обновляют виджеты.
        from multiprocess_framework.modules.state_store_module.proxy.gui_state_proxy import (
            GuiStateProxy,
        )

        self._state_emitter = _StateDeltaEmitter(self._bridge)
        self._gui_state_proxy = GuiStateProxy(
            process_name=self.name,
            router=self.router_manager,
            signal_emitter=self._state_emitter,
            server_target="ProcessManager",
            logger=self,
        )
        self._gui_state_proxy.initialize()
        if self.router_manager:
            # Регистрируем handler вручную (self.state_proxy оставляем None, чтобы не
            # активировать сторонние GUI-адаптеры и не словить двойную регистрацию
            # через _init_state_proxy / ADR-SS-006).
            self.router_manager.register_message_handler("state.changed", self._gui_state_proxy.on_state_changed)
            # Серверная подписка на телеметрию (callback пуст — доставку в виджеты
            # делает emitter через bridge; подписка нужна, чтобы DeltaDispatcher слал
            # дельты на 'gui'). Не блокирует старт: subscribe — fire-and-forget.
            try:
                self._gui_state_proxy.subscribe("processes.**", lambda _deltas: None, exclude_self=True)
            except Exception as exc:
                self._log_warning(
                    f"GuiProcess '{self.name}': подписка на processes.** не удалась: {exc}",
                    module="gui",
                )

        # Создаём worker для получения IPC data-сообщений
        config = ThreadConfig(priority=ThreadPriority.NORMAL)
        self.worker_manager.create_worker(
            "data_receiver",
            self._data_receiver_loop,
            config,
            auto_start=True,
        )

        self._log_info(
            f"GuiProcess '{self.name}': bridge + SHM middleware + data_receiver созданы",
            module="gui",
        )

    def _data_receiver_loop(self, stop_event, pause_event) -> None:
        """Цикл получения IPC data-сообщений и передачи в Qt через bridge."""
        _trace_cnt = 0
        _consecutive_errors = 0
        _backoff = 0.1  # начальный backoff (секунды)
        _MAX_BACKOFF = 5.0
        _ERROR_THRESHOLD = 5  # порог для вызова _log_critical

        while not stop_event.is_set():
            if pause_event.is_set():
                time.sleep(0.05)
                continue
            try:
                # return_messages=False → получаем сырые dict (после middleware)
                msgs = self.router_manager.receive(timeout=0.1, channel_types=["data"], return_messages=False)
                for msg_dict in msgs:
                    _trace_cnt += 1
                    if _trace_cnt % 30 == 1:
                        data = msg_dict.get("data", {})
                        self._log_info(
                            f"[TRACE] GuiProcess.data_receiver: msg #{_trace_cnt}, "
                            f"data_type={msg_dict.get('data_type', '?')}, "
                            f"has_frame={'frame' in msg_dict}, "
                            f"has_data_shm={bool(data.get('shm_name') if isinstance(data, dict) else False)}",
                            module="gui",
                        )
                    self._bridge.dispatch(msg_dict)

                # При успешном получении — сбрасываем счётчик ошибок
                if msgs:
                    if _consecutive_errors > 0:
                        self._log_info(
                            f"data_receiver: восстановление после {_consecutive_errors} ошибок подряд",
                            module="gui",
                        )
                    _consecutive_errors = 0
                    _backoff = 0.1
                    self._record_metric("data_receiver.success")

            except Exception as exc:
                _consecutive_errors += 1

                # Трекинг через ErrorManager (единый паттерн)
                self._track_error(
                    exc,
                    context={
                        "loop": "data_receiver",
                        "consecutive": _consecutive_errors,
                    },
                )

                # Метрика через StatsManager
                self._record_metric("data_receiver.errors")

                # После порога — critical лог
                if _consecutive_errors == _ERROR_THRESHOLD:
                    self._log_critical(
                        f"data_receiver: {_consecutive_errors} ошибок подряд, последняя: {exc}",
                        module="gui",
                    )

                # Exponential backoff
                time.sleep(min(_backoff, _MAX_BACKOFF))
                _backoff = min(_backoff * 2, _MAX_BACKOFF)

    def run(self) -> None:
        """Запустить базовый ProcessModule (воркеры), затем Qt event loop.

        Поддерживает перезапуск UI без перезапуска процесса:
        если _restart_ui == True после выхода из Qt loop,
        QApplication пересоздаётся и run_gui() вызывается заново.
        При рестарте Python-модули frontend перезагружаются — подхватываются
        новые файлы без перезапуска всего приложения.
        """
        super().run()
        self._restart_ui = False
        while True:
            gui_app.run_gui(self)
            if not self._restart_ui:
                break
            self._restart_ui = False
            self._stop_requested = False
            self._reload_frontend_modules()
            self._log_info("GuiProcess: перезапуск UI по запросу", module="gui")
        # После возврата из Qt (реальное закрытие, НЕ _restart_ui — иначе while не
        # вышел бы) — сигнализируем об остановке и гасим ВСЮ систему.
        self._stop_requested = True
        self._request_system_shutdown()

    def _request_system_shutdown(self) -> None:
        """Закрытие окна = выключение всей системы.

        GuiProcess — дочерний процесс ProcessManager'а. Без этого сигнала закрытие
        окна гасило бы только сам GuiProcess, а ProcessManager и воркеры остались бы
        жить headless (launcher висит в join-цикле и не доходит до
        ``_kill_orphan_children``). Шлём ``system.shutdown`` в ProcessManager — он
        ставит ``stop_event`` → каскадный teardown дерева. Fire-and-forget: ответ не
        нужен, важна доставка. Best-effort: ошибка на выходе не критична.
        """
        try:
            from multiprocess_framework.modules.message_module import build_system_command_message

            msg = build_system_command_message({"cmd": "system.shutdown"}, sender=self.name)
            self.send_message("ProcessManager", msg)
            self._log_info(
                "GuiProcess: послан system.shutdown в ProcessManager (закрытие окна)",
                module="gui",
            )
        except Exception as exc:  # noqa: BLE001 — best-effort на выходе процесса
            self._log_warning(f"GuiProcess: не удалось послать system.shutdown: {exc}", module="gui")

    def _reload_frontend_modules(self) -> None:
        """Перезагрузить Python-модули frontend для подхвата новых файлов.

        Удаляем из sys.modules все модули multiprocess_prototype.frontend.*
        (кроме process и bridge — они живут между рестартами).
        При следующем import Python загрузит актуальные .py-файлы.
        """
        import importlib

        keep_prefixes = (
            "multiprocess_prototype.frontend.process",
            "multiprocess_prototype.frontend.bridge",
        )
        to_remove = [
            name
            for name in sys.modules
            if name.startswith("multiprocess_prototype.frontend") and not any(name.startswith(p) for p in keep_prefixes)
        ]
        for name in to_remove:
            del sys.modules[name]

        # Перезагружаем сам app-модуль чтобы подхватить новые импорты
        importlib.invalidate_caches()
        import multiprocess_prototype.frontend.app as _app_mod

        importlib.reload(_app_mod)

        # Обновляем ссылку на уровне модуля
        global gui_app
        gui_app = _app_mod

    def shutdown(self) -> bool:
        """Graceful shutdown: сначала останавливаем воркеры, затем базовый shutdown."""
        self._log_info(
            f"GuiProcess '{self.name}': начало graceful shutdown",
            module="gui",
        )
        proxy = getattr(self, "_gui_state_proxy", None)
        if proxy is not None:
            try:
                proxy.shutdown()
            except Exception:  # nosec B110 — shutdown best-effort
                pass
        return super().shutdown()
