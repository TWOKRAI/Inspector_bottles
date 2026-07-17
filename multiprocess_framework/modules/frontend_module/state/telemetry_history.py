# -*- coding: utf-8 -*-
"""telemetry_history.py — generic read-сторона SQLite-истории телеметрии для GUI.

Принцип «запись — всегда, чтение — локально, история — по запросу». История
телеметрии пишется отдельным писателем (в прототипе — плагин ``telemetry_sink``)
в SQLite-таблицу; этот модуль закрывает read-сторону для GUI: диапазонная
выборка метрик процесса с даунсемплом.

Модуль generic: имя таблицы, whitelist колонок-метрик и путь к файлу БД —
аргументы конструктора (никаких прикладных дефолтов). Приложение (тонкая
конфигурация) передаёт схему своего стока телеметрии.

Live ≠ история: последние ~N минут — из кольцевых буферов
:class:`TelemetryViewModel` (в памяти, без похода в БД); глубже (час/день) —
отсюда.

Отказоустойчивость (обязательна для GUI): нет файла БД / нет таблицы / БД занята
→ ``list_range`` возвращает пустой список, НЕ бросает исключение — график просто
показывает «нет данных», не валит вкладку.
"""

from __future__ import annotations

import logging
import os
import sqlite3
from collections.abc import Sequence
from typing import Any

_logger = logging.getLogger(__name__)

# Дефолт даунсемпла, если вызывающий не указал max_points явно.
_DEFAULT_MAX_POINTS = 300


class TelemetryHistorySource:
    """Read-only источник истории телеметрии из SQLite-таблицы стока.

    Открывает БД в режиме ``mode=ro`` — GUI никогда не пишет и не держит
    блокировку записи (писатель — отдельный процесс/плагин). Соединение
    открывается на КАЖДЫЙ запрос и сразу закрывается — не держит файл между
    вызовами, что упрощает конкурентный доступ читателя к WAL-файлу, который
    параллельно пишет другой процесс.

    Generic: имя таблицы, whitelist метрик и имена служебных колонок задаются
    конструктором. Модуль не знает прикладной схемы стока.
    """

    def __init__(
        self,
        db_path: str,
        *,
        table_name: str,
        allowed_metrics: frozenset[str] | set[str] | Sequence[str],
        ts_column: str = "ts",
        key_column: str = "process_name",
    ) -> None:
        """
        Args:
            db_path: путь к SQLite-файлу истории.
            table_name: имя таблицы истории (например ``telemetry_snapshots``).
            allowed_metrics: whitelist имён колонок-метрик. Защита от
                SQL-инъекции через имя колонки: в SELECT подставляются ТОЛЬКО
                эти имена, всё остальное из ``metrics`` молча отбрасывается.
            ts_column: имя колонки временной метки (unix-время).
            key_column: имя колонки ключа выборки (обычно имя процесса).
        """
        self._db_path = db_path
        self._table = table_name
        self._allowed = frozenset(allowed_metrics)
        self._ts_col = ts_column
        self._key_col = key_column

    @property
    def db_path(self) -> str:
        return self._db_path

    @property
    def allowed_metrics(self) -> frozenset[str]:
        return self._allowed

    def list_range(
        self,
        key: str,
        ts_from: float,
        ts_to: float,
        metrics: Sequence[str],
        max_points: int = _DEFAULT_MAX_POINTS,
    ) -> list[dict[str, Any]]:
        """Диапазонная выборка метрик по ключу с даунсемплом до ``max_points``.

        Args:
            key: значение ключевой колонки (обычно имя процесса).
            ts_from/ts_to: границы диапазона ``ts`` (unix-время, включительно).
            metrics: запрошенные метрики; фильтруются через whitelist
                ``allowed_metrics`` — неизвестные имена молча игнорируются
                (не подставляются в SQL, не роняют запрос).
            max_points: верхняя граница числа возвращаемых точек — равномерное
                прореживание по индексу хронологически отсортированной выборки.

        Returns:
            Список dict вида ``{"ts": ..., <metric>: value, ...}`` в
            хронологическом порядке. Пусто — если файла/таблицы нет, БД занята,
            в диапазоне нет строк, или ни одна метрика не прошла whitelist.
        """
        cols = [m for m in metrics if m in self._allowed]
        if not cols:
            return []

        conn = self._connect()
        if conn is None:
            return []
        try:
            col_list = ", ".join(cols)
            # nosec B608: инъекция невозможна — cols отфильтрованы через
            # whitelist allowed_metrics (только литералы имён колонок), имена
            # таблицы/колонок — из доверенной конфигурации приложения; все
            # ЗНАЧЕНИЯ параметризованы плейсхолдерами (?). Имена колонок в SQL
            # параметризовать нельзя, whitelist — штатная защита.
            sql = (
                f"SELECT {self._ts_col}, {col_list} FROM {self._table} "  # nosec B608
                f"WHERE {self._key_col} = ? AND {self._ts_col} >= ? AND {self._ts_col} <= ? "
                f"ORDER BY {self._ts_col} ASC"
            )
            cur = conn.execute(sql, (key, ts_from, ts_to))
            rows = cur.fetchall()
        except sqlite3.Error as exc:
            # Таблицы нет (БД ещё не проинициализирована стоком) / БД занята /
            # прочая транзиентная ошибка чтения — не роняем GUI.
            _logger.warning(
                "TelemetryHistorySource: list_range(%s) упал (%s) — возвращаю пусто",
                key,
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
        (QThreadPool), не только из Qt main thread.
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


__all__ = ["TelemetryHistorySource"]
