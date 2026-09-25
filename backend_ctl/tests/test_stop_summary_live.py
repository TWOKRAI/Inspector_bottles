# -*- coding: utf-8 -*-
"""Приёмка Task 1.6 (независимый тестер, вслепую): сводка стопа в observability.db.

Источник контракта — «Контракт записи» из брифа лида (см. `TASK: 1.6` в задаче,
раздел плана `plans/lifecycle-stop-ownership.md` → Task 1.6). ``interface.py``
для этого механизма нет — implementation, план целиком и авторские тесты НЕ
читались (запрещены заданием); контракт пинуется буквально по литералам брифа.

Контракт (буквально):
  - Ровно одна запись на ``PM.shutdown()``: ``process='ProcessManager'``,
    ``message`` начинается с ``stop summary:``.
  - ``extra["context"]`` (JSON) несёт ключ ``stop_summary`` -> ``{имя_ребёнка: {"released": int,
    "buffered_dropped": int, "reported": bool}}`` по каждому ребёнку, остановленному
    этим ``stop_all`` — все 6 детей ``inspection_full``.
  - ``reported=false`` — ребёнок не дошёл до хука выхода (kill/terminate, упал до
    ``finally``); тогда released/buffered_dropped = 0 и это «не знаем».
  - Числа ребёнка равны числам его stderr-строки
    ``<name>: queues released to gone readers: N, buffered dropped: M``;
    нет строки -> released=0, buffered_dropped=0 при reported=true.
  - Severity: WARNING, если у кого-то released>0, buffered_dropped>0 или
    reported=false; иначе INFO.

Путь до БД — ``<log_dir>/observability.db`` (``resolve_default_db_path()``:
env ``MULTIPROCESS_LOG_DIR`` сильнее ``INSPECTOR_LOG_DIR``). ``INSPECTOR_LOG_DIR``
у сборки ставится ``os.environ.setdefault(...)`` (``launch.py:669``) — ловушка:
ПЕРВЫЙ ``harness.start()`` в процессе pytest фиксирует его для ВСЕХ последующих
запусков в том же процессе. Каждый тест здесь принудительно ставит
``MULTIPROCESS_LOG_DIR`` (обычное присваивание через ``monkeypatch.setenv``,
не ``setdefault``) на СВОЙ ``tmp_path`` ДО ``harness.start()`` — он идёт первым
в приоритете и снимает ловушку независимо от порядка тестов в файле.

Собственный диапазон портов 9810-9829 (бриф).
"""

from __future__ import annotations

import os
import re
import signal
import time
from typing import Any, Dict, List

import pytest

from backend_ctl.harness import BackendHarness
from multiprocess_framework.modules.channel_routing_module.observability import (
    ObservabilityStore,
)

_PORT_BASE = 9810
_RECIPE = "multiprocess_prototype/backend/topology/inspection_full.yaml"
_CHILDREN = ("camera_0", "processor", "renderer", "inspector", "storage", "gui")

_STDERR_LINE_RE = re.compile(r"(\w+): queues released to gone readers: (\d+), buffered dropped: (\d+)")


def _stop_summary_records(store: ObservabilityStore) -> List[Dict[str, Any]]:
    """Записи-кандидаты сводки стопа: ``process='ProcessManager'`` + префикс сообщения.

    Питоновский фильтр после чтения, а не SQL-фильтр по ``process=`` — контракт
    называет литерал ``'ProcessManager'``, но не гарантирует, что ``list_records``
    сегодня умеет фильтровать по нему для ЭТОГО имени; независимый широкий срез
    надёжнее узкого запроса, придуманного тестером.
    """
    rows = store.list_records(limit=5000, newest_first=False)
    return [
        r
        for r in rows
        if r.get("process") == "ProcessManager" and str(r.get("message", "")).startswith("stop summary:")
    ]


def _stop_summary_of(record: Dict[str, Any]) -> Any:
    """``extra["context"]["stop_summary"]`` записи (None, если пути нет).

    Правка контракта ведущим 2026-09-25: стор кладёт структурные kwargs лог-записи
    в ``extra["context"]`` (так у всех записей PM: ``proc_name``/``pid``/``recipe``),
    исходная буква контракта «ключ в ``extra``» была неточна — эскалация developer.
    """
    context = (record.get("extra") or {}).get("context") or {}
    return context.get("stop_summary")


def _expected_severity(summary: Dict[str, Dict[str, Any]]) -> str:
    """Правило severity буквально по брифу — независимая реализация, не вызов кода под тестом."""
    any_bad = any(
        entry.get("released", 0) > 0 or entry.get("buffered_dropped", 0) > 0 or entry.get("reported") is False
        for entry in summary.values()
    )
    return "WARNING" if any_bad else "INFO"


@pytest.mark.harness_smoke
def test_normal_stop_writes_one_stop_summary_record(monkeypatch, tmp_path) -> None:
    """Обычный стоп `inspection_full`: ровно одна запись сводки, все 6 детей, reported=true.

    Живой трафик лёгкий (2.0s), поэтому severity здесь НЕ фиксируется литералом —
    только правило («см. `_expected_severity`) сверяется с реальными числами
    ТОЙ ЖЕ записи (кросс-поле severity <-> extra, не self-fulfilling: обе стороны
    читаются из независимо устроенных колонок ``severity``/``extra``).
    """
    log_dir = tmp_path / "run_normal"
    monkeypatch.setenv("MULTIPROCESS_LOG_DIR", str(log_dir))
    harness = BackendHarness(recipe=_RECIPE, port=_PORT_BASE, warmup=1.0, log_dir=log_dir)
    try:
        harness.start()
        time.sleep(2.0)
    finally:
        harness.stop()

    store = ObservabilityStore(str(log_dir / "observability.db"))
    try:
        matches = _stop_summary_records(store)
    finally:
        store.close()

    assert len(matches) == 1, (
        f"ожидалась РОВНО одна запись сводки стопа (process='ProcessManager', "
        f"message startswith 'stop summary:'), найдено {len(matches)}: {matches!r}"
    )
    record = matches[0]
    assert record["message"].startswith("stop summary:"), record["message"]

    summary = _stop_summary_of(record)
    assert summary is not None, f"extra.context без ключа 'stop_summary': {record.get('extra')!r}"
    assert isinstance(summary, dict), f"stop_summary не dict: {summary!r}"
    assert set(summary.keys()) == set(_CHILDREN), (
        f"stop_summary покрывает не всех 6 детей inspection_full: "
        f"есть {sorted(summary.keys())}, ожидались {sorted(_CHILDREN)}"
    )
    for name, entry in summary.items():
        assert set(entry.keys()) == {"released", "buffered_dropped", "reported"}, (
            f"{name}: неверный набор ключей записи {entry!r}"
        )
        assert isinstance(entry["released"], int) and entry["released"] >= 0, (name, entry)
        assert isinstance(entry["buffered_dropped"], int) and entry["buffered_dropped"] >= 0, (name, entry)
        assert entry["reported"] is True, f"{name}: обычный стоп обязан дойти до хука выхода, entry={entry!r}"

    expected_severity = _expected_severity(summary)
    assert str(record["severity"]).upper() == expected_severity, (
        f"severity={record['severity']!r} не совпадает с правилом брифа "
        f"(WARNING если у кого-то released>0/buffered_dropped>0/reported=false, иначе INFO) "
        f"по числам самой записи: {summary!r}"
    )


def test_stop_summary_numbers_match_stderr_lines(capfd, monkeypatch, tmp_path) -> None:
    """Числа сводки по каждому ребёнку равны числам его stderr-строки (или 0,0 без строки).

    ``capfd`` — OS-уровень: дочерние процессы наследуют файловые дескрипторы
    родителя (тот же приём, что в `test_system_shutdown_live.py`), поэтому их
    stderr виден здесь так же, как и у самого pytest-процесса.
    """
    log_dir = tmp_path / "run_stderr"
    monkeypatch.setenv("MULTIPROCESS_LOG_DIR", str(log_dir))
    harness = BackendHarness(recipe=_RECIPE, port=_PORT_BASE + 1, warmup=1.0, log_dir=log_dir)
    combined = ""
    try:
        capfd.readouterr()  # слить хвост предыдущего теста в этом же pytest-процессе
        harness.start()
        time.sleep(2.0)
    finally:
        harness.stop()
        captured = capfd.readouterr()
        combined = captured.out + captured.err

    store = ObservabilityStore(str(log_dir / "observability.db"))
    try:
        matches = _stop_summary_records(store)
    finally:
        store.close()

    assert len(matches) == 1, f"ожидалась РОВНО одна запись сводки стопа, найдено {len(matches)}: {matches!r}"
    summary = _stop_summary_of(matches[0])
    assert isinstance(summary, dict), f"stop_summary отсутствует/не dict: {matches[0]!r}"

    stderr_numbers: Dict[str, tuple] = {}
    for m in _STDERR_LINE_RE.finditer(combined):
        stderr_numbers[m.group(1)] = (int(m.group(2)), int(m.group(3)))

    for name in _CHILDREN:
        expected_released, expected_buffered = stderr_numbers.get(name, (0, 0))
        entry = summary.get(name)
        assert entry is not None, f"{name} отсутствует в stop_summary: {summary!r}"
        assert entry["released"] == expected_released, (
            f"{name}: released={entry['released']!r}, ожидалось {expected_released} "
            f"(из stderr {stderr_numbers.get(name)!r}); полный stderr/stdout ниже\n{combined}"
        )
        assert entry["buffered_dropped"] == expected_buffered, (
            f"{name}: buffered_dropped={entry['buffered_dropped']!r}, ожидалось {expected_buffered} "
            f"(из stderr {stderr_numbers.get(name)!r})"
        )
        assert entry["reported"] is True, f"{name}: обычный стоп — reported обязан быть true, entry={entry!r}"


@pytest.mark.skipif(os.name == "nt", reason="POSIX-only: os.kill(SIGKILL) на реальный pid ребёнка")
def test_killed_child_is_reported_false_and_warning(capfd, monkeypatch, tmp_path) -> None:
    """Убитый до стопа ребёнок -> reported=false, released/buffered_dropped=0, severity WARNING.

    Детерминизм убийства: ``FW_AUTORESTART=0`` (env, откат авто-рестарта — см.
    `process_manager_process.py`, `RestartPolicy`/`is_enabled("FW_AUTORESTART")`)
    отключает монитор PM ПОЛНОСТЬЮ ДО спавна, поэтому убитый ``renderer`` не
    воскресает новым инстансом до `harness.stop()` — гонка с авто-рестартом
    исключена структурно, а не таймингом.
    """
    monkeypatch.setenv("FW_AUTORESTART", "0")
    log_dir = tmp_path / "run_kill"
    monkeypatch.setenv("MULTIPROCESS_LOG_DIR", str(log_dir))
    harness = BackendHarness(recipe=_RECIPE, port=_PORT_BASE + 2, warmup=1.0, log_dir=log_dir)
    combined = ""
    try:
        capfd.readouterr()  # слить хвост предыдущего теста в этом же pytest-процессе
        drv = harness.start()
        time.sleep(2.0)
        reply = drv.system_command({"cmd": "supervision.status", "process": "renderer"}, timeout=5.0)
        assert reply.get("success") is True, f"supervision.status отказал: {reply!r}"
        pid = ((reply.get("result") or {}).get("processes") or {}).get("renderer", {}).get("pid")
        assert pid is not None, f"pid 'renderer' неизвестен: {reply!r}"
        os.kill(pid, signal.SIGKILL)
        # 1.0s >> monitor_poll_interval (дефолт 0.5s) — PM успевает заметить смерть
        # до stop(); FW_AUTORESTART=0 гарантирует отсутствие воскрешения, а не тайминг.
        time.sleep(1.0)
    finally:
        harness.stop()
        captured = capfd.readouterr()
        combined = captured.out + captured.err

    store = ObservabilityStore(str(log_dir / "observability.db"))
    try:
        matches = _stop_summary_records(store)
    finally:
        store.close()

    assert len(matches) == 1, f"ожидалась РОВНО одна запись сводки стопа, найдено {len(matches)}: {matches!r}"
    record = matches[0]
    summary = _stop_summary_of(record) or {}
    renderer_entry = summary.get("renderer")
    assert renderer_entry == {"released": 0, "buffered_dropped": 0, "reported": False}, (
        f"renderer: ожидалась ровно {{'released': 0, 'buffered_dropped': 0, 'reported': False}} "
        f"(убит SIGKILL до стопа), получено {renderer_entry!r}"
    )
    assert str(record["severity"]).upper() == "WARNING", (
        f"severity={record['severity']!r}, ожидалось WARNING (renderer.reported=false)"
    )

    # Добор ведущего 2026-09-25 (инъекция I6): сверка чисел со stderr в
    # test_stop_summary_numbers_match_stderr_lines вероятностная — на обычном стопе
    # потери бывают не всегда (перестановка released/buffered_dropped поймана 1 из 3).
    # Убитый читатель даёт потерю устойчиво (замер: processor 1/38 в 2 из 2 прогонов),
    # поэтому здесь сверка не пустая: сначала — что потеря вообще была.
    stderr_numbers: Dict[str, tuple] = {}
    for m in _STDERR_LINE_RE.finditer(combined):
        stderr_numbers[m.group(1)] = (int(m.group(2)), int(m.group(3)))
    assert any(n[0] > 0 for n in stderr_numbers.values()), (
        f"убитый renderer не дал ни одной строки потерь в stderr — сверка чисел была бы пустой; "
        f"сводка: {summary!r}"
    )
    for name in _CHILDREN:
        expected = stderr_numbers.get(name, (0, 0))
        entry = summary.get(name) or {}
        assert (entry.get("released"), entry.get("buffered_dropped")) == expected, (
            f"{name}: сводка {entry!r} расходится со stderr {expected!r}"
        )
