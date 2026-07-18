"""telemetry_view_model.py — Qt-обёртка read-model телеметрии для GUI.

Принцип «запись — всегда, чтение — локально, история — по запросу». Backend
публикует телеметрию постоянно (троттлинг на стороне источника) в дерево
StateStore; GUI держит ОДИН локальный read-model, наполняемый ОДНИМ
wildcard-потоком дельт. Виджеты читают только локально — без похода на сервер
за снимком.

Хранилище (снимок + история) и его тонкие инварианты (граница префикса,
приведение к числу, окно истории) вынесены в generic Qt-free ядро
:class:`~multiprocess_framework.modules.telemetry_readmodel_module.TelemetryReadModel`
(переиспользуется headless-драйвером диагностики backend_ctl). Здесь остаётся
GUI-специфика: разбор конверта ``state_delta``/``gui_local_metric`` и коалесинг
Qt-сигнала ``updated`` (один эмит на пачку дельт).

Инвариант (enforce тестом ``test_view_model_creates_no_server_subscriptions``):
    view-model НЕ создаёт серверных подписок и не делает блокирующий IPC. Он не
    держит ссылки ни на router, ни на state-proxy — питается исключительно
    входящими dict-сообщениями (``on_state_delta``). Стартовые wildcard'ы —
    единственный источник потока.

Что умеет:
    * on_state_delta(msg_dict)  — слот-потребитель ``msg_dict`` того же формата,
      что и общий state-fan-out (multi-subscriber). Пишет read-model синхронно,
      а Qt-сигнал ``updated`` эмитит ОДИН раз на пачку дельт (коалесинг через
      0-таймер), а не по каждой дельте.
    * get(path) / snapshot(prefix)  — чтение текущего снимка (делегат ядра).
      Late-binding: вкладка, созданная ПОСЛЕ публикации, читает актуальное сразу.
    * history(path, since)  — кольцевой буфер последних ~N минут (делегат ядра)
      для мгновенных спарклайнов без похода в БД истории.

Dict-at-Boundary: view-model ест dict-сообщение (не live SchemaBase) — граница
процессов соблюдена.
"""

from __future__ import annotations

import logging
from typing import Any

from PySide6.QtCore import QObject, QTimer, Signal

from multiprocess_framework.modules.telemetry_readmodel_module import (
    DEFAULT_TRACKED_SUFFIXES,
    TelemetryReadModel,
)

_logger = logging.getLogger(__name__)

# Sentinel «путь удалён» во внутреннем накопителе пачки. В публичный батч
# ``updated`` удаление выходит как (path, None) — потребитель перечитывает
# актуальное через get()/snapshot() (удалённый путь вернёт default).
_REMOVED: Any = object()


class TelemetryViewModel(QObject):
    """Владелец «снимок телеметрии → виджет»: read-model + батч-сигнал обновления.

    Один объект в GUI. Питается существующим wildcard-потоком дельт (второй
    потребитель рядом с общим state-fan-out). НЕ создаёт серверных подписок.
    Хранилище — generic :class:`TelemetryReadModel`; здесь только Qt-коалесинг.

    Сигналы:
        updated(list): список ``tuple[str, Any]`` — (path, value) путей,
            изменившихся за одну пачку дельт. Для удалённого пути value=None.
            Эмитится ОДИН раз на пачку (коалесинг), не по каждой дельте.

    Использование:
        vm = TelemetryViewModel(initial_cache=proxy.cache)  # опц. первичный снимок
        bridge.add_state_listener(vm.on_state_delta)         # второй потребитель
        vm.updated.connect(panel.on_telemetry_batch)         # батч-слот панели
        vm.snapshot("processes.cam")                          # late-binding чтение
        vm.history("processes.cam.state.fps", since=...)      # спарклайн
    """

    updated = Signal(list)  # list[tuple[str, Any]]

    def __init__(
        self,
        parent: QObject | None = None,
        *,
        initial_cache: dict[str, Any] | None = None,
        tracked_suffixes: tuple[str, ...] | None = None,
        window_sec: float = 600.0,
        sample_hz: float = 1.0,
    ) -> None:
        """Инициализировать read-model.

        Args:
            parent: Qt-родитель (владение жизненным циклом).
            initial_cache: опциональный первичный снимок ``{path: value}``
                (обычно кэш state-proxy). Заливается сразу — snapshot()
                работает ещё до первой дельты. None/пустой → стартуем пустыми.
            tracked_suffixes: набор суффиксов путей для кольцевых буферов
                истории. None → DEFAULT_TRACKED_SUFFIXES. Пустой кортеж →
                история не копится (только snapshot/get).
            window_sec: длительность окна истории в секундах (~10 мин = 600).
            sample_hz: ожидаемая частота семплов метрики (троттлинг источника).
                maxlen буфера = ceil(window_sec * sample_hz) ≈ 600 точек.
        """
        super().__init__(parent)

        # Хранилище снимка + истории (generic Qt-free ядро). Read-model пишется
        # синхронно в on_state_delta, читается get()/snapshot()/history().
        self._model = TelemetryReadModel(
            initial_cache=initial_cache,
            tracked_suffixes=tracked_suffixes,
            window_sec=window_sec,
            sample_hz=sample_hz,
        )

        # Накопитель пачки (path → value | _REMOVED). Дедуп по пути внутри
        # пачки (last-wins) — один и тот же путь не попадёт в батч дважды.
        self._pending: dict[str, Any] = {}

        # Коалесинг сигнала: 0-таймерный single-shot. Все дельты, доставленные
        # в одном обороте Qt event loop, схлопываются в один updated.
        self._flush_timer = QTimer(self)
        self._flush_timer.setSingleShot(True)
        self._flush_timer.setInterval(0)
        self._flush_timer.timeout.connect(self._flush)

    # ------------------------------------------------------------------
    # Приём дельт (второй потребитель wildcard-потока)
    # ------------------------------------------------------------------

    def on_state_delta(self, msg_dict: dict) -> None:
        """Слот-потребитель dict-сообщения из bridge (Qt main thread).

        Формат (тот же, что у общего state-fan-out):
            {'data_type': 'state_delta', 'path': 'processes.cam.state.fps',
             'value': 25.3, 'deleted': False}

        Принимаем также ``gui_local_metric`` — GUI-локальные метрики,
        измеряемые самим фронтендом и питающие те же path-модели.

        Пишет read-model СИНХРОННО (snapshot/get актуальны сразу), а Qt-сигнал
        ``updated`` планирует одним батчем на пачку (коалесинг). Прочие
        data_type и сообщения без path/value — игнорируются.
        """
        if msg_dict.get("data_type") not in ("state_delta", "gui_local_metric"):
            return
        path = msg_dict.get("path")
        # Пропускаем только при отсутствии path/value (пустой строкой путь в
        # проде не бывает).
        if path is None or "value" not in msg_dict:
            return

        if bool(msg_dict.get("deleted")):
            # Удаление узла: убрать из read-model. value в envelope — None-
            # заглушка, в батч кладём маркер удаления.
            self._model.ingest(path, None, deleted=True)
            self._pending[path] = _REMOVED
        else:
            value = msg_dict["value"]
            self._model.ingest(path, value)
            self._pending[path] = value

        # Взвести коалесинг-таймер, если ещё не взведён.
        if not self._flush_timer.isActive():
            self._flush_timer.start()

    def _flush(self) -> None:
        """Эмит одного батча за пачку дельт и сброс накопителя."""
        if not self._pending:
            return
        pending = self._pending
        self._pending = {}
        batch: list[tuple[str, Any]] = [(path, None if value is _REMOVED else value) for path, value in pending.items()]
        self.updated.emit(batch)

    # ------------------------------------------------------------------
    # Чтение снимка (делегат ядра — late-binding)
    # ------------------------------------------------------------------

    def get(self, path: str, default: Any = None) -> Any:
        """Текущее значение по пути (или default, если пути нет)."""
        return self._model.get(path, default)

    def snapshot(self, prefix: str) -> dict[str, Any]:
        """Снимок поддерева: все пути == prefix или начинающиеся с ``prefix.``.

        Границей служит точка-разделитель — ``snapshot("processes.cam")`` берёт
        поддерево процесса ``cam`` и НЕ захватывает ``processes.cam2.*``. Пустой
        prefix → полный снимок read-model.
        """
        return self._model.snapshot(prefix)

    def history(self, path: str, since: float | None = None) -> list[tuple[float, Any]]:
        """Выборка (ts, value) кольцевого буфера для спарклайна.

        Args:
            path: полный путь метрики (например ``processes.cam.state.fps``).
            since: нижняя граница ts (wall-clock, Unix-epoch); None → весь буфер.

        Returns:
            Список ``(ts, value)`` в хронологическом порядке. Нет буфера → [].
        """
        return self._model.history(path, since)


__all__ = ["TelemetryViewModel", "DEFAULT_TRACKED_SUFFIXES"]
