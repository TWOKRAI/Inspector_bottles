# -*- coding: utf-8 -*-
"""Live-тест Ф3.5 (wire-статусы first-class): honest broken_wires + re-issue.

Acceptance Ф3.5: разрыв провода → ``system.health.broken_wires ≠ 0`` в момент
разрыва; после восстановления → снова 0.

**A vs B (см. plans/.../f3.5-wire-status.md §Контекст + DECISIONS.md ADR-PM-Ф3.5):**
в headless-рецепте wire.* абстракция (путь B) НЕ заводится — ``connect_wire`` только
в GUI. Живой поток кадров несёт generic data-path (путь A), который самовосстанавливается
через routing-epoch Ф3.1 (это отдельно закрыто ``test_routing_epoch_live``:
peer→peer доставка после restart). Поэтому здесь Ф3.5-специфику — honest broken_wires
и re-issue провода B — проверяем на **синтетическом** wire, заведённом через
``wire.setup`` между двумя живыми процессами (санкционировано планом, §Шаги 4 live).

Разрыв наблюдаем ДЕТЕРМИНИРОВАННО: ``process.stop`` peer'а держит endpoint мёртвым
(graceful stop → «stopped», без авто-рестарта) → broken_wires стабильно ≥1, а не
транзиентно в узком окне рестарта. Восстановление — ``process.restart`` (re-issue
wire.configure в пересозданный инстанс) → broken_wires снова 0.

Собственный порт 8782 (≥8770 заняты; ловушка «двух бэкендов» — свой порт изолирует).
"""

from __future__ import annotations

import time

import pytest

from backend_ctl.harness import BackendHarness

_SOURCE = "devices"        # protected → выживает restart соседа
_PEER = "preprocessor"     # non-protected → пересоздаётся на restart
_WIRE = "synthetic_wire"   # ASCII-ключ (без «→» в state-пути)
_PORT = 8782               # уникальный порт (8770-8781 заняты)

_BROKEN = "system.health.broken_wires"
_WIRE_STATUS = f"system.wires.{_WIRE}.status"


def _result(res: dict) -> dict:
    """Развернуть result-конверт ответа (см. test_health_live._result)."""
    if isinstance(res, dict) and isinstance(res.get("result"), dict):
        return res["result"]
    return res if isinstance(res, dict) else {}


@pytest.fixture(scope="module")
def wire_backend():
    """Свой headless-бэкенд для wire-теста (base.yaml → devices)."""
    harness = BackendHarness(with_base=True, port=_PORT)
    drv = harness.start()
    try:
        yield drv
    finally:
        harness.stop()


def _wait_path(drv, path: str, predicate, deadline: float):
    """Дождаться дельты ``path``, чьё new_value удовлетворяет predicate.

    Возвращает последнее увиденное значение (или None). Delta-driven: подписка
    шлёт push только при РЕАЛЬНОМ изменении, поэтому копим до предиката/дедлайна.
    """
    latest = None
    while time.time() < deadline:
        for e in drv.events(timeout=2.0):
            if e.get("command") != "state.changed":
                continue
            for d in (e.get("data") or {}).get("deltas", []) or []:
                if d.get("path") == path:
                    latest = d.get("new_value")
        if latest is not None and predicate(latest):
            return latest
    return latest


@pytest.mark.harness_smoke
def test_broken_wires_honest_and_recovers(wire_backend) -> None:
    """Синтетический провод: stop peer → broken_wires≥1; restart → re-issue → 0."""
    drv = wire_backend

    # --- Полная топология: создаём preprocessor (base.yaml даёт только devices) ---
    from multiprocess_prototype.backend.launch import load_topology_dict
    from multiprocess_prototype.main import DEFAULT_BLUEPRINT

    bp = load_topology_dict(DEFAULT_BLUEPRINT)
    applied = _result(
        drv.send_command("ProcessManager", "topology.apply", {"topology_dict": bp}, timeout=30.0)
    )
    assert applied.get("success") is True, f"topology.apply не success: {applied}"
    time.sleep(3.0)  # дать процессам подняться + первый heartbeat

    # --- Подписка на health/wire-ветки ДО манипуляций ---
    sub = _result(drv.state_subscribe("system.**", timeout=8.0))
    assert sub.get("status") == "ok", f"state.subscribe не ok: {sub}"
    drv.events()  # осушить накопленное

    # --- Синтетический провод devices→preprocessor (путь B, обычно GUI-only) ---
    ws = _result(
        drv.send_command(
            "ProcessManager",
            "wire.setup",
            {
                "wire_key": _WIRE,
                "source_process": _SOURCE,
                "target_process": _PEER,
                "transport": "router",
                "shm_config": {"shm_name": "syn_frames", "buffer_slots": 4},
            },
            timeout=10.0,
        )
    )
    assert ws.get("success") is True, f"wire.setup не success: {ws}"

    # Провод активен при живых endpoint'ах (оба процесса running).
    active = _wait_path(drv, _WIRE_STATUS, lambda v: v == "active", time.time() + 15.0)
    assert active == "active", f"wire не 'active' при живой топологии: {active}"

    # --- Разрыв: stop peer → endpoint мёртв → broken_wires ≥ 1 (honest) ---
    stopped = _result(
        drv.send_command("ProcessManager", "process.stop", {"process_name": _PEER}, timeout=15.0)
    )
    assert stopped.get("success") is True, f"process.stop не success: {stopped}"

    broken = _wait_path(drv, _BROKEN, lambda v: isinstance(v, int) and v >= 1, time.time() + 20.0)
    assert broken is not None and broken >= 1, (
        f"broken_wires НЕ ≥1 при оборванном проводе (honest-статус не сработал): {broken}"
    )

    # --- Восстановление: restart peer → re-issue wire.configure → broken_wires 0 ---
    drv.events()  # осушить буфер до restart (изолировать post-restart серию)
    r = _result(
        drv.send_command("ProcessManager", "process.restart", {"process_name": _PEER}, timeout=30.0)
    )
    assert r.get("success") is True, f"process.restart не success: {r}"

    # Копим серию broken_wires после restart: re-issue вернул wire в active,
    # peer снова is_alive → broken_wires опускается к 0 (delta 1→0 наблюдаемо).
    broken_series: list = []
    deadline = time.time() + 30.0
    while time.time() < deadline:
        for e in drv.events(timeout=2.0):
            if e.get("command") != "state.changed":
                continue
            for d in (e.get("data") or {}).get("deltas", []) or []:
                if d.get("path") == _BROKEN:
                    broken_series.append(d.get("new_value"))
        if broken_series and broken_series[-1] == 0:
            break
    assert 0 in broken_series, (
        f"broken_wires НЕ вернулся к 0 после re-issue провода: series={broken_series}"
    )
