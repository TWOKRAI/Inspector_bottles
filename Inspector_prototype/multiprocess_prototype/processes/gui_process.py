"""
GuiProcess — отображение видео и управление (PyQt5).

Consumer rendered_frame. QTimer для опроса сообщений в главном потоке.
Без воркеров — PyQt в главном потоке.
"""

import sys

import numpy as np

from multiprocess_framework.refactored.modules.process_module import ProcessModule
from multiprocess_framework.refactored.modules.message_module import MessageAdapter
from multiprocess_prototype.utils.shm_utils import read_frame_from_shm


class GuiProcess(ProcessModule):
    """
    GUI-процесс с PyQt5.

    run() запускает QApplication.exec_() — блокирующий вызов.
    QTimer опрашивает входящие сообщения. Воркеры не создаются.
    """

    def _init_application_threads(self):
        """GUI без воркеров — только конфиг."""
        self._log_info("GuiProcess initializing...")

        self._msg = MessageAdapter(sender=self.name)

        self._poll_interval = self.get_config("poll_interval_ms", 16)
        self._window_title = self.get_config("window_title", "Inspector Prototype")
        self._window_width = self.get_config("window_width", 1024)
        self._window_height = self.get_config("window_height", 768)
        self._log_info("GuiProcess ready (no workers)")

    def _init_system_threads(self):
        """GUI не использует message_processor — опрос через QTimer в главном потоке."""
        pass

    def _stop_system_threads(self):
        """Нет системных потоков для остановки."""
        pass

    def run(self):
        """Основной цикл GUI — QApplication.exec_()."""
        from PyQt5.QtWidgets import QApplication
        from PyQt5.QtCore import QTimer

        from multiprocess_prototype.gui.main_window import InspectorWindow

        app = QApplication(sys.argv)

        # При любом выходе (крестик, Cmd+Q и т.д.) — запрос на остановку всех процессов
        app.aboutToQuit.connect(self.gui_request_shutdown)

        self._window = InspectorWindow(
            title=self._window_title,
            width=self._window_width,
            height=self._window_height,
            process=self,
        )
        self._window.show()

        self._timer = QTimer()
        self._timer.timeout.connect(self._poll_messages)
        self._timer.start(self._poll_interval)

        self._stop_timer = QTimer()
        self._stop_timer.timeout.connect(lambda: self._check_stop(app))
        self._stop_timer.start(100)

        app.exec_()

    def _poll_messages(self):
        """Вызывается QTimer. Читает rendered_frame_ready."""
        msgs = self.receive(timeout=0.001, channel_types=['data'])
        if msgs:
            types = [m.get("data_type", m.get("type", "?")) for m in msgs if isinstance(m, dict)]
            if getattr(self, "_gui_msg_count", 0) < 5:
                self._gui_msg_count = getattr(self, "_gui_msg_count", 0) + len(msgs)
                self._log_info(f"[DEBUG] gui: received {len(msgs)} msg(s), data_types={types}")
        for msg in msgs:
            if isinstance(msg, dict):
                msg_dict = msg
            elif hasattr(msg, "to_dict"):
                msg_dict = msg.to_dict()
            else:
                continue
            if msg_dict.get("data_type") == "rendered_frame_ready":
                self._handle_new_frame(msg_dict.get("data", {}))

    def _handle_new_frame(self, data: dict):
        """Получен новый отрендеренный кадр (оригинал + маска)."""
        shm_actual_name = data.get("shm_actual_name")
        mask_shm_actual_name = data.get("mask_shm_actual_name")
        width = data.get("width", 640)
        height = data.get("height", 480)
        frame_id = data.get("frame_id", 0)
        show_original = data.get("show_original", True)
        show_mask = data.get("show_mask", True)

        original_frame = None
        mask_frame = None
        mm = self.memory_manager
        shm_index = data.get("shm_index", 0)
        mask_shm_index = data.get("mask_shm_index", 0)

        if mm:
            images = mm.read_images("renderer", "rendered_frame", shm_index, n=1)
            if images:
                original_frame = images[0]
            if mask_shm_actual_name:
                mask_images = mm.read_images("renderer", "mask_frame", mask_shm_index, n=1)
                if mask_images:
                    mask_frame = mask_images[0]
        if original_frame is None and shm_actual_name:
            original_frame = read_frame_from_shm(shm_actual_name, width, height)
        if mask_frame is None and mask_shm_actual_name:
            mask_frame = read_frame_from_shm(mask_shm_actual_name, width, height)

        if self._window:
            if frame_id <= 3 or frame_id % 50 == 0:
                self._log_info(
                    f"[DEBUG] gui: update_frame frame_id={frame_id} "
                    f"original={original_frame.shape if original_frame is not None else None} "
                    f"mask={mask_frame.shape if mask_frame is not None else None}"
                )
            self._window.update_frame(
                original_frame if original_frame is not None else np.zeros((height, width, 3), dtype=np.uint8),
                mask_frame if mask_frame is not None else np.zeros((height, width, 3), dtype=np.uint8),
                frame_id,
                show_original=show_original,
                show_mask=show_mask,
            )

    def _check_stop(self, app):
        """Проверка stop_event для graceful shutdown."""
        if self.should_stop():
            app.quit()

    # === Методы для вызова из GUI ===

    def gui_request_shutdown(self):
        """Запрос на остановку всей системы (при закрытии окна или Cmd+Q)."""
        try:
            self._log_info("GUI: requesting system shutdown")
            msg = self._msg.command(
                targets=["ProcessManager"],
                command="system.shutdown",
                args={},
                data={},
            )
            ok = self.send_message("ProcessManager", msg.to_dict())
            self._log_info(f"GUI: shutdown request sent, ok={ok}")
        except Exception as e:
            self._log_error(f"GUI: failed to send shutdown: {e}")

    def gui_start_capture(self):
        self._log_info("[DEBUG] gui: gui_start_capture -> sending start_capture to camera")
        msg = self._msg.command(targets=["camera"], command="start_capture", args={}, data={})
        self.send_message("camera", msg.to_dict())

    def gui_stop_capture(self):
        msg = self._msg.command(targets=["camera"], command="stop_capture", args={}, data={})
        self.send_message("camera", msg.to_dict())

    def gui_set_fps(self, fps: int):
        msg = self._msg.command(
            targets=["camera"],
            command="set_fps",
            args={"fps": fps},
            data={"fps": fps},
        )
        self.send_message("camera", msg.to_dict())

    def gui_set_color_range(
        self,
        b_lower: int,
        g_lower: int,
        r_lower: int,
        b_upper: int,
        g_upper: int,
        r_upper: int,
    ):
        """Отправка BGR-диапазона в processor для детекции цвета."""
        msg = self._msg.command(
            targets=["processor"],
            command="set_color_range",
            args={},
            data={
                "color_lower": [b_lower, g_lower, r_lower],
                "color_upper": [b_upper, g_upper, r_upper],
            },
        )
        self.send_message("processor", msg.to_dict())

    def gui_set_min_area(self, min_area: int):
        msg = self._msg.command(
            targets=["processor"],
            command="set_min_area",
            args={"min_area": min_area},
            data={"min_area": min_area},
        )
        self.send_message("processor", msg.to_dict())

    def gui_set_show_original(self, show: bool):
        msg = self._msg.command(
            targets=["renderer"],
            command="set_show_original",
            args={"show_original": show},
            data={"show_original": show},
        )
        self.send_message("renderer", msg.to_dict())

    def gui_set_show_mask(self, show: bool):
        msg = self._msg.command(
            targets=["renderer"],
            command="set_show_mask",
            args={"show_mask": show},
            data={"show_mask": show},
        )
        self.send_message("renderer", msg.to_dict())

    def gui_set_draw_contours(self, draw: bool):
        msg = self._msg.command(
            targets=["renderer"],
            command="set_draw_contours",
            args={"draw_contours": draw},
            data={"draw_contours": draw},
        )
        self.send_message("renderer", msg.to_dict())
