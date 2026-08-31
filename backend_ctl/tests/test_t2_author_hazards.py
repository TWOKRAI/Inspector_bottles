# -*- coding: utf-8 -*-
"""Т.2 — тесты автора (дополнительно к независимому тестеру, не замена).

Правило проекта (``.claude/CLAUDE.md``, «Test authorship»): автор пишет тесты на
внутренние опасности механизма — то, что видно только тому, кто писал реализацию.
Здесь — три штуки:

  1. Грани хелпера предка ``_is_ancestor_path`` (conditions.py), которые
     acceptance-тесты не обязаны знать: корневой предок, наблюдаемый путь САМ
     является корнем (без точки вовсе), путь не является предком самому себе.
  2. Разграничение «удаление предка» (``MISSING_MARKER``) от «легитимный ``None``
     на пути предка» — это ДВА РАЗНЫХ факта, конфликт их смешал бы «узел исчез»
     с «узел присвоили в null».
  3. Форма и порядок аномалий ``queue_data_loss``/``control_plane_loss``, когда
     оба счётчика положительны сразу на НЕСКОЛЬКИХ процессах — независимый
     тестер проверял один процесс, здесь — что kind/detail/process не путаются
     между процессами.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Dict, List

from backend_ctl.conditions import _is_ancestor_path
from backend_ctl.driver import BackendDriver
from backend_ctl.events import MISSING_MARKER
from backend_ctl.tests.conftest import full_router_stats
from backend_ctl.tests.conftest import wire_line as _line
from backend_ctl.tests.test_overview import _fake_backend, _healthy_responses

JOIN_DEADLINE = 5.0


# ---- 1. Хелпер предка — юнит-грани ----------------------------------------


def test_root_segment_is_ancestor_of_grandchild() -> None:
    """Предок может быть КОРНЕВЫМ сегментом, а не только непосредственным родителем."""
    assert _is_ancestor_path("processes", "processes.gui.state.plugins.capture.capture_fps") is True


def test_path_is_not_its_own_ancestor() -> None:
    """Точное совпадение — не предок (это ветка exact-match, у неё своя семантика)."""
    assert _is_ancestor_path("processes.gui.x", "processes.gui.x") is False
    assert _is_ancestor_path("processes", "processes") is False


def test_single_segment_watched_path_has_no_textual_ancestor() -> None:
    """Наблюдаемый путь САМ корень (без точки) — текстовый префикс без точки-
    границы предком не считается, даже если совпадают первые буквы."""
    assert _is_ancestor_path("proc", "processes") is False


# ---- 2. MISSING_MARKER vs легитимный None — два разных факта --------------


def _state_line(path: str, value: Any) -> bytes:
    return _line({"command": "state.changed", "data": {"deltas": [{"path": path, "new_value": value}]}})


def _feed_later(d: BackendDriver, lines: List[bytes], delay: float = 0.05) -> threading.Thread:
    def run() -> None:
        time.sleep(delay)
        for raw in lines:
            d.dispatch_raw(raw)

    th = threading.Thread(target=run, daemon=True)
    th.start()
    return th


def _join_or_fail(th: threading.Thread) -> None:
    th.join(timeout=JOIN_DEADLINE)
    assert not th.is_alive(), "producer-поток не завершился в отведённый срок"


WATCHED = "processes.gui.state.plugins.capture.capture_fps"


def test_legitimate_none_on_ancestor_path_is_not_read_as_deletion() -> None:
    """``new_value=None`` на пути предка — легитимное присвоение null, НЕ
    ``MISSING_MARKER``. Спутать их значило бы читать «записали null куда-то
    выше» как «поддерево исчезло» — разные факты, разные диагнозы."""
    d = BackendDriver()
    th = _feed_later(d, [_state_line("processes.gui", None)])
    res = d.await_condition("state_path", {"path": WATCHED, "value": 30}, timeout=0.3)
    _join_or_fail(th)

    assert res["success"] is False
    assert res["last_seen"] is None, (
        f"None (не MISSING_MARKER) на пути предка не должен читаться как удаление: {res['last_seen']}"
    )
    assert "hint" in res  # ни одного релевантного наблюдения — подсказка на месте


def test_missing_marker_on_ancestor_is_distinguished_from_none_by_same_predicate() -> None:
    """Контрольное плечо: тот же путь предка, но настоящий ``MISSING_MARKER`` —
    диагноз обязан появиться. Пара с тестом выше доказывает, что различие
    именно в значении маркера, а не в чём-то ещё."""
    d = BackendDriver()
    th = _feed_later(d, [_state_line("processes.gui", MISSING_MARKER)])
    res = d.await_condition("state_path", {"path": WATCHED, "value": 30}, timeout=0.3)
    _join_or_fail(th)

    assert res["success"] is False
    assert res["last_seen"] is not None
    assert res["last_seen"].get("deleted") is True


# ---- 3. Форма/порядок аномалий на НЕСКОЛЬКИХ процессах ---------------------


def test_both_counters_positive_on_several_processes_do_not_cross_contaminate(monkeypatch) -> None:
    """Два процесса, разные значения обоих счётчиков — kind/detail/process
    каждой аномалии обязаны указывать на СВОЙ процесс и СВОЁ число, а не на
    значение соседа (независимый тестер проверял только один процесс)."""
    d = BackendDriver()
    responses = _healthy_responses()
    responses["introspect.router_stats@cam1"] = {
        "success": True,
        "router_stats": full_router_stats(queue_data_evicted=3, queue_never_drop_loss_total=5),
    }
    responses["introspect.router_stats@cam2"] = {
        "success": True,
        "router_stats": full_router_stats(queue_data_evicted=9, queue_never_drop_loss_total=11),
    }
    _fake_backend(monkeypatch, d, procs=["cam1", "cam2"], responses=responses)
    res = d.system_overview()

    by_kind_proc: Dict[tuple, List[Dict[str, Any]]] = {}
    for a in res["anomalies"]:
        if a["kind"] in ("queue_data_loss", "control_plane_loss"):
            by_kind_proc.setdefault((a["kind"], a["process"]), []).append(a)

    assert len(by_kind_proc[("queue_data_loss", "cam1")]) == 1
    assert "3" in by_kind_proc[("queue_data_loss", "cam1")][0]["detail"]
    assert len(by_kind_proc[("queue_data_loss", "cam2")]) == 1
    assert "9" in by_kind_proc[("queue_data_loss", "cam2")][0]["detail"]

    assert len(by_kind_proc[("control_plane_loss", "cam1")]) == 1
    assert "5" in by_kind_proc[("control_plane_loss", "cam1")][0]["detail"]
    assert len(by_kind_proc[("control_plane_loss", "cam2")]) == 1
    assert "11" in by_kind_proc[("control_plane_loss", "cam2")][0]["detail"]

    # Никакая аномалия cam1 не должна нести число cam2 и наоборот (перекрёстное
    # заражение — типовая ошибка при построении detail-строки в общем цикле по
    # процессам с переиспользуемой переменной).
    cam1_details = " ".join(a["detail"] for a in res["anomalies"] if a.get("process") == "cam1")
    assert "9" not in cam1_details and "11" not in cam1_details


def test_zero_and_positive_mixed_across_processes_only_flags_the_positive_one(monkeypatch) -> None:
    """Один процесс здоров (оба счётчика — 0), другой — нет. Здоровый не обязан
    получить ни одной аномалии из новых kind'ов, даже находясь в той же сводке."""
    d = BackendDriver()
    responses = _healthy_responses()
    responses["introspect.router_stats@cam_ok"] = {
        "success": True,
        "router_stats": full_router_stats(queue_data_evicted=0, queue_never_drop_loss_total=0),
    }
    responses["introspect.router_stats@cam_bad"] = {
        "success": True,
        "router_stats": full_router_stats(queue_data_evicted=0, queue_never_drop_loss_total=4),
    }
    _fake_backend(monkeypatch, d, procs=["cam_bad", "cam_ok"], responses=responses)
    res = d.system_overview()

    kinds_by_proc = {
        proc: [a["kind"] for a in res["anomalies"] if a.get("process") == proc] for proc in ("cam_ok", "cam_bad")
    }
    assert "queue_data_loss" not in kinds_by_proc["cam_ok"]
    assert "control_plane_loss" not in kinds_by_proc["cam_ok"]
    assert "control_plane_loss" in kinds_by_proc["cam_bad"]
    assert "queue_data_loss" not in kinds_by_proc["cam_bad"]
