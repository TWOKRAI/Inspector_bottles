# -*- coding: utf-8 -*-
"""telemetry_history.py — read-сторона ``telemetry.db`` для GUI (Ф2, Task 2.1).

Принцип плана gui-telemetry-read-model: «запись — всегда, чтение — локально,
история — по запросу». История уже пишется плагином ``telemetry_sink``
(``Plugins/io/telemetry_sink``, таблица ``telemetry_snapshots``, семпл 5 с) —
этот модуль закрывает read-сторону для GUI: диапазонная выборка с даунсемплом,
паттерн ``RecordSource`` вкладки «Наблюдаемость»
(``frontend/widgets/tabs/observability/record_source.py``), но без пагинации —
графику нужен весь диапазон целиком (прорежённый), не постранично.

Live ≠ история: последние ~10 мин — из кольцевых буферов ``TelemetryViewModel``
(Task 1.2, в памяти, без похода в БД); глубже (час/день) — отсюда.

Отказоустойчивость (обязательна для GUI): нет файла БД / нет таблицы / БД занята
→ ``list_range`` возвращает пустой список, НЕ бросает исключение — график просто
показывает «нет данных», не валит вкладку.

Путь к БД изолирован в ОДНОМ месте (``resolve_telemetry_db_path``) — план
отмечает риск переезда ``telemetry_sink`` в layer-grouping (Task 2.1, риск
«telemetry_sink переезжает в stdlib/»): переезд кода стока эту функцию не
затронет, менять придётся только её тело.
"""

from __future__ import annotations

import logging
import os
import sqlite3
from collections.abc import Sequence
from typing import Any

_logger = logging.getLogger(__name__)

# Whitelist колонок-метрик ``telemetry_snapshots``
# (Plugins/io/telemetry_sink/schemas.py::TelemetrySnapshot). Защита от
# SQL-инъекции через имя колонки: в SELECT подставляются ТОЛЬКО эти имена,
# всё остальное из ``metrics`` молча отбрасывается.
ALLOWED_METRICS: frozenset[str] = frozenset({"fps", "latency_ms", "uptime_s", "status"})

# Дефолт даунсемпла, если вызывающий не указал max_points явно.
_DEFAULT_MAX_POINTS = 300

# Имя таблицы истории (см. TelemetrySnapshot.SQLMeta.table_name).
_TABLE = "telemetry_snapshots"


def resolve_telemetry_db_path() -> str:
    """Путь к SQLite-файлу истории телеметрии — единая точка в GUI-слое.

    Приоритет: env ``INSPECTOR_TELEMETRY_DB`` → дефолт ``data/telemetry.db``
    (тот же дефолт, что у ``TelemetrySinkRegisters.db_path`` — относительно cwd
    процесса; GUI и telemetry_sink запускаются из одного корня прототипа).
    """
    override = os.environ.get("INSPECTOR_TELEMETRY_DB")
    return override if override else "data/telemetry.db"


class TelemetryHistorySource:
    """Read-only источник истории телеметрии (паттерн ``RecordSource`` Наблюдаемости).

    Открывает ``telemetry.db`` в режиме ``mode=ro`` — GUI никогда не пишет и не
    держит блокировку записи (писатель — ``TelemetrySinkPlugin``, отдельный
    процесс). Соединение открывается на КАЖДЫЙ запрос и сразу закрывается —
    не держит файл между вызовами, что упрощает конкурентный доступ читателя
    к WAL-файлу, который параллельно пишет другой процесс.
    """

    def __init__(self, db_path: str | None = None) -> None:
        """
        Args:
            db_path: путь к SQLite-файлу. None → ``resolve_telemetry_db_path()``.
        """
        self._db_path = db_path if db_path is not None else resolve_telemetry_db_path()

    @property
    def db_path(self) -> str:
        return self._db_path

    def list_range(
        self,
        process_name: str,
        ts_from: float,
        ts_to: float,
        metrics: Sequence[str],
        max_points: int = _DEFAULT_MAX_POINTS,
    ) -> list[dict[str, Any]]:
        """Диапазонная выборка метрик процесса с даунсемплом до ``max_points``.

        Args:
            process_name: имя процесса (``telemetry_snapshots.process_name``).
            ts_from/ts_to: границы диапазона ``ts`` (unix-время, включительно).
            metrics: запрошенные метрики; фильтруются через whitelist
                ``ALLOWED_METRICS`` — неизвестные имена молча игнорируются
                (не подставляются в SQL, не роняют запрос).
            max_points: верхняя граница числа возвращаемых точек — равномерное
                прореживание по индексу хронологически отсортированной выборки
                (не тащим в GUI все строки диапазона).

        Returns:
            Список dict вида ``{"ts": ..., <metric>: value, ...}`` в
            хронологическом порядке. Пусто — если файла/таблицы нет, БД занята,
            в диапазоне нет строк, или ни одна метрика не прошла whitelist.
        """
        cols = [m for m in metrics if m in ALLOWED_METRICS]
        if not cols:
            return []

        conn = self._connect()
        if conn is None:
            return []
        try:
            col_list = ", ".join(cols)
            # nosec B608: инъекция невозможна — cols отфильтрованы через
            # whitelist ALLOWED_METRICS (только литералы имён колонок), _TABLE —
            # константа модуля; все значения параметризованы плейсхолдерами (?).
            # Имена колонок в SQL параметризовать нельзя, whitelist — штатная защита.
            sql = f"SELECT ts, {col_list} FROM {_TABLE} WHERE process_name = ? AND ts >= ? AND ts <= ? ORDER BY ts ASC"  # nosec B608
            cur = conn.execute(sql, (process_name, ts_from, ts_to))
            rows = cur.fetchall()
        except sqlite3.Error as exc:
            # Таблицы нет (БД ещё не проинициализирована стоком) / БД занята /
            # прочая транзиентная ошибка чтения — не роняем GUI.
            _logger.warning(
                "TelemetryHistorySource: list_range(%s) упал (%s) — возвращаю пусто",
                process_name,
                exc,
            )
            return []
        finally:
            conn.close()

        records = [{"ts": row[0], **{col: row[idx + 1] for idx, col in enumerate(cols)}} for row in rows]
        return _downsample(records, max_points)

    def _connect(self) -> sqlite3.Connection | None:
        """Открыть read-only соединение; None — если БД недоступна.

        ``check_same_thread=False``: источник рассчитан на вызов из worker-потока
        (Task 2.2 — RequestRunner/QThreadPool), не только из Qt main thread.
        """
        if not os.path.isfile(self._db_path):
            return None
        try:
            uri = f"file:{self._db_path}?mode=ro"
            return sqlite3.connect(uri, uri=True, check_same_thread=False, timeout=1.0)
        except sqlite3.Error as exc:
            _logger.warning("TelemetryHistorySource: не удалось открыть %s (%s) — возвращаю пусто", self._db_path, exc)
            return None


def _downsample(records: list[dict[str, Any]], max_points: int) -> list[dict[str, Any]]:
    """Равномерное прореживание по индексу до ``max_points`` строк.

    Строки уже отсортированы по ``ts`` (хронологический порядок сохраняется).
    Индексы берутся равномерным шагом ``n / max_points``, последняя точка
    диапазона гарантированно попадает в выборку (иначе график «обрезан»).
    """
    n = len(records)
    if max_points <= 0 or n <= max_points:
        return records
    step = n / max_points
    indices = sorted({int(i * step) for i in range(max_points)})
    if indices[-1] != n - 1:
        indices[-1] = n - 1
    return [records[i] for i in indices]


__all__ = ["TelemetryHistorySource", "resolve_telemetry_db_path", "ALLOWED_METRICS"]
