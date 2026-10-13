# -*- coding: utf-8 -*-
"""Хост sim v2 под НАСТОЯЩИМ ``WorkerManager`` (ревью кода T2.3 r1, major).

Весь прежний набор v2-хоста (``test_v2_host.py`` и др.) идёт на фейке ``ThreadWorkerManager``
из ``host_harness.py``; project-rules §9 требует хотя бы один тест на настоящих объектах. Контракт
фейка расходится с настоящим менеджером в двух местах, от которых зависит ``_start_v2_workers``:
``is_worker_running`` (у фейка — ``thread.is_alive()``, у настоящего — статус реестра) и
``start_worker`` на живом потоке (фейк — ``False``, настоящий — ``True`` без нового потока).

Основа — одноразовый скрипт ревьюера ``real_wm.py`` (30 циклов, ``bad []``). Литералы проверок:
соединение принято и хост отвечает v2, ``TLM_HB_ROBOT`` растёт за 1.0 с, порт свободен за 5.0 с.

Вторым тестом (ревью инъекций, дыра inj-14) здесь же лежит проверка ``t`` события ``scene.job_done``:
хост v2 обязан заменить время sim ядра на ``time.monotonic()``. Он идёт на фейковом менеджере
воркеров ``make_host`` — менеджер там не предмет проверки.
"""

from __future__ import annotations

import socket
import time

import pytest

from multiprocess_framework.modules.process_module.plugins.base import PluginContext
from multiprocess_framework.modules.process_module.plugins.testing import MockProcessServices
from multiprocess_framework.modules.worker_module.core.worker_manager import WorkerManager
import Plugins.sim.robot_host.plugin as host_module
from Plugins.hub.device_hub.client import DeviceHubClient
from Plugins.sim.robot_host.plugin import SimRobotHostPlugin
from Plugins.sim.robot_host.tests.host_harness import (
    HOST,
    ThreadWorkerManager,
    call,
    close_client,
    encoder,
    free_port,
    make_host,
    open_client,
    read_reg,
    run_with_deadline,
    wait_done_hb,
)
from Services.robot_comm import ROBOT_AVAILABLE
from Services.robot_comm.core.registers import ROBOT_UNIT_ID

pytestmark = [
    pytest.mark.skipif(not ROBOT_AVAILABLE, reason="pymodbus не установлен"),
]

_CYCLES = 3
_PROTO_V2_WIRE = 0x0200  # литерал: protocol_v2.CONSTANTS["PROTO_VER"]
_HB_GROWTH_DEADLINE_S = 1.0
_PORT_FREE_DEADLINE_S = 5.0


def _port_is_free(port: int) -> bool:
    """Проба bind без SO_REUSEADDR: на Windows живой слушатель даёт отказ, свободный порт — успех."""
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.bind((HOST, port))
        return True
    except OSError:
        return False
    finally:
        probe.close()


def _wait_until(predicate, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return bool(predicate())


def test_v2_host_restarts_cleanly_under_real_worker_manager():
    """Три цикла ``start -> shutdown`` v2-хоста на одном порту под настоящим ``WorkerManager``.

    Каждый цикл: (a) TCP-соединение принято и ``TLM_PROTO_VER == 0x0200``; (b) ``TLM_HB_ROBOT``
    растёт за <= 1.0 с (жив тикер, а не только слушатель); (c) после ``shutdown`` порт свободен
    за <= 5.0 с. Блокирующие вызовы — под дедлайном (daemon-поток + join), менеджер и плагин
    гасятся в ``finally``.

    НЕ доказывает: поведение под процессом фреймворка целиком (здесь ``MockProcessServices``, а не
    ``ProcessModule``); ``restart_count`` менеджера и отсутствие утечки потоков после 3 циклов
    (проверено скриптом ревьюера на 30 циклах, в тест не вошло); окно «STOPPED, но поток жив» в
    ``worker_lifecycle`` — оно микросекундное, тест его не воспроизводит."""
    port = free_port()
    services = MockProcessServices(name="robot")
    manager = WorkerManager("robot")
    assert manager.initialize(), "WorkerManager не инициализировался"
    services.worker_manager = manager
    ctx = PluginContext(
        services=services,
        config={"host": HOST, "port": port, "unit_id": ROBOT_UNIT_ID, "auto_start": True, "protocol": "v2"},
    )
    assert ctx.worker_manager is manager, "ctx.worker_manager не настоящий менеджер — тест ничего не доказывает"
    plugin = SimRobotHostPlugin()
    plugin.configure(ctx)
    try:
        for cycle in range(_CYCLES):
            run_with_deadline(lambda: plugin.start(ctx), timeout=15.0, label=f"start#{cycle}")
            status = call(plugin, "sim_robot.status")
            assert status["state"] == "running", f"цикл {cycle}: состояние хоста {status['state']!r}, ждали 'running'"
            try:
                device, client = open_client(port, timeout=3.0)
            except Exception as exc:  # noqa: BLE001 — привязать отказ соединения к номеру цикла
                pytest.fail(f"цикл {cycle}: соединение на порт хоста не принято: {exc!r}")
            try:
                assert read_reg(device, "TLM_PROTO_VER")[0] == _PROTO_V2_WIRE, f"цикл {cycle}: хост не v2"
                hb_start = read_reg(device, "TLM_HB_ROBOT")[0]
                grew = _wait_until(
                    lambda: 0 < (read_reg(device, "TLM_HB_ROBOT")[0] - hb_start) & 0xFFFF < 0x8000,
                    _HB_GROWTH_DEADLINE_S,
                )
                assert grew, f"цикл {cycle}: TLM_HB_ROBOT не растёт за {_HB_GROWTH_DEADLINE_S} с — тикер не жив"
            finally:
                close_client(device)
            run_with_deadline(lambda: plugin.shutdown(ctx), timeout=15.0, label=f"shutdown#{cycle}")
            assert _wait_until(lambda: _port_is_free(port), _PORT_FREE_DEADLINE_S), (
                f"цикл {cycle}: порт {port} не свободен за {_PORT_FREE_DEADLINE_S} с после shutdown"
            )
    finally:
        try:
            run_with_deadline(lambda: plugin.shutdown(ctx), timeout=15.0, label="shutdown-final")
        finally:
            manager.shutdown()


# Место укладки и pick — литералы из test_v2_line_cycle.py (принимаются ядром v2): радиус укладки ~412 мм.
_PLACE_X_MM, _PLACE_Y_MM, _PLACE_RZ_DEG = 400.0, 100.0, 45.0
_PICK_X_MM, _PICK_Y_MM = 300.0, -200.0


def test_scene_job_done_t_is_plugin_monotonic_not_sim_time(monkeypatch):
    """``t`` в ``scene.job_done`` от хоста v2 — ``time.monotonic()`` плагина, а не время sim ядра.

    Ядро v2 даёт ``t`` = секунды sim с запуска ядра (единицы секунд к моменту DONE); хост обязан
    подменить его (DESIGN T2.4 п.4), иначе сцена сравнит с ``time.monotonic()`` несопоставимые числа.
    Проверки: ``abs(t - time.monotonic()) < 5.0`` и ``t >= t_до_старта`` (монотонные часы взяты
    ДО ``plugin.start``; время sim с запуска ядра заведомо меньше возраста монотонных часов процесса).
    Блокирующие вызовы — под дедлайном, плагин гасится в ``finally``.

    НЕ доказывает: что событие доходит до настоящей сцены (подменён ``send_fire_and_forget``);
    поведение под настоящим ``WorkerManager`` (фейковый менеджер); корректность остальных полей
    события — их проверяет ``test_v2_line_cycle.py``."""
    sent: list[dict] = []

    def _fake_send(self, command, args=None):
        sent.append({"command": command, "args": dict(args)})
        return True

    monkeypatch.setattr(DeviceHubClient, "send_fire_and_forget", _fake_send)
    port = free_port()
    plugin, ctx, _services, workers = make_host(port, protocol="v2", scene_process="camera")
    device = None
    try:
        t_before_start = time.monotonic()
        run_with_deadline(lambda: plugin.start(ctx), timeout=10.0, label="start")
        device, client = open_client(port)
        assert read_reg(device, "TLM_PROTO_VER")[0] == _PROTO_V2_WIRE, "хост не v2 — тест бессмыслен"
        ecap = encoder(device)
        run_with_deadline(lambda: client.servo(True), timeout=5.0, label="servo")
        run_with_deadline(client.kick_heartbeat, timeout=5.0, label="hb")
        job = run_with_deadline(
            lambda: client.cvt_job(
                ecap,
                _PICK_X_MM,
                _PICK_Y_MM,
                0.0,  # pick_z
                0,  # flags
                _PLACE_X_MM,
                _PLACE_Y_MM,
                0.0,  # place_z
                _PLACE_RZ_DEG,
            ),
            timeout=5.0,
            label="cvt_job",
        )
        wait_done_hb(client, job.seq)
        assert _wait_until(lambda: bool(sent), 5.0), "scene.job_done не отправлен за 5.0 с"
        t_after = time.monotonic()
        assert len(sent) == 1, f"ожидалось одно scene.job_done, отправлено {sent!r}"
        assert sent[0]["command"] == "scene.job_done"
        event_t = sent[0]["args"]["t"]
        assert abs(event_t - t_after) < 5.0, f"t={event_t!r} далеко от time.monotonic()={t_after!r}"
        assert event_t >= t_before_start, (
            f"t={event_t!r} меньше монотонных часов до старта {t_before_start!r}: время sim"
        )
    finally:
        if device is not None:
            close_client(device)
        try:
            run_with_deadline(lambda: plugin.shutdown(ctx), timeout=10.0, label="shutdown")
        finally:
            workers.stop_all()


class _TickerNeverStartsManager(ThreadWorkerManager):
    """Фейковый менеджер, у которого воркер тика «создаётся», но поток не заводится
    (как окно «статус STOPPED, поток жив» настоящего менеджера: ``start_worker`` вернул ``True``
    без нового потока)."""

    def create_worker(self, worker_name, target, config=None, auto_start=False):
        if worker_name == "sim_robot_ticker":
            return True
        return super().create_worker(worker_name, target, config, auto_start)

    def start_worker(self, worker_name):
        if worker_name == "sim_robot_ticker":
            return True
        return super().start_worker(worker_name)


def test_start_fails_when_ticker_worker_never_runs(monkeypatch):
    """Тикер не запущен, а слушатель поднят: старт обязан кончиться ``state == "error"``, порт отпущен.

    Ревью T2.3 r1 (nit): без ожидания живого тикера старт был бы «успешным» — слушатель на месте,
    mailbox молчит. Ожидание сокращено до 0.3 с подменой ``_V2_TICKER_TIMEOUT_S`` (в продукте 5.0 с).

    НЕ доказывает: поведение настоящего ``WorkerManager`` в окне «STOPPED, но поток жив» (микросекунды,
    не воспроизводится); текст причины в health."""
    monkeypatch.setattr(host_module, "_V2_TICKER_TIMEOUT_S", 0.3)
    port = free_port()
    broken = _TickerNeverStartsManager()
    services = MockProcessServices(name="robot")
    services.worker_manager = broken
    ctx = PluginContext(
        services=services,
        config={"host": HOST, "port": port, "unit_id": ROBOT_UNIT_ID, "auto_start": True, "protocol": "v2"},
    )
    assert ctx.worker_manager is broken, "ctx.worker_manager не наш менеджер"
    plugin = SimRobotHostPlugin()
    plugin.configure(ctx)
    try:
        run_with_deadline(lambda: plugin.start(ctx), timeout=15.0, label="start")
        assert call(plugin, "sim_robot.status")["state"] == "error", "тикера нет, а хост считает старт успешным"
        assert _wait_until(lambda: _port_is_free(port), _PORT_FREE_DEADLINE_S), (
            f"порт {port} не отпущен после отказа старта"
        )
    finally:
        try:
            run_with_deadline(lambda: plugin.shutdown(ctx), timeout=15.0, label="shutdown")
        finally:
            broken.stop_all()
