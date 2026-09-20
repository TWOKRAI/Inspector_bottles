# -*- coding: utf-8 -*-
"""Независимая приёмка Task 3.1 плана ``observability-closure`` — К8 (долг Task 3.5).

**RED-набор, написан ДО реализации.** Тестер работал в отдельном git worktree
(``.claude/worktrees/f3-t31``) на коммите ``610698c0`` — ДО правки Task 3.1,
не видел diff/реализацию, не читал ``_impl/`` (в этом дереве такой директории
нет). Источник критерия — К8 из «### Task 3.1» в
``plans/observability-closure/phase-3-store-and-signal.md``, а НЕ сегодняшнее
поведение ``BackendDriver.history_query``.

======================================================================
К8 дословно
======================================================================

«Долг Task 3.5 закрыт. ``history_query(metric="capture.drops", since=-600)``
больше не отказывает и возвращает, сверх обычного конверта Task 3.5, ключ
``series``: ``[[ts, value], …]``, СТАРЫЕ ПЕРВЫМИ — обратный порядок
относительно ``rows`` (те остаются ``ORDER BY id DESC`` по К4 задачи 3.5),
потому что ряд читают как временной, а ленту — как хвост. Строка без
числового ``extra.value`` в ``series`` не попадает, но остаётся в ``rows``;
расхождение длин названо, а не молчаливо.»

Сегодня (ПОДТВЕРЖДЕНО чтением ``backend_ctl/driver.py``) метод отказывает
ПЕРВОЙ строкой при любом ``metric is not None``, ДО readback'а и до открытия
файла — поэтому ВСЕ тесты этого файла сегодня падают на одной и той же
строке (``assert result["success"] is True``), что честно и предсказано (тот
же класс, что «несколько тестов делят один блокирующий ``AttributeError``» —
см. память tester'а ``feedback_red_without_interface_needs_one_named_guessed_hook``),
и разойдутся по разным причинам только после того, как отказ будет снят.

======================================================================
Важная находка контракта — см. отчёт тестера, пункт 4 (дыра в контракте)
======================================================================

Файл ``backend_ctl/driver.py`` НЕ упомянут в разделе «Files» Task 3.1 плана
(там перечислены только ``statistics_module``/``channel_routing_module``/
``process_module`` пути) — при этом К8 буквально требует правки именно этого
метода (снять ранний отказ по ``metric``, добавить фильтр в
``_history_where_clauses``/``_history_list_rows``, построить ``series``).
Явно назвал это тестер, задача выдана мне (три файла, включая этот) — то есть
лид уже знает про эту работу, а «Files» в тексте плана просто не обновлён.

======================================================================
Что здесь НЕ проверяется (сознательно, не забыто)
======================================================================

* Живое «≥ 50 точек, такт 5.0 с» (акцептанс-критерий «Долг из Task 3.5») —
  нужен работающий бэкенд с реальной плоскостью observation; здесь проверяется
  МЕХАНИЗМ (сортировка/фильтрация/исключение нечисловых строк) на маленькой,
  автономной sqlite-фикстуре.
* Точное имя поля/механизм, которым «расхождение длин ``rows``/``series``
  названо» (план не даёт литерала для этого — см. отчёт тестера).
* Обновление ``TestK7MetricNotYetSupported`` в
  ``test_task_3_5_history_query.py`` (эта задача его переживёт как
  противоречащий новому поведению) — не мой файл, трогать нельзя.
"""

from __future__ import annotations

import copy
import json
import sqlite3
import time
from typing import Any, Dict, List, Optional


from backend_ctl.driver import BackendDriver

#: К8: буквальное имя метрики из акцептанс-критерия («Долг из Task 3.5»,
#: capture.drops — единственная из трёх реальных имён плоскости observation,
#: на которую переписан долг задачи 3.5, см. «исправление 1» К-контракта).
METRIC_NAME = "capture.drops"


# ---------------------------------------------------------------------------
# Фейковый driver — тот же приём, что у test_task_3_5_history_query.py
# (не импортирую оттуда: тестовые файлы не предназначены для взаимного
# импорта, здесь — свой компактный дубль минимально нужной части).
# ---------------------------------------------------------------------------


class _FakeSendCommand:
    def __init__(self, response: Dict[str, Any]) -> None:
        self.calls: List[tuple] = []
        self._response = response

    def __call__(self, target: str, command: str, args: Optional[dict] = None, *, timeout: Optional[float] = None):
        self.calls.append((target, command, args, timeout))
        return copy.deepcopy(self._response)


def _driver_with_response(response: Dict[str, Any]) -> BackendDriver:
    drv = BackendDriver()
    drv.send_command = _FakeSendCommand(response)  # type: ignore[assignment]
    return drv


def _ok_response(db_path: str) -> Dict[str, Any]:
    """Форма ответа ``introspect.observability`` — история включена, путь известен
    (ровно форма, которую строит ``BuiltinCommands._history_report()``, см.
    ``test_task_3_5_history_query.py::_ok_response`` — тот же прецедент)."""
    return {"success": True, "process": "ProcessManager", "history": {"enabled": True, "db_path": db_path}}


# ---------------------------------------------------------------------------
# Фикстура: sqlite-файл С УЖЕ ДОБАВЛЕННОЙ (руками, не через реализацию Task 3.1)
# колонкой ``metric`` — читаю ТОЛЬКО схему, которую history_query потребляет
# напрямую (см. ``_HISTORY_COLUMNS`` в driver.py), поэтому строю её сырым SQL,
# а не через ``ObservabilityStore`` (тот сегодня колонку metric не заводит —
# это ПРЕДМЕТ К4/К5, проверенный отдельно в channel_routing_module).
# ---------------------------------------------------------------------------


def _seed_metric_store(tmp_path):
    """Четыре строки ``capture.drops``: три с числовым ``extra.value`` (старые
    первыми по ts) + одна БЕЗ числового значения (испорченный/иной вид записи
    той же метрики) — специально НЕ в ts-порядке относительно строк со
    значением, чтобы протестировать исключение независимо от совпадения
    id-порядка и ts-порядка.

    Возвращает (db_path, [ts_30, ts_20, ts_10, ts_25]) — четыре метки времени
    "сейчас минус N секунд", в порядке ВСТАВКИ (id 1..4).
    """
    now = time.time()
    ts_30, ts_20, ts_10, ts_25 = now - 30.0, now - 20.0, now - 10.0, now - 25.0

    db_path = str(tmp_path / "obs_with_metric.db")
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE records (id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, "
        "process TEXT, module TEXT NOT NULL, ts REAL NOT NULL, severity TEXT, "
        "severity_number INTEGER, message TEXT, extra TEXT, metric TEXT)"
    )
    rows = [
        # (id 1) ts_30 — старейшая числовая точка
        (
            "observation",
            "camera_0",
            "capture",
            ts_30,
            "number",
            0,
            METRIC_NAME,
            json.dumps({"writer": "capture", "metric": "drops", "value": 1.0}),
            METRIC_NAME,
        ),
        # (id 2) ts_20
        (
            "observation",
            "camera_0",
            "capture",
            ts_20,
            "number",
            0,
            METRIC_NAME,
            json.dumps({"writer": "capture", "metric": "drops", "value": 2.0}),
            METRIC_NAME,
        ),
        # (id 3) ts_10 — самая свежая числовая точка
        (
            "observation",
            "camera_0",
            "capture",
            ts_10,
            "number",
            0,
            METRIC_NAME,
            json.dumps({"writer": "capture", "metric": "drops", "value": 3.0}),
            METRIC_NAME,
        ),
        # (id 4) ts_25 — та же метрика, БЕЗ числового extra.value (нет ключа "value")
        (
            "observation",
            "camera_0",
            "capture",
            ts_25,
            "number",
            0,
            METRIC_NAME,
            json.dumps({"writer": "capture", "metric": "drops"}),
            METRIC_NAME,
        ),
    ]
    for kind, process, module, ts, severity, sevnum, message, extra, metric in rows:
        conn.execute(
            "INSERT INTO records (kind, process, module, ts, severity, severity_number, message, extra, metric) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (kind, process, module, ts, severity, sevnum, message, extra, metric),
        )
    conn.commit()
    conn.close()
    return db_path, (ts_30, ts_20, ts_10, ts_25)


def _approx_ts(actual: float, expected: float) -> bool:
    """Сравнение ts с допуском: ``time.time()``-фикстура, а не целочисленный литерал —
    допускаю округление до мс, если реализация его сделает (план этого не требует,
    но и не запрещает)."""
    return abs(actual - expected) < 0.01


class TestK8MetricFilterSucceedsInsteadOfRefusing:
    def test_metric_filter_no_longer_returns_the_task_3_5_refusal(self, tmp_path) -> None:
        """Ведущая проверка К8: долг закрыт, вызов с ``metric=`` больше не отказывает.

        Сегодня падает здесь — ``BackendDriver.history_query`` отказывает
        ПЕРВОЙ строкой при любом ``metric is not None`` (прочитано в коде,
        строка 796: ``if metric is not None: return _history_fail(...)``),
        ДО обращения к readback'у и до открытия sqlite-файла.
        """
        db_path, _ = _seed_metric_store(tmp_path)
        drv = _driver_with_response(_ok_response(db_path))
        result = drv.history_query(metric=METRIC_NAME, since=-600)
        assert result.get("success") is True, (
            f"history_query(metric=...) обязан ПЕРЕСТАТЬ отказывать (долг Task 3.5 закрыт К8) — получено {result}"
        )


class TestK8SeriesKeyOldestFirst:
    def test_series_is_ascending_ts_value_pairs_for_the_numeric_rows(self, tmp_path) -> None:
        """К8: «``series``: ``[[ts, value], …]``, СТАРЫЕ ПЕРВЫМИ» — литеральные значения,
        а не пересчёт форматом ответа (три числовые точки из четырёх строк фикстуры).
        """
        db_path, (ts_30, ts_20, ts_10, _ts_25) = _seed_metric_store(tmp_path)
        drv = _driver_with_response(_ok_response(db_path))
        result = drv.history_query(metric=METRIC_NAME, since=-600)

        assert result.get("success") is True, f"история отказала: {result}"
        series = result.get("series")
        assert series is not None, f"в ответе нет ключа 'series' — доступные ключи: {sorted(result.keys())}"
        assert len(series) == 3, f"ожидались 3 числовые точки (четвёртая строка без extra.value), получено {series}"

        expected_values = [1.0, 2.0, 3.0]
        expected_ts = [ts_30, ts_20, ts_10]
        for i, (pair, exp_ts, exp_value) in enumerate(zip(series, expected_ts, expected_values)):
            assert len(pair) == 2, f"точка №{i} обязана быть парой [ts, value], получено {pair}"
            assert _approx_ts(pair[0], exp_ts), (
                f"точка №{i}: ts {pair[0]} не совпадает с ожидаемым {exp_ts} (старые первыми)"
            )
            assert pair[1] == exp_value, f"точка №{i}: value {pair[1]} != ожидаемого {exp_value}"


class TestK8NonNumericRowStaysInRowsButDropsFromSeries:
    def test_row_without_numeric_extra_value_is_excluded_from_series_but_kept_in_rows(self, tmp_path) -> None:
        """К8: «Строка без числового ``extra.value`` в ``series`` не попадает, но
        остаётся в ``rows``; расхождение длин названо, а не молчаливо.»

        Проверяю ОДНОЗНАЧНО специфицированную часть (числа строк и то, что
        «пропавшая» точка не всплывает в ``series`` по своему ``ts``) —
        КАКИМ ИМЕННО способом расхождение «названо» план не уточняет (нет
        литерала для поля-счётчика/флага), поэтому этого я не угадываю: см.
        отчёт тестера, пункт 4.
        """
        db_path, (_ts_30, _ts_20, _ts_10, ts_25) = _seed_metric_store(tmp_path)
        drv = _driver_with_response(_ok_response(db_path))
        result = drv.history_query(metric=METRIC_NAME, since=-600)

        assert result.get("success") is True, f"история отказала: {result}"
        rows = result.get("rows")
        series = result.get("series")
        assert rows is not None and series is not None

        assert len(rows) == 4, f"все четыре строки метрики обязаны остаться в rows, получено {len(rows)}"
        assert len(series) == 3, f"ровно одна (без числового value) обязана выпасть из series, получено {len(series)}"
        assert not any(_approx_ts(pair[0], ts_25) for pair in series), (
            f"точка без числового extra.value (ts≈{ts_25}) не должна попасть в series: {series}"
        )


class TestK8RowsOrderIsIndependentOfSeriesOrder:
    def test_rows_stay_ordered_newest_id_first_regardless_of_series(self, tmp_path) -> None:
        """К8: «``rows`` остаются ``ORDER BY id DESC`` (те К4 задачи 3.5)» — не меняется
        добавлением ``series``. Фикстура вставлена НЕ в ts-порядке (id4 несёт ts_25,
        которое лежит МЕЖДУ id1 и id2 по времени) специально, чтобы id-порядок и
        ts-порядок не совпадали случайно.
        """
        db_path, _ = _seed_metric_store(tmp_path)
        drv = _driver_with_response(_ok_response(db_path))
        result = drv.history_query(metric=METRIC_NAME, since=-600)

        assert result.get("success") is True, f"история отказала: {result}"
        rows = result.get("rows")
        assert rows is not None
        assert [r["id"] for r in rows] == [4, 3, 2, 1], (
            f"rows обязаны идти по id DESC (свежие первыми) независимо от ts-порядка series, "
            f"получено id-последовательность {[r.get('id') for r in rows]}"
        )
