# -*- coding: utf-8 -*-
"""Авторские hazard-тесты журнала заданий (Task 5.1, Контракт лида ред. 3, §2/«Кто
что пишет»): ``drain`` из такта публикации против ``on_write`` из потока сервера,
``journal_reset`` во время потока заданий.

Приём задания — ``plugin._on_write(fc, addr, values)`` напрямую, тот же приём, что
``tests/test_hazards.py``/``test_journal_commands.py`` — реальный ``SimJournal``,
без подмен. Оба сценария потенциально блокирующие (join на потоках) — по правилу
проекта каждый такой вызов идёт в daemon-потоке со своим дедлайном join, чтобы
зависание не повесило сьют, а свалилось явной ошибкой.
"""

from __future__ import annotations

import socket
import threading
import time

import pytest

from multiprocess_framework.modules.process_module.plugins.base import PluginContext
from multiprocess_framework.modules.process_module.plugins.testing import MockProcessServices
from Plugins.sim.robot_host.plugin import SimRobotHostPlugin
from Services.robot_comm import ROBOT_AVAILABLE
from Services.robot_comm.core.registers import REG_JOB_ECAP, REG_JOB_FLAG, REG_JOB_X, REG_JOB_Y, XY_SCALE

pytestmark = [
    pytest.mark.timeout(30),
    pytest.mark.skipif(not ROBOT_AVAILABLE, reason="pymodbus не установлен"),
]

_HOST = "127.0.0.1"
_FORBIDDEN_PORTS = {5021, 8765, 8766, 8091, 8092}  # живой стенд владельца — не трогать
_JOIN_DEADLINE_S = 15.0

_FC_WRITE_SINGLE = 6
_FC_WRITE_MULTI = 16


def _free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind((_HOST, 0))
        port = s.getsockname()[1]
    finally:
        s.close()
    assert port not in _FORBIDDEN_PORTS, f"порту {port} не повезло совпасть со стендом, перегенерировать"
    return port


def _make_running_plugin() -> tuple[SimRobotHostPlugin, PluginContext, MockProcessServices]:
    port = _free_port()
    services = MockProcessServices(name="robot")
    cfg = {"host": _HOST, "port": port, "unit_id": 2, "auto_start": True}
    ctx = PluginContext(services=services, config=cfg)
    plugin = SimRobotHostPlugin()
    plugin.configure(ctx)
    plugin.start(ctx)
    assert plugin._state == "running", f"сервер не поднялся: {plugin._reason!r}"
    return plugin, ctx, services


def _drive_job(plugin: SimRobotHostPlugin, x_mm: float, y_mm: float, ecap: int) -> None:
    """Транзакция клиента через приёмник сервера: X, Y, DW-энкодер, флаг последним."""
    plugin._on_write(_FC_WRITE_SINGLE, REG_JOB_X, [int(x_mm * XY_SCALE) & 0xFFFF])
    plugin._on_write(_FC_WRITE_SINGLE, REG_JOB_Y, [int(y_mm * XY_SCALE) & 0xFFFF])
    plugin._on_write(_FC_WRITE_MULTI, REG_JOB_ECAP, [ecap & 0xFFFF, (ecap >> 16) & 0xFFFF])
    plugin._on_write(_FC_WRITE_SINGLE, REG_JOB_FLAG, [1])


def _join_or_fail(threads: list[threading.Thread], *, label: str) -> None:
    """Дождаться потоков с общим дедлайном — зависание падает явной ошибкой, не висит сьют."""
    deadline = time.monotonic() + _JOIN_DEADLINE_S
    for t in threads:
        remaining = max(0.0, deadline - time.monotonic())
        t.join(timeout=remaining)
    alive = [t.name for t in threads if t.is_alive()]
    assert not alive, f"{label}: потоки не завершились за {_JOIN_DEADLINE_S} с — похоже на зависание: {alive!r}"


# --------------------------------------------------------------------------- #
# H1 — drain() такта публикации против on_write() приёмного потока             #
# --------------------------------------------------------------------------- #


def test_concurrent_on_write_and_publish_no_exception_and_correct_count() -> None:
    """4 потока пишут задания, ещё один непрерывно тикает ``_publish_once`` —
    ни одно исключение не должно вырваться наружу (``on_write`` зовётся с
    "чужого" потока сервера в проде — см. докстринг ``plugin.py``), и
    ``jobs_seen`` в итоге равен числу реально отправленных взводов флага
    (число задач учитывается атомарно под локом самого ``SimJournal``,
    несмотря на то что координаты из четырёх потоков могут мешаться в тени —
    учёт факта задания и разбор его координат — разные шаги, contract здесь
    гарантирует только первое)."""
    plugin, ctx, _services = _make_running_plugin()
    try:
        n_threads = 4
        jobs_per_thread = 25
        errors: list[BaseException] = []
        errors_lock = threading.Lock()
        stop_publisher = threading.Event()

        def _writer(thread_idx: int) -> None:
            try:
                for i in range(jobs_per_thread):
                    _drive_job(plugin, x_mm=float(thread_idx * 100 + i), y_mm=20.0, ecap=1000 + i)
            except BaseException as exc:  # noqa: BLE001 — хотим увидеть КАЖДОЕ исключение
                with errors_lock:
                    errors.append(exc)

        def _publisher() -> None:
            try:
                while not stop_publisher.is_set():
                    plugin._publish_once()
                    time.sleep(0.001)
            except BaseException as exc:  # noqa: BLE001
                with errors_lock:
                    errors.append(exc)

        publisher_thread = threading.Thread(target=_publisher, name="journal-hazard-publisher", daemon=True)
        publisher_thread.start()

        writer_threads = [
            threading.Thread(target=_writer, args=(i,), name=f"journal-hazard-writer-{i}", daemon=True)
            for i in range(n_threads)
        ]
        for t in writer_threads:
            t.start()

        _join_or_fail(writer_threads, label="писатели заданий")
        stop_publisher.set()
        _join_or_fail([publisher_thread], label="паблишер")

        assert not errors, f"исключение в потоке приёма/публикации: {errors!r}"

        # Финальный тик — забрать то, что писатели успели добавить после
        # последнего тика паблишера (иначе последняя пачка потеряется из
        # recent, но НЕ из живых счётчиков — jobs_seen считается в on_write,
        # не в drain).
        plugin._publish_once()

        counters = plugin._journal.counters()
        assert counters["jobs"] == n_threads * jobs_per_thread, counters
        assert counters["dups"] == counters["dups_same_capture"] + counters["dups_tracked"], counters
    finally:
        plugin.shutdown(ctx)


# --------------------------------------------------------------------------- #
# H2 — journal_reset посреди потока заданий не ломает инвариант dups           #
# --------------------------------------------------------------------------- #


def test_reset_during_job_stream_keeps_dup_invariant_consistent() -> None:
    """``sim_robot.journal_reset`` дёргается ИЗ ДРУГОГО потока, пока льётся поток
    заданий (часть которых — намеренные дубли одной и той же съёмки, чтобы
    ``dups_same_capture`` реально рос). Читатель на каждом тике снимает
    ``counters()`` (снимок атомарен — строится под ``SimJournal._lock``,
    см. ``sim_journal.py``) и проверяет ``dups == dups_same_capture +
    dups_tracked`` — reset обнуляет три поля НЕ одним присваиванием словаря, а
    отдельными строками (см. ``SimJournal.reset``); если бы это не было под
    одним локом с приёмом задания, читатель мог бы поймать половинчатое
    состояние (одно поле уже обнулено, другое — ещё нет)."""
    plugin, ctx, _services = _make_running_plugin()
    try:
        stop = threading.Event()
        errors: list[BaseException] = []
        violations: list[dict] = []
        errors_lock = threading.Lock()

        def _writer() -> None:
            try:
                i = 0
                while not stop.is_set():
                    # Каждая пара — намеренный дубль одной и той же съёмки
                    # (одинаковые X/Y/ecap), чтобы dups_same_capture реально рос
                    # параллельно с ресетами.
                    _drive_job(plugin, x_mm=10.0, y_mm=20.0, ecap=1000 + i)
                    _drive_job(plugin, x_mm=10.0, y_mm=20.0, ecap=1000 + i)
                    i += 1
            except BaseException as exc:  # noqa: BLE001
                with errors_lock:
                    errors.append(exc)

        def _resetter() -> None:
            try:
                while not stop.is_set():
                    plugin.cmd_journal_reset()
                    time.sleep(0.002)
            except BaseException as exc:  # noqa: BLE001
                with errors_lock:
                    errors.append(exc)

        def _reader() -> None:
            try:
                while not stop.is_set():
                    counters = plugin._journal.counters()
                    if counters["dups"] != counters["dups_same_capture"] + counters["dups_tracked"]:
                        violations.append(counters)
                    time.sleep(0.001)
            except BaseException as exc:  # noqa: BLE001
                with errors_lock:
                    errors.append(exc)

        threads = [
            threading.Thread(target=_writer, name="journal-hazard-reset-writer", daemon=True),
            threading.Thread(target=_resetter, name="journal-hazard-resetter", daemon=True),
            threading.Thread(target=_reader, name="journal-hazard-reader", daemon=True),
        ]
        for t in threads:
            t.start()
        time.sleep(0.5)
        stop.set()
        _join_or_fail(threads, label="писатель/ресеттер/читатель")

        assert not errors, f"исключение в потоке writer/resetter/reader: {errors!r}"
        assert not violations, f"инвариант dups == dups_same_capture + dups_tracked нарушен: {violations!r}"
    finally:
        plugin.shutdown(ctx)
