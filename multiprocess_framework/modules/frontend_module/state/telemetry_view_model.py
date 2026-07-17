"""telemetry_view_model.py — generic GUI read-model телеметрии.

Принцип «запись — всегда, чтение — локально, история — по запросу». Backend
публикует телеметрию постоянно (троттлинг на стороне источника) в дерево
StateStore; GUI держит ОДИН локальный read-model, наполняемый ОДНИМ
wildcard-потоком дельт. Виджеты читают только локально — без похода на сервер
за снимком.

Модуль generic: он не знает ни имён процессов, ни конкретного набора метрик
приложения. Набор путей, для которых копится история (``tracked_suffixes``),
и параметры окна — аргументы конструктора. Дефолт ``DEFAULT_TRACKED_SUFFIXES``
покрывает штатные gated-метрики фреймворка (см. ``process_module`` —
``GATED_METRICS`` и форму дерева ``build_worker_telemetry``); приложение с
дополнительными метриками передаёт собственный набор суффиксов.

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
    * get(path) / snapshot(prefix)  — чтение текущего снимка. Late-binding:
      вкладка, созданная ПОСЛЕ публикации, читает актуальное сразу.
    * history(path, since)  — кольцевой буфер последних ~N минут по ключевым
      метрикам для мгновенных спарклайнов без похода в БД истории. Fixed-size
      deque, append O(1), выборка диапазона O(k).

Dict-at-Boundary: view-model ест dict-сообщение (не live SchemaBase) — граница
процессов соблюдена.
"""

from __future__ import annotations

import collections
import logging
import time
from typing import Any

from PySide6.QtCore import QObject, QTimer, Signal

_logger = logging.getLogger(__name__)


# Суффиксы путей телеметрии, для которых копится кольцевой буфер истории.
# Соответствуют штатным gated-метрикам фреймворка (``GATED_METRICS`` в
# ``process_module``) и форме телеметрийного поддерева (``build_worker_telemetry``):
# агрегат публикуется как ``processes.<P>.state.fps`` → суффикс ``.state.fps``,
# per-worker — как ``processes.<P>.workers.<w>.effective_hz`` → суффикс
# ``.effective_hz``. Совпадение по СУФФИКСУ пути (независимо от имени
# процесса/воркера). Приложение с дополнительными метриками передаёт свой набор
# через ``tracked_suffixes``.
DEFAULT_TRACKED_SUFFIXES: tuple[str, ...] = (
    ".state.fps",
    ".state.latency_ms",
    ".state.uptime",
    ".effective_hz",
    ".cycle_duration_ms",
)

# Sentinel «путь удалён» во внутреннем накопителе пачки. В публичный батч
# ``updated`` удаление выходит как (path, None) — потребитель перечитывает
# актуальное через get()/snapshot() (удалённый путь вернёт default).
_REMOVED: Any = object()


class TelemetryViewModel(QObject):
    """Владелец «снимок телеметрии → виджет»: read-model + батч-сигнал обновления.

    Один объект в GUI. Питается существующим wildcard-потоком дельт (второй
    потребитель рядом с общим state-fan-out). НЕ создаёт серверных подписок.

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

        # Read-model: путь → последнее значение. Пишется синхронно в
        # on_state_delta, читается get()/snapshot() (late-binding).
        self._state: dict[str, Any] = {}

        # Накопитель пачки (path → value | _REMOVED). Дедуп по пути внутри
        # пачки (last-wins) — один и тот же путь не попадёт в батч дважды.
        self._pending: dict[str, Any] = {}

        # Кольцевые буферы истории: путь → deque[(ts_wall, число)].
        self._history: dict[str, collections.deque[tuple[float, float]]] = {}
        self._tracked: tuple[str, ...] = (
            tuple(tracked_suffixes) if tracked_suffixes is not None else DEFAULT_TRACKED_SUFFIXES
        )
        # maxlen из окна и ожидаемого троттлинга: 600 с × 1 Гц = 600 точек.
        self._maxlen: int = max(1, int(round(window_sec * sample_hz)))

        # Коалесинг сигнала: 0-таймерный single-shot. Все дельты, доставленные
        # в одном обороте Qt event loop, схлопываются в один updated.
        self._flush_timer = QTimer(self)
        self._flush_timer.setSingleShot(True)
        self._flush_timer.setInterval(0)
        self._flush_timer.timeout.connect(self._flush)

        if initial_cache:
            self._prime(initial_cache)

    # ------------------------------------------------------------------
    # Первичное наполнение
    # ------------------------------------------------------------------

    def _prime(self, cache: dict[str, Any]) -> None:
        """Залить первичный снимок кэша (без эмита updated — это не «дельты»)."""
        for path, value in cache.items():
            if not isinstance(path, str):
                continue
            self._state[path] = value
            self._record_history(path, value)

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
            self._state.pop(path, None)
            self._pending[path] = _REMOVED
        else:
            value = msg_dict["value"]
            self._state[path] = value
            self._pending[path] = value
            # История — по каждой дельте (все точки важны для графика),
            # независимо от коалесинга сигнала.
            self._record_history(path, value)

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
    # Чтение снимка (late-binding — снимает нужду в cache-replay биндингов)
    # ------------------------------------------------------------------

    def get(self, path: str, default: Any = None) -> Any:
        """Текущее значение по пути (или default, если пути нет)."""
        return self._state.get(path, default)

    def snapshot(self, prefix: str) -> dict[str, Any]:
        """Снимок поддерева: все пути == prefix или начинающиеся с ``prefix.``.

        Границей служит точка-разделитель — ``snapshot("processes.cam")`` берёт
        поддерево процесса ``cam`` и НЕ захватывает ``processes.cam2.*`` (иначе
        соседний процесс с общим строковым префиксом протёк бы в снимок).
        Пустой prefix → полный снимок read-model.
        """
        if not prefix:
            return dict(self._state)
        dotted = prefix + "."
        return {p: v for p, v in self._state.items() if p == prefix or p.startswith(dotted)}

    # ------------------------------------------------------------------
    # Кольцевые буферы истории
    # ------------------------------------------------------------------

    def _is_tracked(self, path: str) -> bool:
        """Отслеживается ли путь для истории (совпадение по суффиксу)."""
        return any(path.endswith(suffix) for suffix in self._tracked)

    @staticmethod
    def _as_number(value: Any) -> float | None:
        """Привести к float; не-число (в т.ч. bool/str/None) → None."""
        if isinstance(value, bool):
            return None
        if isinstance(value, (int, float)):
            return float(value)
        return None

    def _record_history(self, path: str, value: Any) -> None:
        """Добавить числовую точку в кольцевой буфер отслеживаемого пути (O(1))."""
        if not self._is_tracked(path):
            return
        num = self._as_number(value)
        if num is None:
            return
        buf = self._history.get(path)
        if buf is None:
            buf = collections.deque(maxlen=self._maxlen)
            self._history[path] = buf
        # ts приёма: wall-clock (Unix-epoch, time.time()) — единая ось времени с
        # DB-историей и с DateAxisItem графика. Ring — только для отображения
        # (спарклайн/дашборд), длительности/Hz по нему не считаются, поэтому
        # monotonic здесь не нужен.
        buf.append((time.time(), num))

    def history(self, path: str, since: float | None = None) -> list[tuple[float, Any]]:
        """Выборка (ts, value) буфера для спарклайна.

        Args:
            path: полный путь метрики (например ``processes.cam.state.fps``).
            since: нижняя граница ts (wall-clock, Unix-epoch); None → весь буфер.

        Returns:
            Список ``(ts, value)`` в хронологическом порядке (O(k) по буферу).
            Нет буфера → пустой список.
        """
        buf = self._history.get(path)
        if buf is None:
            return []
        if since is None:
            return list(buf)
        return [(ts, val) for ts, val in buf if ts >= since]


__all__ = ["TelemetryViewModel", "DEFAULT_TRACKED_SUFFIXES"]
