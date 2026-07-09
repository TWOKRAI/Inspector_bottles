# -*- coding: utf-8 -*-
"""Live-тест Ф4.2 fencing-token (acceptance): после замены инстанса старый процесс
физически НЕ вкидывает сообщение в новую топологию.

Требование владельца (2026-07-08): у каждого процесса свой incarnation; при замене
(пересоздание очередей — switch/restart-no-reuse) старый инстанс не должен слать
данные в новую топологию. Механизм (ADR-PMM-014, ADR-MSG-009): каждый control-plane
билет штампуется `_fence={sender, inc, epoch}` (send-mw), а на приёме fence-фильтр
дропает билет, чей `inc` меньше известного получателю текущего incarnation отправителя
(`PSR[sender].routing_incarnation`).

**Почему live, а не unit (урок Ф3.7).** Юнит доказывает логику фильтра, но НЕ то, что
штамп реально несёт incarnation инстанса и что стейл действительно летит после замены.
Здесь бэкенд поднимается целиком: `restart` с пересозданием очередей (`restart_reuse_
queues=false`) бампит incarnation процесса (`_bump_incarnation` + broadcast refresh
соседям), а УМИРАЮЩИЙ старый инстанс в окне teardown ещё шлёт heartbeat/state.set со
СТАРЫМ incarnation. Получатель (ProcessManager, уже знающий новый incarnation) их
дропает → `fence_dropped` растёт. Именно live-прогон выявил, что глобальный epoch-
критерий ложно дропает легитимный state/telemetry текущих процессов в переходном окне
(routing_epoch_live краснел) — ключом дропа сделан per-sender incarnation.

**Почему restart-no-reuse, а не reuse.** Дефолтный restart переиспользует очереди
(incarnation НЕ меняется) — сообщения старого инстанса летят в ту же очередь, что
читает новый, и НЕ являются «чужой топологией»: fence их корректно НЕ трогает. Замена
инстанса = пересоздание очередей → новый incarnation → вот тогда стейл отбрасывается.

Собственные порты ≥8790 (изоляция от общих фикстур: ловушка «двух бэкендов»).
"""
from __future__ import annotations

import os
import time
from contextlib import contextmanager

import pytest

import backend_ctl.harness as _harness_mod
from backend_ctl.harness import BackendHarness

_PORT_GREEN = 8790
_PORT_RED = 8791
_PEER = "preprocessor"  # non-protected → restart пересоздаёт, старый инстанс шлёт стейл


def _router_node(drv, proc: str) -> dict:
    node = drv.introspect_router_stats(proc, timeout=6.0)
    for _ in range(4):
        if isinstance(node, dict) and "router_stats" in node:
            return node
        node = node.get("result") if isinstance(node, dict) else None
    return node if isinstance(node, dict) else {}


def _fence_dropped(drv, proc: str) -> int:
    return int((_router_node(drv, proc).get("router_stats") or {}).get("fence_dropped", 0) or 0)


def _poll_fence_dropped(drv, proc: str, deadline: float) -> int:
    best = 0
    while time.time() < deadline:
        best = max(best, _fence_dropped(drv, proc))
        if best >= 1:
            return best
        time.sleep(0.5)
    return best


@contextmanager
def _backend(port: int, *, fence: str | None, monkeypatch):
    """Headless-бэкенд с restart_reuse_queues=false (замена → bump incarnation) и
    заданным FW_FENCE (env читается детьми при spawn)."""
    if fence is None:
        monkeypatch.delenv("FW_FENCE", raising=False)
    else:
        monkeypatch.setenv("FW_FENCE", fence)

    # Внедрить restart_reuse_queues=false в конфиг оркестратора (мутабельный dict,
    # читается при start()) — так restart пересоздаёт очереди и бампит incarnation.
    orig_build = _harness_mod.build_headless_launcher

    def _build_no_reuse(**kw):
        launcher = orig_build(**kw)
        launcher._orchestrator_config["restart_reuse_queues"] = False
        return launcher

    monkeypatch.setattr(_harness_mod, "build_headless_launcher", _build_no_reuse)

    harness = BackendHarness(with_base=True, port=port)
    try:
        yield harness.start()
    finally:
        harness.stop()


def _restart_peer(drv) -> None:
    res = drv.send_command("ProcessManager", "process.restart", {"process_name": _PEER}, timeout=30.0)
    assert isinstance(res, dict), f"process.restart вернул не dict: {res!r}"


@pytest.mark.harness_smoke
def test_stale_dropped_after_instance_replace_green(monkeypatch) -> None:
    """GREEN (fence on): замена инстанса соседа → старый инстанс шлёт стейл
    (inc<known) → ProcessManager дропает, fence_dropped растёт (гарантия владельца)."""
    with _backend(_PORT_GREEN, fence=None, monkeypatch=monkeypatch) as drv:
        assert _fence_dropped(drv, "ProcessManager") == 0, "на старте дропов быть не должно"

        _restart_peer(drv)
        dropped = _poll_fence_dropped(drv, "ProcessManager", time.time() + 15.0)

        assert dropped >= 1, (
            f"стейл от старого инстанса '{_PEER}' НЕ отброшен после замены "
            f"(fence_dropped={dropped}) — fencing не сработал live"
        )


@pytest.mark.harness_smoke
def test_stale_passes_without_fence_red(monkeypatch) -> None:
    """RED (FW_FENCE=0): та же замена — стейл от старого инстанса проходит,
    fence_dropped остаётся 0 (доказывает, что дропает именно fence, а не иной guard)."""
    with _backend(_PORT_RED, fence="0", monkeypatch=monkeypatch) as drv:
        _restart_peer(drv)
        time.sleep(6.0)  # столько же, сколько окно GREEN — честное отсутствие дропов
        dropped = _fence_dropped(drv, "ProcessManager")
        assert dropped == 0, (
            f"при FW_FENCE=0 стейл не должен дропаться fence-фильтром, но fence_dropped={dropped}"
        )
