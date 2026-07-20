# -*- coding: utf-8 -*-
"""Live-тесты RS-2/RS-3: честный state после switch + honest shutdown.

Acceptance аудита рецептов 2026-07-12 (RS-2/RS-3):
  - после switch state == ОС-реальности: 0 ghost-процессов старой топологии,
    у КАЖДОГО живого процесса есть pid, config соответствует НОВОМУ рецепту
    (Ж-2/LP-4 — cleanup поддерева при replace; RS-2 — publish pid+config);
  - switch НЕ роняет тихий ``state.merge failed`` WARNING (Ж-3 — контракт merge);
  - shutdown добивает ВСЕХ детей: 0 выживших по psutil (Ж-4).

Рецепты только headless-бутящиеся: region_pipeline ↔ line_filter_inspect
(source camera_0 + CapturePlugin бутится без камеры). НЕ phone_sketch/hikvision
(блок на железе — см. project_hardware_recipes_no_headless_boot).

Собственные порты 8782 (switch) и 8784 (shutdown) — РАЗНЫЕ бэкенды (ловушка «двух
бэкендов»: общий PID-реестр/SHM конфликтуют). См. project_concurrent_backends_trap,
feedback_live_harness_tests (разворачивание result-конверта).
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from backend_ctl.driver import _leaf_result
from backend_ctl.harness import BackendHarness
from backend_ctl.tests.conftest import bookmark_cursor as _bookmark
from backend_ctl.tests.conftest import page_events as _page

_SWITCH_PORT = 8782
_SHUTDOWN_PORT = 8784

_RECIPES = Path(__file__).resolve().parents[2] / "multiprocess_prototype" / "recipes"
_REGION = _RECIPES / "region_pipeline.yaml"
_LINE = _RECIPES / "line_filter_inspect.yaml"

# Процессы region_pipeline (non-protected) — после switch на line их не должно
# остаться в state (ghost-проверка).
_REGION_ONLY = {
    "preprocessor",
    "region_splitter",
    "process_negative",
    "process_grayscale",
    "process_flip",
    "stitcher",
}
# Процессы line_filter_inspect — после switch должны быть в state с pid + config.
_LINE_PROCS = {"camera_0", "detector", "line", "draw"}


def _state_subtree(drv, path: str) -> dict:
    """Прочитать поддерево StateStore через PM (state.get_subtree).

    Конверт ответа разворачивает ``_leaf_result`` (backend_ctl.driver) — общий
    хелпер, а не локальный дубль (спускается по вложенным ``result`` до листа).
    """
    res = drv.send_command("ProcessManager", "state.get_subtree", {"path": path, "request_id": "rs23"}, timeout=8.0)
    value = _leaf_result(res).get("value")
    return value if isinstance(value, dict) else {}


def _load_bp(path: Path) -> dict:
    from multiprocess_prototype.backend.launch import load_topology_dict

    return load_topology_dict(path)


def _pid_alive(pid: int) -> bool:
    """True если процесс с pid жив (os.kill(pid, 0) без ошибки)."""
    try:
        os.kill(pid, 0)
    except (ProcessLookupError, PermissionError):
        return False
    return True


# ===========================================================================
# RS-2: честный state после switch
# ===========================================================================


@pytest.fixture(scope="module")
def switch_backend():
    """Свой headless-бэкенд region_pipeline на уникальном порту."""
    harness = BackendHarness(recipe=_REGION, port=_SWITCH_PORT)
    drv = harness.start()
    try:
        yield harness, drv
    finally:
        harness.stop()


@pytest.mark.harness_smoke
def test_switch_state_matches_os(switch_backend) -> None:
    """После switch region→line: 0 ghost, у всех живых pid, config нового рецепта."""
    harness, drv = switch_backend

    # WARNING-tail PM — ловим тихий state.merge (Ж-3): его быть НЕ должно.
    drv.log_tail("ProcessManager", level="WARNING")
    cursor = _bookmark(drv)  # осушить возможный хвост до switch

    bp_line = _load_bp(_LINE)
    applied = _leaf_result(
        drv.send_command("ProcessManager", "topology.apply", {"topology_dict": bp_line}, timeout=40.0)
    )
    assert applied.get("success") is True, f"switch region→line не success: {applied}"

    # Дать монитору/heartbeat'ам осесть после switch.
    time.sleep(2.0)
    procs = _state_subtree(drv, "processes")
    assert procs, "поддерево processes пусто после switch"

    # (1) 0 ghost: ни одного процесса СТАРОЙ топологии в state.
    ghosts = sorted(_REGION_ONLY & set(procs))
    assert not ghosts, f"ghost-процессы region_pipeline остались в state после switch: {ghosts}"

    # (2) Каждый живой процесс нового рецепта присутствует с pid.
    for name in sorted(_LINE_PROCS):
        node = procs.get(name)
        assert isinstance(node, dict), f"процесс '{name}' отсутствует в state после switch"
        pid = node.get("pid")
        assert isinstance(pid, int) and pid > 0, f"у '{name}' нет валидного pid в state: {pid}"
        assert _pid_alive(pid), f"pid {pid} процесса '{name}' не жив в ОС (state врёт)"

    # (3) config соответствует НОВОМУ рецепту (detector — из line_filter_inspect).
    detector_cfg = procs.get("detector", {}).get("config")
    assert isinstance(detector_cfg, dict) and detector_cfg, "нет config detector в state после switch"

    # (4) Ж-3: тихий state.merge WARNING НЕ появился за окно switch.
    time.sleep(1.0)  # дать возможному хвостовому WARNING доехать
    evts, cursor = _page(drv, cursor)
    records = []
    for ev in evts:
        data = ev.get("data") if isinstance(ev, dict) else None
        rec = data.get("record") if isinstance(data, dict) else None
        if isinstance(rec, dict):
            records.append(str(rec.get("message", "")))
    silent_merge = [m for m in records if "state.merge" in m or "Поле 'data' обязательно" in m]
    assert not silent_merge, f"тихий state.merge WARNING на switch (Ж-3 не починен): {silent_merge}"


# ===========================================================================
# RS-3: shutdown добивает всех детей (Ж-4)
# ===========================================================================


@pytest.mark.harness_smoke
def test_shutdown_leaves_no_children() -> None:
    """Ж-4: после shutdown ни один дочерний процесс не остаётся живым (psutil)."""
    import psutil

    harness = BackendHarness(recipe=_REGION, port=_SHUTDOWN_PORT)
    harness.start()

    orch_pid = harness._orchestrator_pid()
    assert isinstance(orch_pid, int) and orch_pid > 0, "не получен pid оркестратора"

    # Снимок дочерних PID-ов ДО shutdown (реальные ОС-дети оркестратора).
    child_pids = [p.pid for p in psutil.Process(orch_pid).children(recursive=True)]
    assert child_pids, "у оркестратора нет дочерних процессов — нечего проверять"

    # Штатный shutdown (launcher.shutdown → PM.shutdown → stop_all с confirmed-death).
    harness.stop()

    # Дать ОС снять процессы.
    deadline = time.time() + 5.0
    survivors = child_pids
    while time.time() < deadline:
        survivors = [pid for pid in child_pids if _pid_alive(pid)]
        if not survivors:
            break
        time.sleep(0.3)

    assert not survivors, f"после shutdown выжили дети: {survivors} (Ж-4 не починен)"
