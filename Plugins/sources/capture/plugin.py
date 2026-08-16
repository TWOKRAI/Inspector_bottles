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
        # Задача 2.1: сколько потерь уже отдано в плоскость stats. ``_drops``
        # накопительный, а counter принимает ПРИРОСТ — отдай мы сумму, окно
        # сложило бы её с предыдущими и «потерь за смену» вышло бы
        # квадратичным. Позиция одна, вычитается здесь же.
        self._drops_reported = 0

        # Task 3.5: имена уровней объявляются РЯДОМ с полями, которые их считают, —
        # только объявленным именем умеет управлять publisher-gate (он обходит
        # каталог объявлений). ``fps`` в этом списке нет намеренно: имя уже
        # объявлено фреймворком, который считает одноимённый агрегат по воркерам,
        # и второе объявление на то же имя — законный отказ реестра
        # (см. :meth:`_publish_levels`).
        ctx.declare_metric("frame_count")
        ctx.declare_metric("drops")

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
        # Такт метрик — ПЕРВЫМ делом, до всех ранних `return`. Раньше он стоял в
        # ветке успешного кадра, и плоскость слепла ровно в отказном режиме:
        # при `ret=False` управление уходило по `return []` выше, и на 485
        # потерянных кадров за 1.4 с не эмитилось НИ ОДНОЙ метрики — ни
        # `capture.drops`, ни `capture.fps=0`. «Камера умерла» было неотличимо
        # от «процесс простаивает» (находка ревью 2.1, воспроизведена).
        self._tick_stats()

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

        self._fps_counter += 1

        return [self._build_item(frame)]

    def _tick_stats(self) -> None:
        """Раз в секунду: пересчитать fps, опубликовать состояние, отдать метрики.

        Зовётся в НАЧАЛЕ ``produce``, до любых ранних выходов, — потому что
        отвечать эта ветка должна и на «кадров нет»: молчание плоскости в
        отказном режиме и есть тот сигнал, который нужен оператору больше всего.
        """
        now = time.monotonic()
        elapsed = now - self._fps_timer
        if elapsed < 1.0:
            return
        self._actual_fps = self._fps_counter / elapsed
        self._emit_stats(self._fps_counter)
        self._fps_counter = 0
        self._fps_timer = now
        self._publish_state()
        self._publish_levels()

    def _emit_stats(self, frames_in_window: int) -> None:
        """Отдать бизнес-метрики захвата тем же жестом, что лог (задача 2.1).

        **Первый боевой эмитент плоскости stats.** До него у плоскости не было
        ни одного: разъём (1.1) существовал, дорога в стор (2.1) существовала, а
        писать в неё было некому — ``kind=stats`` в сторе стоял на нуле.

        **Раз в секунду, не на кадр.** Точка вызова — существующая ветка
        пересчёта fps, а не горячий путь ``produce``: при 30 к/с эмиссия на кадр
        стоила бы 30 вызовов в секунду там, где вся ценность в агрегате за окно
        (окно ``StatsManager`` всё равно свернёт их в одно число). Своего
        таймера задача не заводит — ветка уже есть и уже срабатывает по времени.

        Счётчик потерь отдаётся ПРИРОСТОМ: counter суммируется за окно, и сумма
        накопительного значения дала бы квадратичный рост «потерь за смену».
        """
        ctx = self._ctx
        if ctx is None:
            return
        tags = {"camera": str(self._camera_id)}
        ctx.record_metric("capture.frames", frames_in_window, tags)
        ctx.gauge("capture.fps", self._actual_fps, tags)
        drops_delta = self._drops - self._drops_reported
        if drops_delta:
            ctx.record_metric("capture.drops", drops_delta, tags)
            self._drops_reported = self._drops

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
            self._publish_levels()
        else:
            ctx.log_error(f"CapturePlugin[{self._camera_id}]: не удалось открыть камеру {self._device_id}")

    def _stop_capture(self, ctx: PluginContext) -> None:
        """Остановить захват и сбросить FPS-метрику."""
        self._is_capturing = False
        self._release_camera()
        ctx.log_info(f"CapturePlugin[{self._camera_id}]: захват остановлен")
        # Сбрасываем FPS и публикуем финальное состояние. Уровень отдаём здесь же,
        # не дожидаясь следующего такта метрик: такта больше не будет (``produce``
        # не зовут у остановленного захвата), и ``fps`` замер бы на последнем
        # живом значении — «камера остановлена, а частота идёт».
        self._actual_fps = 0.0
        self._publish_state()
        self._publish_levels()

    def _publish_state(self) -> None:
        """Опубликовать ФРОНТЫ захвата в StateStore (Task 3.5).

        Здесь остались только те ключи, которые меняются СОБЫТИЕМ, а не текут по
        тику: ``status`` (запущен/остановлен), ``paused`` и ``frozen``. Их и
        публикуем прямой записью в дерево — уровнем, обновляемым по тику, они не
        являются, и превращать их в уровень значило бы получить «уровень»,
        который между сменами состояния не обновляется.

        **Уровни ушли на дорогу фреймворка** (``ctx.publish_metric``, см.
        :meth:`_publish_levels`): ``fps``, ``frame_count``, ``drops``. Прямая
        запись уровней отсюда была ВТОРОЙ дорогой в тот же путь дерева — мимо
        publisher-гейта, мимо сборщика телеметрийного тика и мимо опроса. Живьём
        это выглядело так: гейт ``camera_0`` закрыт на ``fps`` (readback
        ``enabled=false``), чисто-тиковые ``latency_ms`` и ``shm`` дают ноль
        дельт за 41.1 с, а ``state.fps`` за то же окно получает 35 — потому что
        писал их сюда этот метод.
        """
        if self._state_proxy is None:
            return
        path = f"processes.{self._ctx.process_name}.state"
        self._state_proxy.merge(
            path,
            {
                "status": "running" if self._is_capturing else "stopped",
                "paused": self._paused,
                "frozen": self._frozen,
            },
        )

    def _publish_levels(self) -> None:
        """Отдать УРОВНИ захвата сборщику телеметрийного тика (Task 3.5).

        Дорога одна на все три числа: фреймворк собирает их на своём тике, гейтит
        наравне с ``fps``/``latency_ms`` и отдаёт опросом
        (``introspect.telemetry`` → ``levels``). Пути в дереве те же, что были
        (``processes.<процесс>.state.fps`` и соседи), — миграция меняет ДОРОГУ, а
        не показание.

        ``fps`` здесь НЕ объявляется: имя уже принадлежит фреймворку (агрегат
        ``max(effective_hz)`` по running-воркерам), и второе объявление на то же
        имя — законный отказ реестра. Публиковать в него можно: сборщик уровней
        накладывается ПОСЛЕ агрегата воркеров, поэтому измеренный камерой fps
        побеждает выведенный из частоты воркера — то же число, что оператор видел
        до миграции.
        """
        ctx = self._ctx
        if ctx is None:
            return
        ctx.publish_metric("fps", round(self._actual_fps, 1))
        ctx.publish_metric("frame_count", self._frame_count)
        ctx.publish_metric("drops", self._drops)

    def _release_camera(self) -> None:
        """Освободить камеру."""
        if self._cap is not None:
            self._cap.release()
            self._cap = None
