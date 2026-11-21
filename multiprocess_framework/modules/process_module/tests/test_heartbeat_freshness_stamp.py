# -*- coding: utf-8 -*-
"""Task 0.9 — метка свежести ``_fresh`` в каждом слиянии телеметрии heartbeat; исход публикации (M-7).

Писатель (``ProcessHeartbeat._publish_telemetry_to_tree``) кладёт в ``data`` последним
ключом метку ``{"seq", "src_ts", "incarnation", "tick_sec"}`` на КОРЕНЬ записи процесса
(``processes.<name>._fresh``, рядом с ``state`` и ``workers``). Контракт формы метки и
читателей — Task 0.2 (``state_store_module/tests/test_contract_freshness.py``); здесь
доказывается только то, что ПИСАТЕЛЬ метку кладёт.

M-7: отказы ПУБЛИКАЦИИ в дерево (``proxy.merge``, ``proxy.delete``, публикация health)
считаются атрибутом ``telemetry_publish_failed`` БЕЗУСЛОВНО и звучат одним WARNING на
окно голоса; счётчик виден в ответе ``introspect.telemetry``.

Часы: ``time.time_ns()`` на Windows ходит сеткой ~15.6 мс, поэтому между двумя
сравниваемыми воплощениями тест ждёт СМЕНЫ часов занятым циклом (с дедлайном), а не
``sleep``. Ожидаемые значения — литералы, не выведенные из кода писателя.
"""

from __future__ import annotations

import copy
import logging
import os
import time
from typing import Any

import pytest

from multiprocess_framework.modules.process_module.plugins.base import PluginContext
from multiprocess_framework.modules.state_store_module.manager.state_store_manager import StateStoreManager
from multiprocess_framework.modules.state_store_module.middleware.throttle import ThrottleMiddleware
from multiprocess_framework.modules.state_store_module.proxy.state_proxy import StateProxy

from .test_plugin_levels_hazards import _boot, _Proxy, _Services, _poll, _tick_levels


def _workers(hz: float = 8.0, lat: float = 3.0, age: float = 0.1, *, status: bool = True) -> dict:
    """Снимок одного отработавшего воркера: даёт ``workers.w.*`` и ``state.fps``/``latency_ms``."""
    worker: dict[str, Any] = {"effective_hz": hz, "cycle_duration_ms": lat, "last_cycle_age_s": age}
    if status:
        worker["status"] = "running"
    return {"w": worker}


class _Recorder(_Proxy):
    """Дерево-двойник, чей журнал ``merges`` хранит нетронутый снимок каждого слияния.

    Базовый ``_Proxy`` кладёт во вложенный узел дерева ТОТ ЖЕ dict, что лежит в журнале
    (``node[last] = value``), и следующее слияние правит его на месте: метка первого такта в
    журнале задним числом получила бы ``seq`` второго. Это артефакт двойника, а не писателя.
    """

    def merge(self, path: str, data: dict) -> None:
        super().merge(path, copy.deepcopy(data))
        self.merges[-1] = (path, copy.deepcopy(data))


def _boot_cam() -> tuple[_Services, Any]:
    services, hb = _boot(name="cam")
    services._state_proxy = _Recorder()
    return services, hb


def _wait_clock_change() -> None:
    """Дождаться смены ``time.time_ns()`` занятым циклом (без sleep), дедлайн 2 с.

    Зачем: воплощение строится из ``time.time_ns()``, и на грубой сетке часов два
    создания подряд читают одно значение. Тест, сравнивающий воплощения, ждёт смены
    сам, а не надеется на разрешение часов.
    """
    start = time.time_ns()
    deadline = time.monotonic() + 2.0
    while time.time_ns() == start:
        if time.monotonic() > deadline:
            pytest.fail("time.time_ns() не сменился за 2 с — сравнение воплощений невозможно")


def _marks(services: _Services) -> list[dict]:
    """Метки всех слияний, ушедших в прокси за прогон, по порядку."""
    return [data["_fresh"] for _path, data in services._state_proxy.merges]


# --------------------------------------------------------------------------- #
# Форма метки в слиянии
# --------------------------------------------------------------------------- #
def test_merge_carries_stamp_keys() -> None:
    """Одно слияние на ``processes.cam``; метка на корне записи, последним ключом ``data``."""
    services, hb = _boot_cam()
    before = time.time()
    hb._publish_telemetry_to_tree(_workers(), None)
    after = time.time()

    assert len(services._state_proxy.merges) == 1
    path, data = services._state_proxy.merges[0]
    assert path == "processes.cam"
    assert set(data) == {"workers", "state", "_fresh"}
    assert list(data)[-1] == "_fresh", f"метка не последняя в data: {list(data)}"
    assert "_fresh" not in data["state"], "метка легла внутрь state, а не на корень записи"

    mark = data["_fresh"]
    assert set(mark) == {"seq", "src_ts", "incarnation", "tick_sec"}
    assert mark["seq"] == 1
    assert before <= mark["src_ts"] <= after, (before, mark["src_ts"], after)  # time.time(), не monotonic
    assert mark["tick_sec"] == 5.0
    assert isinstance(mark["incarnation"], str)
    assert mark["incarnation"].split(":")[0] == str(os.getpid())


# --------------------------------------------------------------------------- #
# Номер такта и воплощение
# --------------------------------------------------------------------------- #
def test_seq_increments_per_tick() -> None:
    """Один экземпляр: ``seq`` 1, 2, 3 и ОДНО воплощение; пустой такт номер не двигает и не публикует."""
    services, hb = _boot_cam()

    hb._publish_telemetry_to_tree(_workers(), None)
    _wait_clock_change()  # воплощение, пересчитанное на такте, отличилось бы от первого
    hb._publish_telemetry_to_tree(_workers(), None)
    assert [m["seq"] for m in _marks(services)] == [1, 2]
    assert _marks(services)[0]["incarnation"] == _marks(services)[1]["incarnation"]

    # Пустой такт: гейт закрыт наглухо, воркеров нет, уровней нет -> нечего слать, метка тоже не уходит.
    hb._publish_telemetry_to_tree({}, set())
    assert len(services._state_proxy.merges) == 2, "пустой такт опубликовал слияние (одну метку)"

    hb._publish_telemetry_to_tree(_workers(), None)
    assert [m["seq"] for m in _marks(services)] == [1, 2, 3], "пустой такт продвинул seq"


def test_new_process_new_incarnation() -> None:
    """Новый ``ProcessHeartbeat`` (рестарт процесса) -> другое воплощение и ``seq`` с единицы."""
    first_services, first = _boot_cam()
    first._publish_telemetry_to_tree(_workers(), None)
    first._publish_telemetry_to_tree(_workers(), None)
    _wait_clock_change()
    second_services, second = _boot_cam()
    second._publish_telemetry_to_tree(_workers(), None)

    old = _marks(first_services)[-1]
    new = _marks(second_services)[-1]
    assert old["incarnation"] != new["incarnation"], old["incarnation"]
    assert (old["seq"], new["seq"]) == (2, 1)


def test_tick_sec_follows_the_interval() -> None:
    """``tick_sec`` метки — действующий такт воркера, а не константа 5.0."""
    services, hb = _boot_cam()
    hb._interval = 5.0
    hb._publish_telemetry_to_tree(_workers(), None)
    assert _marks(services)[-1]["tick_sec"] == 5.0

    hb._interval = 2.5
    hb._publish_telemetry_to_tree(_workers(), None)
    assert _marks(services)[-1]["tick_sec"] == 2.5

    # Контракт ``telemetry.publish.tick_sec`` короче интервала heartbeat -> действует он.
    hb._interval = 5.0
    hb.reconfigure_telemetry({"tick_sec": 2.0})
    hb._publish_telemetry_to_tree(_workers(), None)
    assert _marks(services)[-1]["tick_sec"] == 2.0


# --------------------------------------------------------------------------- #
# Метка и троттл центрального хранилища (без IPC)
# --------------------------------------------------------------------------- #
class _SentRouter:
    """Роутер без IPC: сообщение ``StateProxy`` складывается в список."""

    def __init__(self) -> None:
        self.sent: list[dict] = []

    def send_async(self, msg: dict, priority: str = "normal") -> None:
        self.sent.append(msg)


def _wire(rules: dict[str, float]) -> tuple[_SentRouter, Any, Any, StateStoreManager]:
    """Heartbeat -> реальный ``StateProxy`` -> список сообщений -> реальный ``StateStoreManager`` с троттлом.

    Часы троттла замёрзли на 1000.0: оба слияния попадают в одно окно в 60 с.
    """
    router = _SentRouter()
    services, hb = _boot_cam()
    services._state_proxy = StateProxy("cam", router=router)
    manager = StateStoreManager(router=None, auto_register_ipc=False)
    manager.use(ThrottleMiddleware(rules, clock=lambda: 1000.0))
    return router, services, hb, manager


def test_throttle_passes_stamp_and_holds_value() -> None:
    """Троттл судит слияние по листьям: метка (листья ``_fresh.*`` без правила) проходит всегда, значение держится."""
    # (а) Правила покрывают ВСЕ листья настоящего тика, кроме метки. Без метки второе слияние отклонено целиком.
    router, services, hb, manager = _wire({"processes.**.state.**": 60.0, "processes.**.workers.**": 60.0})
    hb._publish_telemetry_to_tree(_workers(hz=8.0, lat=3.0, age=0.1), None)
    hb._publish_telemetry_to_tree(_workers(hz=9.0, lat=4.0, age=0.2), None)
    first, second = router.sent
    assert manager.handle_state_merge(first)["status"] == "ok"

    stampless = copy.deepcopy(second)  # те же листья тика, метка удалена
    del stampless["data"]["data"]["_fresh"]
    assert manager.handle_state_merge(second)["status"] == "ok", "слияние с меткой отклонено троттлом"
    tree = manager.store.get_subtree("processes.cam")
    assert tree["_fresh"]["seq"] == 2
    assert tree["state"]["fps"] == 8.0, "значение первого слияния должно держаться в окне троттла"
    # Контроль: то же слияние БЕЗ метки троттл отклоняет целиком; значит пропускает его именно метка.
    rejected = manager.handle_state_merge(stampless)
    assert (rejected["status"], rejected["reason"]) == ("rejected", "throttled")

    # (б) Смешанное слияние: лист без правила (``workers.w.effective_hz``) идёт, ``state.fps`` держится.
    router, services, hb, manager = _wire({"processes.**.state.fps": 60.0})
    hb._publish_telemetry_to_tree(_workers(hz=8.0, age=0.1), None)
    hb._publish_telemetry_to_tree(_workers(hz=9.0, age=0.2), None)
    first, second = router.sent
    assert manager.handle_state_merge(first)["status"] == "ok"
    assert manager.handle_state_merge(second)["status"] == "ok"
    tree = manager.store.get_subtree("processes.cam")
    assert tree["_fresh"]["seq"] == 2
    assert tree["workers"]["w"]["effective_hz"] == 9.0
    assert tree["state"]["fps"] == 8.0


# --------------------------------------------------------------------------- #
# M-7: исход публикации
# --------------------------------------------------------------------------- #
class _MergeRaises(_Proxy):
    def merge(self, path: str, data: dict) -> None:
        raise RuntimeError("секрет-текст-исключения")


class _DeleteRaises(_Proxy):
    def delete(self, path: str) -> bool:
        raise RuntimeError("секрет-текст-исключения")


class _PollRaises:
    """Состояние здоровья, чья публикация падает (``poll`` зовётся внутри того же ``try``)."""

    def poll(self) -> None:
        raise RuntimeError("секрет-текст-исключения")


@pytest.mark.parametrize("place", ["merge", "delete", "health"])
def test_publish_failure_counted(place: str) -> None:
    """Каждое из трёх мест отказа публикации считается и видно в ответе ``introspect.telemetry``; такт не падает."""
    services, hb = _boot_cam()
    assert hb.telemetry_publish_failed == 0

    if place == "merge":
        services._state_proxy = _MergeRaises()
        hb._publish_telemetry_to_tree(_workers(), None)
    elif place == "delete":
        services._state_proxy = _DeleteRaises()
        writer = PluginContext(services=services, config={}, plugin_name="dying")
        writer.publish_metric("fps", 1.0)
        _tick_levels(hb)  # уровень уехал в дерево, отказов нет
        assert hb.telemetry_publish_failed == 0
        writer._retract_metrics()
        _tick_levels(hb)  # снятие утверждается -> delete бросает
    else:
        services._health_state = _PollRaises()
        hb._publish_health_to_tree()

    assert hb.telemetry_publish_failed == 1
    assert _poll(services)["telemetry_publish_failed"] == 1


def test_publish_failure_voice_is_windowed(caplog: pytest.LogCaptureFixture) -> None:
    """Два отказа подряд: счётчик 2, а WARNING ровно ОДИН; в строке имя класса исключения, не его текст."""
    services, hb = _boot_cam()
    services._state_proxy = _MergeRaises()

    with caplog.at_level(logging.WARNING):
        hb._publish_telemetry_to_tree(_workers(), None)
        hb._publish_telemetry_to_tree(_workers(), None)

    assert hb.telemetry_publish_failed == 2
    lines = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert len(lines) == 1, lines
    assert "RuntimeError" in lines[0]
    assert "секрет-текст-исключения" not in lines[0]
