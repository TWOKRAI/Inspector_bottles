"""GuiProcess — ProcessModule с Qt event loop в main thread.

Архитектура:
  - main thread: Qt event loop (QApplication.exec())
  - data_receiver worker: получает IPC data-сообщения, emit'ит через DataReceiverBridge
  - _init_system_threads() НЕ переопределён — стандартный framework message_processor
  - FrameShmMiddleware.on_receive — автоматически извлекает numpy frame из SHM
"""

from __future__ import annotations

from multiprocess_framework.modules.process_module.core.process_module import ProcessModule
from multiprocess_framework.modules.router_module.middleware import FrameShmMiddleware
from multiprocess_framework.modules.worker_module import ThreadConfig, ThreadPriority

from .bridge import DataReceiverBridge
from . import app as gui_app


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

        # SHM receive middleware: при получении frame_ready — читать кадр из SHM
        if self.router_manager and self.memory_manager:
            self._recv_frame_mw = FrameShmMiddleware(
                self.memory_manager, owner="camera_0", slot="camera_0_frame"
            )
            self.router_manager.add_receive_middleware(self._recv_frame_mw.on_receive)

        # Создаём bridge в main thread — он будет использоваться из worker
        self._bridge = DataReceiverBridge()

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
        while not stop_event.is_set():
            if pause_event.is_set():
                import time
                time.sleep(0.05)
                continue
            try:
                # return_messages=False → получаем сырые dict (после middleware)
                msgs = self.router_manager.receive(
                    timeout=0.1, channel_types=["data"], return_messages=False
                )
                for msg_dict in msgs:
                    self._bridge.dispatch(msg_dict)
            except Exception as exc:
                self._log_error(
                    f"GuiProcess '{self.name}': ошибка в data_receiver_loop: {exc}",
                    module="gui",
                )

    def run(self) -> None:
        """Запустить базовый ProcessModule (воркеры), затем Qt event loop."""
        super().run()
        # Qt event loop блокирует main thread до закрытия приложения
        gui_app.run_gui(self)
        # После возврата из Qt — сигнализируем об остановке
        self._stop_requested = True

    def shutdown(self) -> bool:
        """Graceful shutdown: сначала останавливаем воркеры, затем базовый shutdown."""
        self._log_info(
            f"GuiProcess '{self.name}': начало graceful shutdown",
            module="gui",
        )
        return super().shutdown()
