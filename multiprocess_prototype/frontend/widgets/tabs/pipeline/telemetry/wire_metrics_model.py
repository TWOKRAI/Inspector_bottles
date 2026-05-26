"""Модель данных телеметрии wire-соединений pipeline.

Предоставляет два независимых потока данных:
- WireStatus  — медленный (~2с): состояние соединения (ok/idle/error)
- WireMetrics — быстрый (~1с): производительность (fps, latency, buffer_fill)

Сигналы испускаются только при явном вызове emit_statuses() / emit_metrics(),
что позволяет управлять частотой обновления UI извне через таймеры.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Literal

from PySide6.QtCore import QObject, Signal


@dataclass
class WireStatus:
    """Статусная информация о wire-соединении.

    Обновляется с низкой частотой (~2с).
    Используется для цветовой индикации состояния соединения.
    """

    state: Literal["ok", "idle", "error"] = "idle"
    """Состояние соединения: ok — активно, idle — неактивно, error — ошибка."""

    last_message_time: float = 0.0
    """Время последнего сообщения (Unix timestamp, секунды)."""


@dataclass
class WireMetrics:
    """Метрики производительности wire-соединения.

    Обновляется с высокой частотой (~1с).
    Используется для отображения fps/latency/buffer_fill в badge.
    """

    fps: float = 0.0
    """Частота передачи сообщений (кадров/сек)."""

    latency_ms: float = 0.0
    """Задержка передачи (миллисекунды)."""

    buffer_fill: float = 0.0
    """Заполненность буфера (0.0–1.0)."""


class WireMetricsModel(QObject):
    """Модель данных телеметрии для всех wire-соединений pipeline.

    Хранит состояния и метрики по ключу (src, tgt) — паре идентификаторов
    исходного и целевого узлов соединения.

    Сигналы испускаются ТОЛЬКО при явных вызовах emit_statuses() / emit_metrics().
    Это разделяет логику накопления данных и логику обновления UI,
    позволяя управлять частотой обновления через внешние таймеры (Task 7b.3).

    Signals:
        statuses_changed(dict): испускается с {(src, tgt): WireStatus}.
        metrics_changed(dict): испускается с {(src, tgt): WireMetrics}.
    """

    statuses_changed = Signal(object)
    """Сигнал обновления статусов. Передаёт deepcopy текущего словаря статусов.

    Использует Signal(object) вместо Signal(dict), так как PySide6 не поддерживает
    автоматическую конвертацию dict с tuple-ключами через Shiboken C++ мост.
    """

    metrics_changed = Signal(object)
    """Сигнал обновления метрик. Передаёт deepcopy текущего словаря метрик.

    Использует Signal(object) — аналогичная причина: tuple-ключи не проходят C++ конвертацию.
    """

    def __init__(self, parent: QObject | None = None) -> None:
        """Инициализировать модель.

        Args:
            parent: Родительский QObject (опционально).
        """
        super().__init__(parent)
        self._statuses: dict[tuple[str, str], WireStatus] = {}
        self._metrics: dict[tuple[str, str], WireMetrics] = {}

    # ------------------------------------------------------------------
    # Методы обновления (НЕ испускают сигналы)
    # ------------------------------------------------------------------

    def update_status(
        self,
        src: str,
        tgt: str,
        state: str,
        last_message_time: float = 0.0,
    ) -> None:
        """Обновить или создать запись о статусе wire-соединения.

        Сигнал НЕ испускается — используй emit_statuses() явно.

        Args:
            src: Идентификатор исходного узла.
            tgt: Идентификатор целевого узла.
            state: Состояние соединения ("ok", "idle" или "error").
            last_message_time: Время последнего сообщения (Unix timestamp).
        """
        self._statuses[(src, tgt)] = WireStatus(
            state=state,  # type: ignore[arg-type]
            last_message_time=last_message_time,
        )

    def update_metrics(
        self,
        src: str,
        tgt: str,
        fps: float,
        latency_ms: float,
        buffer_fill: float,
    ) -> None:
        """Обновить или создать запись о метриках wire-соединения.

        Сигнал НЕ испускается — используй emit_metrics() явно.

        Args:
            src: Идентификатор исходного узла.
            tgt: Идентификатор целевого узла.
            fps: Частота передачи (кадров/сек).
            latency_ms: Задержка (миллисекунды).
            buffer_fill: Заполненность буфера (0.0–1.0).
        """
        self._metrics[(src, tgt)] = WireMetrics(
            fps=fps,
            latency_ms=latency_ms,
            buffer_fill=buffer_fill,
        )

    # ------------------------------------------------------------------
    # Методы чтения
    # ------------------------------------------------------------------

    def get_status(self, src: str, tgt: str) -> WireStatus | None:
        """Получить статус wire-соединения.

        Args:
            src: Идентификатор исходного узла.
            tgt: Идентификатор целевого узла.

        Returns:
            WireStatus или None, если запись отсутствует.
        """
        return self._statuses.get((src, tgt))

    def get_metrics(self, src: str, tgt: str) -> WireMetrics | None:
        """Получить метрики wire-соединения.

        Args:
            src: Идентификатор исходного узла.
            tgt: Идентификатор целевого узла.

        Returns:
            WireMetrics или None, если запись отсутствует.
        """
        return self._metrics.get((src, tgt))

    # ------------------------------------------------------------------
    # Методы испускания сигналов
    # ------------------------------------------------------------------

    def emit_statuses(self) -> None:
        """Испустить сигнал statuses_changed с deepcopy текущих статусов.

        Вызывается внешним таймером (~2с) для обновления цветов badges.
        """
        self.statuses_changed.emit(deepcopy(self._statuses))

    def emit_metrics(self) -> None:
        """Испустить сигнал metrics_changed с deepcopy текущих метрик.

        Вызывается внешним таймером (~1с) для обновления текста badges.
        """
        self.metrics_changed.emit(deepcopy(self._metrics))

    # ------------------------------------------------------------------
    # Управление жизненным циклом данных
    # ------------------------------------------------------------------

    def clear(self) -> None:
        """Очистить все данные о статусах и метриках.

        Используется при сбросе pipeline или загрузке нового рецепта.
        """
        self._statuses.clear()
        self._metrics.clear()

    def remove_wire(self, src: str, tgt: str) -> None:
        """Удалить данные для конкретного wire-соединения из обоих словарей.

        Вызывается при удалении edge из графа pipeline.

        Args:
            src: Идентификатор исходного узла.
            tgt: Идентификатор целевого узла.
        """
        key = (src, tgt)
        self._statuses.pop(key, None)
        self._metrics.pop(key, None)
