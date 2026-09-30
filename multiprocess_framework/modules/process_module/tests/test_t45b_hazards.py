# -*- coding: utf-8 -*-
"""Task 4.5b — hazard-тесты автора: то, что видно только из устройства механизма.

Приёмку по контракту пишет независимый tester (``test_t45b_process_fields.py``); здесь три
места, где механизм может сломаться тихо:

  * раннер общий для потоков producer и executor -> EMA под замком, оба ключа выживают;
  * опрос (``current_levels_snapshot``) не должен сдвигать окно дельты CPU, иначе
    «push ⊆ poll» превращается в «опрос съел окно тика»;
  * связка с НАСТОЯЩИМ ``PluginRunner`` (не заглушкой) — имя плагина доезжает до дерева.

Всё, что может зависнуть, идёт в daemon-потоке с join-дедлайном.
"""

from __future__ import annotations

import threading
import time

from multiprocess_framework.modules.process_module.generic.plugin_runner import PluginRunner
from multiprocess_framework.modules.process_module.heartbeat.process_heartbeat import ProcessHeartbeat


class _Plugin:
    enabled = True
    inputs: list = []
    outputs: list = []

    def __init__(self, name: str, delay: float = 0.0) -> None:
        self.name = name
        self._delay = delay

    def process(self, items: list[dict]) -> list[dict]:
        if self._delay:
            time.sleep(self._delay)
        return items


class _Proxy:
    def __init__(self) -> None:
        self.merged: list[tuple[str, dict]] = []

    def set(self, path: str, value: object) -> None: ...

    def merge(self, path: str, data: dict) -> None:
        self.merged.append((path, data))


class _Services:
    def __init__(self, proxy: _Proxy, plugin_runner: object = None) -> None:
        self._state_proxy = proxy
        self.router_manager = None
        self.name = "proc"
        self._health_state = None
        self.plugin_runner = plugin_runner

    def get_config(self, key: str, default=None):
        return default

    def log_info(self, *a, **k) -> None: ...
    def log_debug(self, *a, **k) -> None: ...
    def log_warning(self, *a, **k) -> None: ...


def _burn(seconds: float) -> None:
    deadline = time.perf_counter() + seconds
    x = 0
    while time.perf_counter() < deadline:
        x += 1


def test_t45b_hazard_two_threads_two_plugins_both_keys_survive() -> None:
    """Два потока на ОДНОМ раннере (producer + executor) по 500 вызовов на разных плагинах."""
    runner = PluginRunner(validate_ports=False)
    errors: list[BaseException] = []

    def _work(plugin: _Plugin) -> None:
        try:
            for _ in range(500):
                runner.call_process(plugin, [{"i": 1}])
        except BaseException as exc:  # noqa: BLE001 — тест ловит всё, чтобы поток не умер молча
            errors.append(exc)

    threads = [
        threading.Thread(target=_work, args=(_Plugin("alpha"),), daemon=True),
        threading.Thread(target=_work, args=(_Plugin("beta"),), daemon=True),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30.0)
    assert not any(t.is_alive() for t in threads), "поток раннера завис"
    assert errors == []
    assert set(runner.plugin_ms()) == {"alpha", "beta"}


def test_t45b_hazard_levels_snapshot_does_not_advance_cpu_window() -> None:
    """Два опроса между тиками не сдвигают дельту: следующий тик видит ВСЮ нагрузку окна.

    Если бы снимок звал ``sample()``, окно сбросилось бы на опросе, и тик 2 измерил бы
    только хвост после него. Хвост обязан быть ПРОСТОЕМ (``sleep``): сразу после опроса
    меряющий поток сам занят, и крошечное окно давало ~1 ядро — первая редакция теста
    стояла без простоя и выживала под инъекцией «опрос зовёт sample()» (инъекция лида
    B6, 2026-09-30). С простоем: честно ≈ 0.5 ядра (0.3 с нагрузки / 0.6 с окна),
    со сдвинутым окном ≈ 0.
    """
    proxy = _Proxy()
    hb = ProcessHeartbeat(_Services(proxy))
    hb._publish_telemetry_to_tree({}, None)  # тик 1: праймит окно, cpu ещё нет
    _burn(0.3)
    snap1 = hb.current_levels_snapshot()
    snap2 = hb.current_levels_snapshot()
    assert snap1 is None or "cpu" not in snap1.get("state", {}), "до второго тика показания нет"
    assert snap2 is None or "cpu" not in snap2.get("state", {})
    time.sleep(0.3)  # простой: окно, сдвинутое опросом, видело бы только его
    hb._publish_telemetry_to_tree({}, None)  # тик 2
    cores = proxy.merged[-1][1]["state"]["cpu"]["cores"]
    assert 0.3 < cores < 0.75, f"опрос съел окно тика или окно посчитано не так: cores={cores}"
    # и после тика опрос отдаёт ровно то же число (push ⊆ poll), не пересчитывая его
    assert hb.current_levels_snapshot()["state"]["cpu"] == {"cores": cores}


def test_t45b_hazard_real_runner_wired_into_heartbeat_publish() -> None:
    """НАСТОЯЩИЙ PluginRunner в сервисах: имя плагина и округление до 1 знака доезжают до дерева."""
    runner = PluginRunner(validate_ports=False)
    plugin = _Plugin("detector", delay=0.01)
    for _ in range(5):
        runner.call_process(plugin, [{"i": 1}])
    proxy = _Proxy()
    hb = ProcessHeartbeat(_Services(proxy, plugin_runner=runner))
    hb._publish_telemetry_to_tree({}, None)
    published = proxy.merged[-1][1]["state"]["plugin_ms"]
    assert set(published) == {"detector"}
    assert 9.0 <= published["detector"] <= 15.0
    assert round(published["detector"], 1) == published["detector"]
    assert hb.current_levels_snapshot()["state"]["plugin_ms"] == published
