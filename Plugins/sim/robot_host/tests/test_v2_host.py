# -*- coding: utf-8 -*-
"""Слепая приёмка T2.4 (RED до кода): хост sim v2 — ``protocol: v2``, TCP-карта v2, воркеры
вместо сырых потоков, ``belt.*`` и ``fault.*`` на v2, неизвестный ``protocol``, перезапуск.

Контракт — из DESIGN брифа T2.4; реализации хоста v2 перед глазами не было.

Харнесс: ``MockProcessServices`` + реальный ``PluginContext`` + ``ThreadWorkerManager``
(``host_harness.py``): настоящий менеджер воркеров запускает цель в потоке, а
``MockWorkerManager`` только пишет вызов — под ним v2-хост не получил бы ни тика, ни порта.
Воркеры наблюдаются по записи ``create_worker`` в нашем менеджере (имена и число), а не по
потокам: потоки наших воркеров носят имя ``v2fake-worker:<имя>``. К порту хоста ходит клиент v2
(``RobotClientV2`` поверх ``ModbusDevice``); регистры телеметрии читаются по имени из ``REG``.

Ожидание «до прогона»: все тесты КРАСНЫЕ — сегодня ключ ``protocol`` плагин не читает,
хост всегда v1 (``TLM_PROTO_VER`` не 0x0200, в ``sim_robot.status`` нет ``protocol``).
"""

from __future__ import annotations

import socket
import threading
import time

import pytest

from Plugins.sim.robot_host.tests.host_harness import (
    call,
    close_client,
    encoder,
    free_port,
    make_host,
    open_client,
    read_reg,
    run_with_deadline,
)
from Services.modbus.core.device import ModbusDevice
from Services.robot_comm import ROBOT_AVAILABLE

pytestmark = [
    pytest.mark.skipif(not ROBOT_AVAILABLE, reason="pymodbus не установлен"),
]

_RAW_THREAD_NAMES = {"sim-robot-motion", "sim-robot-server"}  # принадлежат v1-пути (DESIGN п.2)
_PROTO_V2_WIRE = 0x0200  # литерал: protocol_v2.CONSTANTS["PROTO_VER"]
_PMIR_MAGIC_WIRE = 0x5632  # литерал: protocol_v2.CONSTANTS["PMIR_MAGIC_VALUE"]


def _start(plugin, ctx) -> None:
    run_with_deadline(lambda: plugin.start(ctx), timeout=10.0, label="start")


def _stop(plugin, ctx, workers) -> None:
    try:
        run_with_deadline(lambda: plugin.shutdown(ctx), timeout=10.0, label="shutdown")
    finally:
        workers.stop_all()


@pytest.fixture
def v2_host():
    """Поднятый v2-хост: (plugin, ctx, services, workers, port); гасится в finally."""
    port = free_port()
    plugin, ctx, services, workers = make_host(port, protocol="v2")
    _start(plugin, ctx)
    try:
        yield plugin, ctx, services, workers, port
    finally:
        _stop(plugin, ctx, workers)


@pytest.fixture
def client_for():
    """Фабрика ``port -> (device, client)`` с гарантированным close."""
    made: list[ModbusDevice] = []

    def _make(port: int):
        device, client = open_client(port)
        made.append(device)
        return device, client

    yield _make
    for device in made:
        close_client(device)


def test_status_protocol_matches_wire(v2_host, client_for) -> None:
    """``sim_robot.status["protocol"] == "v2"`` И провод отвечает ``TLM_PROTO_VER == 0x0200``.

    Проверяются ВМЕСТЕ: одно без другого не доказательство (статус мог бы врать, провод мог бы
    быть чужим). НЕ доказывает: что карта v2 полна (см. test_tcp_reads_pmir_block), что mailbox
    исполняет опкоды (это цикл «кадр → задание → DONE»)."""
    plugin, _ctx, _services, _workers, port = v2_host
    status = call(plugin, "sim_robot.status")
    assert status.get("protocol") == "v2", f"status без protocol=v2: {status!r}"
    device, _client = client_for(port)
    assert read_reg(device, "TLM_PROTO_VER")[0] == _PROTO_V2_WIRE


def test_default_protocol_is_v1() -> None:
    """Без ключа ``protocol`` хост — v1: ``sim_robot.status["protocol"] == "v1"``.

    НЕ доказывает: что провод при v1 остался прежним (его держат старые тесты хоста)."""
    port = free_port()
    plugin, ctx, _services, workers = make_host(port)
    _start(plugin, ctx)
    try:
        status = call(plugin, "sim_robot.status")
        assert status.get("protocol") == "v1", f"по умолчанию ожидался v1: {status!r}"
    finally:
        _stop(plugin, ctx, workers)


def test_tcp_reads_pmir_block(v2_host, client_for) -> None:
    """Блок PMIR по ``REG["PMIR_MAGIC"]`` читается ОДНИМ FC3: слово 0 — ``PMIR_MAGIC`` 0x5632, три слова
    (MAGIC, CRC, DICT) вернулись одним запросом.

    НЕ доказывает: что CRC и словарь верны (значения не пинятся — их источник ядро), что чтение
    через границу ``PMIR_BASE``..``PMIR_MAGIC`` (сам блок PMIR) работает."""
    _plugin, _ctx, _services, _workers, port = v2_host
    device, _client = client_for(port)
    block = read_reg(device, "PMIR_MAGIC", 3)
    assert block[0] == _PMIR_MAGIC_WIRE, f"PMIR_MAGIC: {block[0]:#06x}"


def test_no_raw_threads_under_v2_host() -> None:
    """При живом v2-хосте нет потоков ``sim-robot-motion``/``sim-robot-server``, а тик и слушатель
    идут воркерами ``ctx.worker_manager``.

    Сначала базовая линия: тот же фейковый менеджер под v1 — оба имени в ``threading.enumerate()``
    ЕСТЬ (иначе проверка отсутствия ничего не значит) и создан ``n1`` воркеров. Затем v2: имён нет,
    воркеров создано не меньше ``n1 + 2`` (тик и слушатель переехали в воркеры).

    НЕ доказывает: что два лишних воркера — именно тик и слушатель (имена не пинятся: их выбирает
    реализация); что настоящий ``WorkerManager`` (не наш фейк) их запустит."""
    port1 = free_port()
    plugin1, ctx1, _s1, workers1 = make_host(port1)
    _start(plugin1, ctx1)
    try:
        v1_threads = {t.name for t in threading.enumerate()}
        n1 = len(workers1.created_names)
    finally:
        _stop(plugin1, ctx1, workers1)
    assert _RAW_THREAD_NAMES <= v1_threads, f"базовая линия v1: ожидались {_RAW_THREAD_NAMES}, есть {v1_threads}"
    # Потоки v1 после shutdown() дают закончиться (до 3 с): остаток базовой линии не должен
    # выдать себя за сырые потоки v2-хоста.
    drain_deadline = time.monotonic() + 3.0
    while time.monotonic() < drain_deadline and _RAW_THREAD_NAMES & {t.name for t in threading.enumerate()}:
        time.sleep(0.05)

    port2 = free_port()
    plugin2, ctx2, _s2, workers2 = make_host(port2, protocol="v2")
    _start(plugin2, ctx2)
    try:
        v2_threads = {t.name for t in threading.enumerate()}
        n2 = len(workers2.created_names)
        assert not (_RAW_THREAD_NAMES & v2_threads), f"сырые потоки v1 под v2: {_RAW_THREAD_NAMES & v2_threads}"
        assert n2 >= n1 + 2, f"воркеров под v2 {n2} ({workers2.created_names}), под v1 {n1}: тик и слушатель не воркеры"
    finally:
        _stop(plugin2, ctx2, workers2)


@pytest.mark.parametrize(
    "command, args, secret",
    [
        ("fault.drop", {"seconds": 7919}, "7919"),
        ("fault.delay_ms", {"ms": 7919}, "7919"),
        ("fault.vfd_code", {"code": 7919}, "7919"),
        ("fault.clear", {}, None),
    ],
)
def test_fault_commands_refused_on_v2(v2_host, command, args, secret) -> None:
    """На v2 ``fault.*`` отвечают ``{"status": "error", "message": ...}``: в сообщении «не поддерживается»
    и ``v2``, введённое значение аргумента (7919) в нём НЕ эхом.

    НЕ доказывает: что отказ не оставил побочного эффекта в ядре (``sim_robot.status`` не читается);
    что значение не утекло в ЛОГ (смотрится только ответ команды)."""
    plugin, _ctx, _services, _workers, _port = v2_host
    resp = call(plugin, command, args)
    assert resp.get("status") == "error", f"{command}: ожидался status=error, получено {resp!r}"
    message = str(resp.get("message", ""))
    assert "не поддерживается" in message, f"{command}: нет «не поддерживается»: {message!r}"
    assert "v2" in message, f"{command}: нет «v2»: {message!r}"
    if secret is not None:
        assert secret not in message, f"{command}: значение аргумента эхом в сообщении: {message!r}"


def _poll_encoder_until(device: ModbusDevice, predicate, *, timeout: float, interval: float = 0.05) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate(encoder(device)):
            return True
        time.sleep(interval)
    return False


def test_belt_commands_on_v2(client_for) -> None:
    """``belt.run`` — энкодер на проводе растёт; ``belt.jog`` без подкачки — лента едет и сама
    останавливается по ``jog_timeout_ms`` (энкодер перестаёт расти).

    Хост поднимается с ``jog_timeout_ms=500``. Рост ``belt.run``: ``TLM_ENC`` через 0.5 с строго
    больше, чем был. ``belt.jog`` (direction 1, 10 Гц): за 0.3 с энкодер сдвинулся, затем в течение
    2.5 с наступает окно, где три опроса подряд (по 0.15 с) дают одно и то же значение. Границы по
    времени широкие (сетка Windows 15.6 мс, тики хоста): точное окно dead-man здесь не пинится.

    НЕ доказывает: окно остановки именно 500 мс (старый тест v1 проверял [0.5, 1.0] с); работу
    ``belt.stop``/``belt.calibrate`` на v2; знак направления (для jog берётся «сдвинулся», не «вырос»)."""
    port = free_port()
    plugin, ctx, _services, workers = make_host(port, protocol="v2", jog_timeout_ms=500, publish_ms=50)
    _start(plugin, ctx)
    try:
        device, _client = client_for(port)
        assert call(plugin, "belt.run", {"freq_hz": 25}).get("ok") is True
        e0 = encoder(device)
        time.sleep(0.5)
        e1 = encoder(device)
        assert e1 > e0, f"belt.run: энкодер не растёт ({e0} -> {e1})"
        assert call(plugin, "belt.status").get("run") is True

        assert call(plugin, "belt.stop").get("ok") is True
        time.sleep(0.3)
        base = encoder(device)

        assert call(plugin, "belt.jog", {"direction": 1, "freq_hz": 10}).get("ok") is True
        time.sleep(0.3)
        assert encoder(device) != base, "belt.jog: энкодер не сдвинулся за 0.3 с"

        stable = [0]
        last = [encoder(device)]

        def _frozen(value: int) -> bool:
            stable[0] = stable[0] + 1 if value == last[0] else 0
            last[0] = value
            return stable[0] >= 3

        assert _poll_encoder_until(device, _frozen, timeout=2.5, interval=0.15), (
            "belt.jog без подкачки: энкодер не остановился за 2.5 с (dead-man jog_timeout_ms не сработал)"
        )
    finally:
        _stop(plugin, ctx, workers)


def test_unknown_protocol_is_error_without_value() -> None:
    """Неизвестный ``protocol`` (``v3``): старт кончается ``state == "error"`` (через
    ``sim_robot.status``), процесс жив (статус отвечает dict), в ответе статуса значение ``v3`` не звучит.

    НЕ доказывает: что значение не эхом в логе/``health`` (смотрится только ответ статуса); что порт
    не занят после неудачного старта."""
    port = free_port()
    plugin, ctx, _services, workers = make_host(port, protocol="v3")
    try:
        run_with_deadline(lambda: plugin.start(ctx), timeout=10.0, label="start")
        status = call(plugin, "sim_robot.status")
        assert isinstance(status, dict)
        assert status.get("state") == "error", f"protocol=v3 принят: {status!r}"
        assert "v3" not in repr(status), f"значение protocol эхом в статусе: {status!r}"
    finally:
        _stop(plugin, ctx, workers)


def _port_is_free(port: int, timeout: float = 3.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            try:
                probe.bind(("127.0.0.1", port))
                return True
            except OSError:
                pass
        time.sleep(0.05)
    return False


def test_restart_after_shutdown_rebinds_port(client_for) -> None:
    """``shutdown()`` освобождает порт (проба ``bind``), повторный ``start()`` на том же порту
    поднимает слушателя заново — карта v2 отвечает снова.

    Фейковый менеджер, как настоящий, возвращает ``False`` на занятое имя воркера, пока его не
    сняли ``remove_worker``: если ``shutdown`` воркеров не снимает, второй ``start`` слушателя не
    получит.

    НЕ доказывает: что состояние ядра при рестарте сброшено (сравнения регистров до/после нет);
    что рестарт переживает открытое клиентское соединение (клиент закрывается до ``shutdown``)."""
    port = free_port()
    plugin, ctx, _services, workers = make_host(port, protocol="v2")
    try:
        _start(plugin, ctx)
        device, _client = client_for(port)
        assert read_reg(device, "TLM_PROTO_VER")[0] == _PROTO_V2_WIRE, "первый старт: карта v2 не отвечает"
        close_client(device)

        run_with_deadline(lambda: plugin.shutdown(ctx), timeout=10.0, label="shutdown")
        assert _port_is_free(port), f"порт {port} не освобождён после shutdown()"

        _start(plugin, ctx)
        device, _client = client_for(port)
        assert read_reg(device, "TLM_PROTO_VER")[0] == _PROTO_V2_WIRE, (
            "второй старт на том же порту: карта v2 не отвечает"
        )
    finally:
        _stop(plugin, ctx, workers)
