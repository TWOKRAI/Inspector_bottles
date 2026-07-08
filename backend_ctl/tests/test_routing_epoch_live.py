# -*- coding: utf-8 -*-
"""Live-тест Ф3.1 routing-epoch (acceptance): peer→peer доставка после switch/restart.

Дыра (docstring ``_cmd_process_relay``): выживший процесс держит стейл-ссылку на
очередь соседа, которую PM пересоздал при switch/restart. ``put_nowait`` в
осиротевшую очередь возвращает успех → **тихая потеря**. Тест воспроизводит это
через синтетический ``routing.probe`` (peer→peer send нормальным путём) и наблюдает
downstream-эффект — health-дельту у соседа в state-дереве.

Отправитель — ``devices`` (protected DeviceHubPlugin из base.yaml): при full-replace
switch (FullReplacePlanner пересоздаёт ВСЕ non-protected) выживают только protected,
а ``gui`` в headless вырезан (strip_gui) — поэтому единственный наблюдаемый выживший
ребёнок-отправитель это ``devices``. (План называл ``camera_0``, но он non-protected →
пересоздаётся на switch и не является выжившим; смысл теста — «выживший → пересозданный
сосед» — сохранён.)

Собственный порт ≥8770 (изоляция от общих фикстур: ловушка «двух бэкендов»).
"""

from __future__ import annotations

import time

import pytest

from backend_ctl.harness import BackendHarness

_SENDER = "devices"       # protected → выживает full-replace switch и restart соседа
_PEER = "preprocessor"    # non-protected → пересоздаётся на switch/restart
# По СВОЕМУ бэкенду на каждый тест (изоляция): switch необратимо роняет очередь
# соседа у devices (тот навсегда доставляет через relay), поэтому restart-тест
# обязан стартовать с чистого бэкенда, иначе relayed_to_hub-проба ложно растёт.
_PORT_SWITCH = 8778       # уникальные порты (≥8770)
_PORT_RESTART = 8779


def _result(res: dict) -> dict:
    """Развернуть result-конверт ответа (см. test_health_live._result)."""
    if isinstance(res, dict) and isinstance(res.get("result"), dict):
        return res["result"]
    return res if isinstance(res, dict) else {}


@pytest.fixture(scope="module")
def switch_backend():
    """Свой headless-бэкенд для switch-теста (base.yaml → devices)."""
    harness = BackendHarness(with_base=True, port=_PORT_SWITCH)
    drv = harness.start()
    try:
        yield drv
    finally:
        harness.stop()


@pytest.fixture(scope="module")
def restart_backend():
    """Свой headless-бэкенд для restart-теста (изоляция от switch)."""
    harness = BackendHarness(with_base=True, port=_PORT_RESTART)
    drv = harness.start()
    try:
        yield drv
    finally:
        harness.stop()


def _probe(drv, sender: str, peer: str, tag: str) -> dict:
    """Отправить routing.probe sender→peer с inner=health.report (метка tag)."""
    inner = {
        "type": "command",
        "command": "health.report",
        "data": {"context": "routing-probe", "message": f"probe:{tag}"},
    }
    return _result(drv.send_command(sender, "routing.probe", {"target": peer, "inner": inner}, timeout=5.0))


def _wait_health_errors(drv, peer: str, deadline: float, *, min_errors: int = 1):
    """Дождаться дельты processes.<peer>.health.errors >= min_errors (или None)."""
    path = f"processes.{peer}.health.errors"
    latest = None
    while time.time() < deadline:
        for e in drv.events(timeout=2.0):
            if e.get("command") != "state.changed":
                continue
            for d in (e.get("data") or {}).get("deltas", []) or []:
                if d.get("path") == path:
                    latest = d.get("new_value")
        if isinstance(latest, int) and latest >= min_errors:
            return latest
    return latest


def _relayed_to_hub(drv, proc: str) -> int:
    """Счётчик relayed_to_hub из introspect.router_stats процесса (0, если нет)."""
    res = drv.introspect_router_stats(proc, timeout=5.0)
    node = res
    for _ in range(4):
        if isinstance(node, dict) and "router_stats" in node:
            return int((node.get("router_stats") or {}).get("relayed_to_hub", 0) or 0)
        node = node.get("result") if isinstance(node, dict) else None
    return 0


@pytest.mark.harness_smoke
def test_peer_send_after_switch_delivered(switch_backend) -> None:
    """peer→peer send выжившего процесса после switch доставляется (acceptance A)."""
    drv = switch_backend

    sub = _result(drv.state_subscribe(f"processes.{_PEER}.**", timeout=8.0))
    assert sub.get("status") == "ok", f"state.subscribe не ok: {sub}"
    drv.events()  # осушить накопленное

    # Baseline: probe до switch доставляется (свежие очереди).
    _probe(drv, _SENDER, _PEER, "baseline")
    baseline = _wait_health_errors(drv, _PEER, time.time() + 20.0)
    assert baseline and baseline >= 1, f"baseline probe {_SENDER}→{_PEER} не доставлен: {baseline}"

    # Switch: full-replace pipeline (preprocessor пересоздан; devices — protected — выживает).
    from multiprocess_prototype.backend.launch import load_topology_dict
    from multiprocess_prototype.main import DEFAULT_BLUEPRINT

    bp = load_topology_dict(DEFAULT_BLUEPRINT)
    applied = _result(
        drv.send_command("ProcessManager", "topology.apply", {"topology_dict": bp}, timeout=30.0)
    )
    assert applied.get("success") is True, f"topology.apply не success: {applied}"

    time.sleep(3.0)  # дать новому preprocessor подняться + первый heartbeat
    drv.events()     # осушить републикацию нового процесса (health.errors=0)

    # Post-switch probe: на main теряется (devices держит стейл-очередь старого peer'а).
    _probe(drv, _SENDER, _PEER, "post-switch")
    errors = _wait_health_errors(drv, _PEER, time.time() + 20.0)
    assert errors and errors >= 1, (
        f"probe {_SENDER}→{_PEER} после switch НЕ доставлен (стейл-очередь): {errors}"
    )


@pytest.mark.harness_smoke
def test_peer_send_after_restart_delivered(restart_backend) -> None:
    """peer→peer send после restart соседа доставлен И relayed_to_hub==0 (acceptance B)."""
    drv = restart_backend

    sub = _result(drv.state_subscribe(f"processes.{_PEER}.**", timeout=8.0))
    assert sub.get("status") == "ok", f"state.subscribe не ok: {sub}"
    drv.events()

    _probe(drv, _SENDER, _PEER, "baseline-restart")
    baseline = _wait_health_errors(drv, _PEER, time.time() + 20.0)
    assert baseline and baseline >= 1, f"baseline probe {_SENDER}→{_PEER} не доставлен: {baseline}"

    # Restart одного процесса: peer пересоздан, devices выживает.
    r = _result(
        drv.send_command("ProcessManager", "process.restart", {"process_name": _PEER}, timeout=30.0)
    )
    assert r.get("success") is True, f"process.restart не success: {r}"
    time.sleep(3.0)
    drv.events()

    relayed_before = _relayed_to_hub(drv, _SENDER)

    _probe(drv, _SENDER, _PEER, "post-restart")
    errors = _wait_health_errors(drv, _PEER, time.time() + 20.0)
    assert errors and errors >= 1, (
        f"probe {_SENDER}→{_PEER} после restart НЕ доставлен (стейл-очередь): {errors}"
    )

    # Доказательство B: доставка ПРЯМАЯ (переиспользованная очередь), не через relay.
    relayed_after = _relayed_to_hub(drv, _SENDER)
    assert relayed_after == relayed_before, (
        f"доставка после restart шла через hub-relay (ожидалась прямая): "
        f"relayed_to_hub {relayed_before}→{relayed_after}"
    )
