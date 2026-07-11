"""CapturePlugin -- захват кадров с вебкамеры.

Source-плагин: produce() возвращает BGR-кадры.
SHM write и IPC send выполняет GenericProcess (SourceProducer).
Запускается в паузе, ждёт команды start_capture.
"""

from __future__ import annotations

import time

import cv2

from multiprocess_framework.modules.process_module.plugins import (
    PluginContext,
    Port,
    ProcessModulePlugin,
    register_plugin,
)

# Максимальное значение счётчика кадров (с rollover как в camera_service)
_FRAME_ID_MODULO = 100_000


@register_plugin("capture", category="source", description="Захват кадров с вебкамеры (cv2)")
class CapturePlugin(ProcessModulePlugin):
    """Захват кадров с вебкамеры через cv2.VideoCapture.

    Lifecycle:
        configure() -- параметры камеры + команды start/stop
        start()     -- auto_start если задан в конфиге
        produce()   -- захват одного кадра (вызывается SourceProducer)
        shutdown()  -- освобождение камеры
    """

    name = "capture"
    category = "source"

    # Манифест (Ф4 Task 4.4, пилот): commands (start/stop/...) регистрируются
    # только через ctx.command_manager (_auto_register_commands) — без него
    # source остаётся без пультового управления (тихая деградация, не падение).
    VERSION = "1.0.0"
    REQUIRES: tuple[str, ...] = ("manager:command_manager",)

    inputs = []
    outputs = [
        Port(name="frame", dtype="image/bgr", shape="(H, W, 3)", description="BGR-кадр с камеры"),
    ]

    commands = {
        "start_capture": "cmd_start_capture",
        "stop_capture": "cmd_stop_capture",
        "pause_capture": "cmd_pause_capture",
        "resume_capture": "cmd_resume_capture",
        # Заморозка: камера перестаёт читать новые кадры, но переотправляет
        # последний (pipeline продолжает обрабатывать статичный кадр для тюнинга).
        "freeze_capture": "cmd_freeze_capture",
        "unfreeze_capture": "cmd_unfreeze_capture",
    }

    def configure(self, ctx: PluginContext) -> None:
        """Настройка параметров камеры."""
        cfg = ctx.config
        self._camera_id: int = cfg.get("camera_id", 0)
        self._device_id: int = cfg.get("device_id", 0)
        self._fps: int = cfg.get("fps", 25)
        self._width: int = cfg.get("resolution_width", 640)
        self._height: int = cfg.get("resolution_height", 480)
        self._auto_start: bool = cfg.get("auto_start", False)

        ctx.log_info(
            f"CapturePlugin[{self._camera_id}]: device={self._device_id}, {self._width}x{self._height}@{self._fps}fps"
        )

        # Состояние захвата
        self._cap: cv2.VideoCapture | None = None
        self._is_capturing = False
        self._paused = False
        self._frame_count = 0
        self._ctx = ctx

        # Заморозка кадра: re-emit последнего кадра для тюнинга на статике
        self._frozen = False
        self._last_frame = None

        # Метрики FPS и потерь кадров
        self._state_proxy = ctx.state_proxy  # может быть None (обратная совместимость)
        self._fps_counter = 0
        self._fps_timer = time.monotonic()
        self._actual_fps = 0.0
        self._drops = 0

    # --- Команды (авторегистрация через commands dict) ---

    def cmd_start_capture(self, data: dict) -> dict:
        self._start_capture(self._ctx)
        return {"status": "ok"}

    def cmd_stop_capture(self, data: dict) -> dict:
        self._stop_capture(self._ctx)
        return {"status": "ok"}

    def cmd_pause_capture(self, data: dict) -> dict:
        self._paused = True
        self._ctx.log_info(f"CapturePlugin[{self._camera_id}]: захват приостановлен")
        self._publish_state()
        return {"status": "ok"}

    def cmd_resume_capture(self, data: dict) -> dict:
        self._paused = False
        self._ctx.log_info(f"CapturePlugin[{self._camera_id}]: захват возобновлён")
        self._publish_state()
        return {"status": "ok"}

    def cmd_freeze_capture(self, data: dict) -> dict:
        """Заморозить кадр: камера не читает новые, переотправляет последний."""
        if self._last_frame is None:
            return {"status": "error", "message": "нет кадра для заморозки"}
        self._frozen = True
        self._ctx.log_info(f"CapturePlugin[{self._camera_id}]: кадр заморожен (тюнинг)")
        self._publish_state()
        return {"status": "ok", "frozen": True}

    def cmd_unfreeze_capture(self, data: dict) -> dict:
        """Разморозить: вернуться к живому захвату."""
        self._frozen = False
        self._ctx.log_info(f"CapturePlugin[{self._camera_id}]: захват разморожен")
        self._publish_state()
        return {"status": "ok", "frozen": False}

    def start(self, ctx: PluginContext) -> None:
        """Auto-start камеры если задан в конфиге."""
        if self._auto_start:
            self._start_capture(ctx)

    def shutdown(self, ctx: PluginContext) -> None:
        """Освобождение камеры."""
        ctx.log_info(f"CapturePlugin[{self._camera_id}]: shutdown...")
        self._is_capturing = False
        self._release_camera()

    def produce(self) -> list[dict]:
        """Захватить один кадр с камеры.

        Возвращает [{"frame": ndarray, "camera_id": int, ...}] или [].
        SHM write и IPC send выполняет SourceProducer.
        """
        # Заморозка: переотправляем последний кадр (новый seq_id), не читая камеру.
        if self._frozen and self._last_frame is not None:
            self._frame_count = (self._frame_count % _FRAME_ID_MODULO) + 1
            return [self._build_item(self._last_frame.copy())]

        if not self._is_capturing or self._cap is None or self._paused:
            return []

        try:
            ret, frame = self._cap.read()
        except Exception as exc:
            # contain → report → degrade (Ф2 Task 2.4): ошибку НЕ пробрасываем
            # (проброс обрушит воркер), но честно кормим health — после порога
            # подряд-ошибок breaker сам переведёт процесс в degraded.
            self._ctx.health.report_error(exc, context="capture: чтение кадра камеры (_cap.read)")
            return []

        if not ret or frame is None:
            # Считаем потерянные кадры (camera.read() не вернул данные)
            self._drops += 1
            return []

        # Resize если камера отдаёт другое разрешение
        h, w = frame.shape[:2]
        if w != self._width or h != self._height:
            frame = cv2.resize(frame, (self._width, self._height))

        # Запоминаем последний кадр для возможной заморозки
        self._last_frame = frame

        # Инкремент счётчика с rollover
        self._frame_count = (self._frame_count % _FRAME_ID_MODULO) + 1

        # Обновление FPS-метрики раз в секунду
        self._fps_counter += 1
        now = time.monotonic()
        elapsed = now - self._fps_timer
        if elapsed >= 1.0:
            self._actual_fps = self._fps_counter / elapsed
            self._fps_counter = 0
            self._fps_timer = now
            self._publish_state()

        return [self._build_item(frame)]

    def _build_item(self, frame) -> dict:
        """Собрать item-словарь кадра (общий для живого захвата и заморозки)."""
        return {
            "frame": frame,
            "camera_id": self._camera_id,
            "seq_id": self._frame_count,
            "frame_id": self._frame_count,
            "timestamp": time.monotonic(),
            "width": self._width,
            "height": self._height,
            "channels": 3,
            "dtype": "uint8",
        }

    # --- Внутренние методы ---

    def _start_capture(self, ctx: PluginContext) -> None:
        """Открыть камеру и начать захват."""
        if self._is_capturing:
            return
        self._cap = cv2.VideoCapture(self._device_id, cv2.CAP_DSHOW)
        if self._cap.isOpened():
            self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, self._width)
            self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self._height)
            self._cap.set(cv2.CAP_PROP_FPS, self._fps)
            actual_w = int(self._cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            actual_h = int(self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            ctx.log_info(
                f"CapturePlugin[{self._camera_id}]: камера открыта (реальное разрешение: {actual_w}x{actual_h})"
            )
            self._is_capturing = True
            ctx.log_info(f"CapturePlugin[{self._camera_id}]: захват запущен")
            # Публикуем начальное состояние после старта захвата
            self._publish_state()
        else:
            ctx.log_error(f"CapturePlugin[{self._camera_id}]: не удалось открыть камеру {self._device_id}")

    def _stop_capture(self, ctx: PluginContext) -> None:
        """Остановить захват и сбросить FPS-метрику."""
        self._is_capturing = False
        self._release_camera()
        ctx.log_info(f"CapturePlugin[{self._camera_id}]: захват остановлен")
        # Сбрасываем FPS и публикуем финальное состояние
        self._actual_fps = 0.0
        self._publish_state()

    def _publish_state(self) -> None:
        """Опубликовать метрики в StateStore."""
        if self._state_proxy is None:
            return
        path = f"processes.{self._ctx.process_name}.state"
        self._state_proxy.merge(
            path,
            {
                "status": "running" if self._is_capturing else "stopped",
                "fps": round(self._actual_fps, 1),
                "frame_count": self._frame_count,
                "drops": self._drops,
                "paused": self._paused,
                "frozen": self._frozen,
            },
        )

    def _release_camera(self) -> None:
        """Освободить камеру."""
        if self._cap is not None:
            self._cap.release()
            self._cap = None
