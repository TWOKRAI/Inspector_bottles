"""FrameThrottleMiddleware — троттлинг кадров для display-каналов."""

from __future__ import annotations

import threading
import time


class FrameThrottleMiddleware:
    """Middleware для ограничения FPS на display-каналах.

    Подключается к RouterManager как send-middleware:
        router_manager.add_send_middleware(throttle_mw.on_send)

    Логика: on_send дропает кадры, превышающие fps_limit для канала,
    путём проверки временного интервала между пропущенными кадрами.
    """

    def __init__(self, channel_fps_limits: dict[str, int] | None = None) -> None:
        """Инициализация middleware.

        Args:
            channel_fps_limits: Маппинг channel → max FPS.
                Пример: {"display_win_0": 15, "display_win_1": 30}.
                None означает отсутствие ограничений (все кадры проходят).
        """
        # Маппинг channel → максимальный FPS
        self._limits: dict[str, int] = dict(channel_fps_limits) if channel_fps_limits else {}
        # Маппинг channel → timestamp последнего пропущенного кадра
        self._last_pass: dict[str, float] = {}
        # Лок для потокобезопасного доступа к _limits и _last_pass
        self._lock = threading.Lock()

    def on_send(self, msg: dict) -> dict | None:
        """Обработчик отправки сообщения — дропает лишние кадры.

        Args:
            msg: Словарь сообщения с полем "channel".

        Returns:
            msg — если кадр пропускается через лимит.
            None — если кадр дропается (лимит не исчерпан или block all).
        """
        channel = msg.get("channel", "")

        with self._lock:
            # Канал без лимита — пропустить без ограничений
            if channel not in self._limits:
                return msg

            fps_limit = self._limits[channel]

            # fps_limit <= 0: нулевой — блокировать все кадры; отрицательный — пропускать все
            if fps_limit == 0:
                return None
            if fps_limit < 0:
                return msg

            min_interval = 1.0 / fps_limit
            now = time.monotonic()

            # Первый кадр для канала — всегда пропускаем
            if channel not in self._last_pass:
                self._last_pass[channel] = now
                return msg

            # Проверяем, прошёл ли минимальный интервал с последнего пропущенного кадра
            if now - self._last_pass[channel] < min_interval:
                return None  # дроп

            # Интервал истёк — обновляем метку и пропускаем кадр
            self._last_pass[channel] = now
            return msg

    def set_fps_limit(self, channel: str, fps: int) -> None:
        """Установить или обновить лимит FPS для канала в runtime.

        Args:
            channel: Имя канала (например, "display_win_0").
            fps: Максимальный FPS. 0 — блокировать все кадры.
                Отрицательное — пропускать все кадры без ограничений.
        """
        with self._lock:
            self._limits[channel] = fps

    def remove_fps_limit(self, channel: str) -> None:
        """Удалить лимит FPS для канала — все кадры будут проходить.

        Args:
            channel: Имя канала для удаления лимита.
        """
        with self._lock:
            self._limits.pop(channel, None)
            self._last_pass.pop(channel, None)

    def clear(self) -> None:
        """Очистить все лимиты и временные метки."""
        with self._lock:
            self._limits.clear()
            self._last_pass.clear()
