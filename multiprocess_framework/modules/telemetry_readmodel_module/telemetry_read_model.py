"""telemetry_read_model.py — generic Qt-free ядро read-model телеметрии.

Принцип «запись — всегда, чтение — локально, история — по запросу». Backend
публикует телеметрию постоянно (троттлинг на стороне источника) в дерево
StateStore; потребитель держит ОДИН локальный read-model, наполняемый ОДНИМ
потоком дельт, и читает снимок/историю локально — без похода на сервер.

Ядро — чистое хранилище проекции состояния плюс кольцевые буферы истории. Оно
**не знает транспорта**: :meth:`ingest` принимает уже разобранную дельту
``(path, value, deleted)``. Обёртки над конкретным конвертом парсят своё
сообщение и вызывают ingest():

    * GUI (:class:`TelemetryViewModel`, Qt) — конверт ``state_delta`` +
      коалесинг сигнала обновления;
    * headless-драйвер диагностики (backend_ctl) — push ``state.changed`` из
      сокета.

Модуль generic: он не знает ни имён процессов, ни конкретного набора метрик
приложения. Набор путей, для которых копится история (``tracked_suffixes``), и
параметры окна — аргументы конструктора. Дефолт ``DEFAULT_TRACKED_SUFFIXES``
покрывает штатные gated-метрики фреймворка (см. ``process_module`` —
``GATED_METRICS`` и форму дерева ``build_worker_telemetry``); приложение с
дополнительными метриками передаёт собственный набор суффиксов.

Инвариант: read-model НЕ создаёт серверных подписок и не делает блокирующий IPC.
Он не держит ссылки ни на router, ни на state-proxy — питается исключительно
входящими дельтами через :meth:`ingest`.

Dict-at-Boundary: ядро оперирует уже разобранными значениями (не live
SchemaBase) — граница процессов соблюдена на стороне обёртки.
"""

from __future__ import annotations

import collections
import time
from typing import Any

# Суффиксы путей телеметрии, для которых копится кольцевой буфер ИСТОРИИ (спарклайны).
# Это НАБОР ИСТОРИИ read-модели, а НЕ зеркало publish-gate (``GATED_METRICS`` в
# ``process_module``): пересекается с ним, но намеренно отличается — ``.state.uptime``
# трекается для истории карточки процесса (в gate его нет, публикуется всегда), а
# транспортный счётчик ``shm`` в gate есть, но своей спарклайн-серии не имеет.
# Форма суффикса — по телеметрийному поддереву (``build_worker_telemetry``): агрегат
# ``processes.<P>.state.fps`` → ``.state.fps``, per-worker ``…workers.<w>.effective_hz``
# → ``.effective_hz`` (матч по СУФФИКСУ, независимо от имени процесса/воркера).
# Потребитель задаёт свой набор истории через ``tracked_suffixes``.
DEFAULT_TRACKED_SUFFIXES: tuple[str, ...] = (
    ".state.fps",
    ".state.latency_ms",
    ".state.uptime",
    ".effective_hz",
    ".cycle_duration_ms",
)


class TelemetryReadModel:
    """Read-model телеметрии: снимок ``path → value`` + кольцевые буферы истории.

    Питается потоком уже разобранных дельт (:meth:`ingest`). НЕ создаёт серверных
    подписок и не держит транспорт. Late-binding: читатель, обратившийся ПОСЛЕ
    публикации, видит актуальный снимок сразу.

    Что умеет:
        * ingest(path, value, deleted)  — внести одну разобранную дельту.
        * get(path) / snapshot(prefix)  — чтение текущего снимка.
        * history(path, since)          — кольцевой буфер последних ~N минут по
          ключевым метрикам для мгновенных спарклайнов без похода в БД.
    """

    def __init__(
        self,
        *,
        initial_cache: dict[str, Any] | None = None,
        tracked_suffixes: tuple[str, ...] | None = None,
        window_sec: float = 600.0,
        sample_hz: float = 1.0,
    ) -> None:
        """Инициализировать read-model.

        Args:
            initial_cache: опциональный первичный снимок ``{path: value}``
                (обычно кэш state-proxy). Заливается сразу — snapshot() работает
                ещё до первой дельты. None/пустой → стартуем пустыми.
            tracked_suffixes: набор суффиксов путей для кольцевых буферов истории.
                None → DEFAULT_TRACKED_SUFFIXES. Пустой кортеж → история не
                копится (только snapshot/get).
            window_sec: длительность окна истории в секундах (~10 мин = 600).
            sample_hz: ожидаемая частота семплов метрики (троттлинг источника).
                maxlen буфера = ceil(window_sec * sample_hz) ≈ 600 точек.
        """
        # Проекция состояния: путь → последнее значение. Пишется в ingest,
        # читается get()/snapshot() (late-binding).
        self._state: dict[str, Any] = {}

        # Кольцевые буферы истории: путь → deque[(ts_wall, число)].
        self._history: dict[str, collections.deque[tuple[float, float]]] = {}
        self._tracked: tuple[str, ...] = (
            tuple(tracked_suffixes) if tracked_suffixes is not None else DEFAULT_TRACKED_SUFFIXES
        )
        # maxlen из окна и ожидаемого троттлинга: 600 с × 1 Гц = 600 точек.
        self._maxlen: int = max(1, int(round(window_sec * sample_hz)))

        if initial_cache:
            self.prime(initial_cache)

    # ------------------------------------------------------------------
    # Первичное наполнение
    # ------------------------------------------------------------------

    def prime(self, cache: dict[str, Any]) -> None:
        """Залить первичный снимок кэша (нечисловые пути игнорируют историю)."""
        for path, value in cache.items():
            if not isinstance(path, str):
                continue
            self._state[path] = value
            self._record_history(path, value)

    # ------------------------------------------------------------------
    # Приём дельт (envelope-agnostic)
    # ------------------------------------------------------------------

    def ingest(self, path: str, value: Any, *, deleted: bool = False) -> None:
        """Внести одну уже разобранную дельту в снимок (+историю числовых точек).

        Args:
            path: полный путь узла (``processes.cam.state.fps``).
            value: новое значение (для ``deleted=True`` игнорируется).
            deleted: True → узел удалён, убрать из снимка (в историю не пишем).

        Пишет СИНХРОННО: snapshot/get/history актуальны сразу после вызова.
        """
        if deleted:
            # tree_store.delete() шлёт ОДНУ дельту на корень поддерева, поэтому
            # чистим и сам путь, и всё поддерево под ним. Граница — точка-разделитель
            # (как в snapshot): удаление ``processes.cam`` не заденет ``processes.cam2``.
            self._purge_subtree(path)
            return
        self._state[path] = value
        # История — по каждой дельте (все точки важны для графика).
        self._record_history(path, value)

    def _purge_subtree(self, path: str) -> None:
        """Убрать путь и всё поддерево под ним из снимка и истории.

        Граница — точка-разделитель: удаляются ``path`` и ключи с префиксом
        ``path + "."`` (сосед с общим строковым префиксом не затрагивается).
        """
        dotted = path + "."
        for store in (self._state, self._history):
            stale = [p for p in store if p == path or p.startswith(dotted)]
            for p in stale:
                del store[p]

    # ------------------------------------------------------------------
    # Чтение снимка (late-binding)
    # ------------------------------------------------------------------

    def get(self, path: str, default: Any = None) -> Any:
        """Текущее значение по пути (или default, если пути нет)."""
        return self._state.get(path, default)

    def snapshot(self, prefix: str) -> dict[str, Any]:
        """Снимок поддерева: все пути == prefix или начинающиеся с ``prefix.``.

        Границей служит точка-разделитель — ``snapshot("processes.cam")`` берёт
        поддерево процесса ``cam`` и НЕ захватывает ``processes.cam2.*`` (иначе
        соседний процесс с общим строковым префиксом протёк бы в снимок). Пустой
        prefix → полный снимок read-model.
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
            Список ``(ts, value)`` в хронологическом порядке (O(k) по буферу). Нет
            буфера → пустой список.
        """
        buf = self._history.get(path)
        if buf is None:
            return []
        if since is None:
            return list(buf)
        return [(ts, val) for ts, val in buf if ts >= since]


__all__ = ["TelemetryReadModel", "DEFAULT_TRACKED_SUFFIXES"]
