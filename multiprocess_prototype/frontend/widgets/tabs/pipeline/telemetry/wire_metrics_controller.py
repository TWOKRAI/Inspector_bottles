"""Контроллер телеметрии wire-соединений pipeline.

Связывает WireMetricsModel (данные) с WireMetricsBadge (визуализация),
реагирует на добавление/удаление edges в GraphScene и обновляет UI
через два независимых QTimer:
  - статусный таймер (2с): цвет badge по WireStatus
  - метрический таймер (1с): текст badge по WireMetrics

Сигналы статусов и метрик испускаются только через таймеры,
что позволяет точно управлять частотой обновления UI.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, QPointF, QTimer

from .wire_metrics_badge import WireMetricsBadge
from .wire_metrics_model import WireMetricsModel

# ---------------------------------------------------------------------------
# Константы интервалов таймеров
# ---------------------------------------------------------------------------

STATUS_TIMER_INTERVAL_MS: int = 2000
"""Интервал обновления статуса (цвет) — 2 секунды (медленный тик)."""

METRICS_TIMER_INTERVAL_MS: int = 1000
"""Интервал обновления метрик (текст) — 1 секунда (быстрый тик)."""


class WireMetricsController(QObject):
    """Контроллер телеметрии edges pipeline-графа.

    Подписывается на GraphScene.edge_added / edge_removed для автоматического
    создания и удаления WireMetricsBadge. Два независимых QTimer управляют
    частотой обновления UI (статус — 2с, метрики — 1с).

    Жизненный цикл badge:
      edge_added → создать badge → добавить в scene → сохранить в _badges
      edge_removed → убрать badge из scene → убрать из _badges → очистить модель

    Управление таймерами: вызвать start() для запуска, stop() для остановки.
    Таймеры НЕ запускаются автоматически в __init__ — это упрощает тестирование.

    Args:
        scene: GraphScene с сигналами edge_added/edge_removed.
        model: WireMetricsModel — источник статусов и метрик.
        parent: Родительский QObject (опционально).
    """

    def __init__(
        self,
        scene: "GraphScene",  # type: ignore[name-defined]  # noqa: F821
        model: WireMetricsModel,
        parent: QObject | None = None,
    ) -> None:
        """Инициализировать контроллер.

        Args:
            scene: Сцена pipeline-графа с поддержкой сигналов edge_added/edge_removed.
            model: Модель данных телеметрии.
            parent: Родительский QObject (опционально).
        """
        super().__init__(parent)

        self._scene = scene
        self._model = model

        # Словарь активных badge'ей: (source_id, target_id) → WireMetricsBadge
        self._badges: dict[tuple[str, str], WireMetricsBadge] = {}

        # Подписка на сигналы GraphScene
        scene.edge_added.connect(self._on_edge_added)
        scene.edge_removed.connect(self._on_edge_removed)

        # Подписка на сигналы WireMetricsModel
        model.statuses_changed.connect(self._apply_statuses)
        model.metrics_changed.connect(self._apply_metrics)

        # Таймер статусов (медленный, 2с)
        self._status_timer = QTimer(self)
        self._status_timer.setInterval(STATUS_TIMER_INTERVAL_MS)
        self._status_timer.timeout.connect(self._tick_status)

        # Таймер метрик (быстрый, 1с)
        self._metrics_timer = QTimer(self)
        self._metrics_timer.setInterval(METRICS_TIMER_INTERVAL_MS)
        self._metrics_timer.timeout.connect(self._tick_metrics)

    # ------------------------------------------------------------------
    # Управление таймерами
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Запустить оба таймера (статус + метрики).

        Вызывается после создания контроллера в PipelineTab.
        """
        self._status_timer.start()
        self._metrics_timer.start()

    def stop(self) -> None:
        """Остановить оба таймера.

        Вызывается при закрытии вкладки или деактивации телеметрии.
        """
        self._status_timer.stop()
        self._metrics_timer.stop()

    # ------------------------------------------------------------------
    # Вспомогательные методы
    # ------------------------------------------------------------------

    def _wire_key(self, edge: "EdgeItem") -> tuple[str, str]:  # type: ignore[name-defined]  # noqa: F821
        """Вычислить ключ для badge-словаря по данным edge.

        Args:
            edge: EdgeItem из GraphScene.

        Returns:
            Кортеж (source_id, target_id) — уникальный ключ wire.
        """
        return (edge.source_id, edge.target_id)

    def _compute_midpoint(self, edge: "EdgeItem") -> QPointF:  # type: ignore[name-defined]  # noqa: F821
        """Вычислить середину кривой Bezier для позиционирования badge.

        Использует QPainterPath.pointAtPercent(0.5) для точки середины кривой.
        Если path пустой — возвращает начало координат.

        Args:
            edge: EdgeItem с обновлённым Bezier-путём.

        Returns:
            QPointF — координаты середины кривой в системе сцены.
        """
        path = edge.path()
        if path is None or path.isEmpty():
            return QPointF(0.0, 0.0)
        return path.pointAtPercent(0.5)

    # ------------------------------------------------------------------
    # Обработчики сигналов GraphScene
    # ------------------------------------------------------------------

    def _on_edge_added(self, edge: "EdgeItem") -> None:  # type: ignore[name-defined]  # noqa: F821
        """Создать badge для нового edge.

        Идемпотентен: повторный вызов для того же edge игнорируется.

        Args:
            edge: Новый EdgeItem, добавленный в сцену.
        """
        key = self._wire_key(edge)

        # Идемпотентность: не создавать дубликаты
        if key in self._badges:
            return

        # Создать badge и добавить в сцену
        badge = WireMetricsBadge()
        self._scene.addItem(badge)

        # Позиционировать по midpoint кривой
        midpoint = self._compute_midpoint(edge)
        badge.update_position(midpoint)

        # Сохранить ссылку
        self._badges[key] = badge

    def _on_edge_removed(self, edge: "EdgeItem") -> None:  # type: ignore[name-defined]  # noqa: F821
        """Удалить badge при удалении edge.

        Также очищает данные телеметрии в модели для этого wire.

        Args:
            edge: Удаляемый EdgeItem (ещё до removeItem).
        """
        key = self._wire_key(edge)
        badge = self._badges.pop(key, None)

        if badge is not None:
            self._scene.removeItem(badge)

        # Очистить данные в модели (статусы + метрики)
        self._model.remove_wire(*key)

    # ------------------------------------------------------------------
    # Тики таймеров
    # ------------------------------------------------------------------

    def _tick_status(self) -> None:
        """Медленный тик (2с): испустить статусы и обновить позиции badge.

        Позиции обновляются на медленном тике, так как узлы двигаются редко.
        """
        self._model.emit_statuses()
        self._update_badge_positions()

    def _tick_metrics(self) -> None:
        """Быстрый тик (1с): испустить метрики производительности."""
        self._model.emit_metrics()

    # ------------------------------------------------------------------
    # Обработчики сигналов WireMetricsModel
    # ------------------------------------------------------------------

    def _apply_statuses(self, statuses: dict) -> None:
        """Обновить цвет всех badge'ей по словарю статусов.

        Вызывается при сигнале model.statuses_changed.

        Args:
            statuses: {(src, tgt): WireStatus} — snapshot из модели.
        """
        for key, status in statuses.items():
            if key in self._badges:
                self._badges[key].update_status(status)

    def _apply_metrics(self, metrics: dict) -> None:
        """Обновить текст всех badge'ей по словарю метрик.

        Вызывается при сигнале model.metrics_changed.

        Args:
            metrics: {(src, tgt): WireMetrics} — snapshot из модели.
        """
        for key, metric in metrics.items():
            if key in self._badges:
                self._badges[key].update_metrics(metric)

    # ------------------------------------------------------------------
    # Обновление позиций
    # ------------------------------------------------------------------

    def _update_badge_positions(self) -> None:
        """Пересчитать позиции всех badge'ей по текущим путям edges.

        Вызывается на медленном тике (~2с) для компенсации перемещения узлов.
        Обращается к self._scene._edges напрямую — допустимо в рамках одного слоя.
        """
        for edge in self._scene._edges:
            key = self._wire_key(edge)
            if key in self._badges:
                self._badges[key].update_position(self._compute_midpoint(edge))

    # ------------------------------------------------------------------
    # Properties для тестирования
    # ------------------------------------------------------------------

    @property
    def badges(self) -> dict[tuple[str, str], WireMetricsBadge]:
        """Словарь активных badge'ей (read-only, для тестов).

        Returns:
            {(source_id, target_id): WireMetricsBadge}
        """
        return self._badges

    # ------------------------------------------------------------------
    # Публичный proxy для внешнего feed-а
    # ------------------------------------------------------------------

    def set_metrics(
        self,
        src: str,
        tgt: str,
        fps: float,
        latency_ms: float,
        buffer_fill: float,
    ) -> None:
        """Публичный proxy для обновления метрик через внешний feed.

        Оборачивает model.update_metrics — для будущего подключения
        реального источника данных (Phase 8).

        Args:
            src: Идентификатор исходного узла.
            tgt: Идентификатор целевого узла.
            fps: Частота передачи (кадров/сек).
            latency_ms: Задержка (миллисекунды).
            buffer_fill: Заполненность буфера (0.0–1.0).
        """
        self._model.update_metrics(src, tgt, fps, latency_ms, buffer_fill)

    def set_status(
        self,
        src: str,
        tgt: str,
        state: str,
        last_message_time: float = 0.0,
    ) -> None:
        """Публичный proxy для обновления статуса через внешний feed.

        Args:
            src: Идентификатор исходного узла.
            tgt: Идентификатор целевого узла.
            state: Состояние ("ok", "idle", "error").
            last_message_time: Unix timestamp последнего сообщения.
        """
        self._model.update_status(src, tgt, state, last_message_time)
