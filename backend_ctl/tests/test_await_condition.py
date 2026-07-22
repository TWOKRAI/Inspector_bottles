# -*- coding: utf-8 -*-
"""Тесты B.2: await_condition — серверное ожидание вместо поллинга.

Acceptance плана: синтетический поток дельт → условие срабатывает на нужной;
таймаут возвращает диагноз (что ждали / что видели), не пустоту.

Поток имитируется producer-потоком, кормящим dispatch_raw (как reader-поток),
пока клиентский поток блокируется в await_condition — ноль поллинга, без сокета.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Dict, List

from backend_ctl.driver import BackendDriver


from backend_ctl.tests.conftest import wire_line as _line  # noqa: E402 — общий хелпер


def _state_line(path: str, value: Any) -> bytes:
    return _line({"command": "state.changed", "data": {"deltas": [{"path": path, "new_value": value}]}})


def _feed_later(d: BackendDriver, lines: List[bytes], delay: float = 0.05) -> threading.Thread:
    """Producer: подать строки в dispatch_raw после паузы (клиент уже ждёт)."""

    def run() -> None:
        time.sleep(delay)
        for raw in lines:
            d.dispatch_raw(raw)

    th = threading.Thread(target=run)
    th.start()
    return th


class TestStatePath:
    def test_triggers_on_matching_delta_only(self) -> None:
        d = BackendDriver()
        th = _feed_later(
            d,
            [
                _state_line("processes.cam.state.status", "starting"),  # не то значение
                _state_line("processes.cam2.state.status", "running"),  # не тот путь
                _state_line("processes.cam.state.status", "running"),  # цель
            ],
        )
        res = d.await_condition("state_path", {"path": "processes.cam.state.status", "value": "running"}, timeout=2.0)
        th.join()
        assert res["success"] is True
        assert res["matched"]["value"] == "running"
        assert res["matched"]["source"] == "delta"

    def test_already_satisfied_returns_immediately(self) -> None:
        d = BackendDriver()
        d.dispatch_raw(_state_line("processes.cam.state.status", "running"))  # уже в read-model
        t0 = time.monotonic()
        res = d.await_condition("state_path", {"path": "processes.cam.state.status", "value": "running"}, timeout=5.0)
        assert res["success"] is True
        assert res["matched"]["source"] == "read-model"
        assert time.monotonic() - t0 < 1.0  # не ждал таймаута

    def test_missing_marker_is_not_a_value(self) -> None:
        d = BackendDriver()
        th = _feed_later(d, [_state_line("processes.cam.state.status", "__MISSING__")])
        res = d.await_condition("state_path", {"path": "processes.cam.state.status", "value": None}, timeout=0.3)
        th.join()
        assert res["success"] is False  # удаление узла не матчится как значение


class TestMetricThreshold:
    def test_triggers_when_threshold_crossed(self) -> None:
        d = BackendDriver()
        th = _feed_later(
            d,
            [
                _state_line("processes.cam.state.fps", 5),
                _state_line("processes.cam.state.fps", 9),
                _state_line("processes.cam.state.fps", 11),  # пересекла порог
            ],
        )
        res = d.await_condition(
            "metric_threshold", {"path": "processes.cam.state.fps", "op": ">=", "value": 10}, timeout=2.0
        )
        th.join()
        assert res["success"] is True
        assert res["matched"]["value"] == 11
        assert res["matched"]["op"] == ">="

    def test_timeout_diagnosis_carries_last_seen(self) -> None:
        d = BackendDriver()
        th = _feed_later(d, [_state_line("processes.cam.state.fps", 7)])
        res = d.await_condition(
            "metric_threshold", {"path": "processes.cam.state.fps", "op": ">", "value": 100}, timeout=0.3
        )
        th.join()
        assert res["success"] is False and res["timed_out"] is True
        assert res["waited"]["op"] == ">"
        assert res["last_seen"]["value"] == 7  # диагноз: что видели последним, не пустота
        assert res["events_seen"] >= 1

    def test_invalid_op_teaches(self) -> None:
        d = BackendDriver()
        res = d.await_condition("metric_threshold", {"path": "p", "op": "~", "value": 1}, timeout=0.1)
        assert res["success"] is False
        assert "op" in res["error"]


class TestMetricThresholdUnknownMetric:
    """BCTL-ADR-007: опечатка в пути metric_threshold — громкий unknown_metric, не тихий
    таймаут, неотличимый от «порог не достигнут». Пара ON/OFF: известный путь бит-в-бит,
    опечатка — явный признак + кандидаты; отдельно — риск ложного блока легитимной,
    но ещё не публиковавшейся метрики."""

    def test_known_tracked_path_pair_unchanged(self) -> None:
        """Плечо «известно»: путь трекается (суффикс ``.state.fps``) — ответ бит-в-бит,
        никакого unknown_metric/candidates, таймаут отрабатывает полный бюджет."""
        d = BackendDriver()
        th = _feed_later(d, [_state_line("processes.cam.state.fps", 7)])
        res = d.await_condition(
            "metric_threshold", {"path": "processes.cam.state.fps", "op": ">", "value": 100}, timeout=0.3
        )
        th.join()
        assert res["success"] is False and res["timed_out"] is True
        assert "unknown_metric" not in res
        assert "candidates" not in res
        assert 0.25 <= res["elapsed_sec"] <= 1.0  # полный бюджет отжидали, не срезали тайминг

    def test_typo_path_pair_flags_unknown_with_candidates(self) -> None:
        """Плечо «опечатка»: путь на одну букву длиннее реально наблюдённого — unknown_metric
        + непустой список кандидатов (difflib), таймаут отрабатывает тот же бюджет."""
        d = BackendDriver()
        d.dispatch_raw(_state_line("processes.cam.state.fps", 5))  # уже в read-model к моменту setup
        res = d.await_condition(
            "metric_threshold", {"path": "processes.cam.state.fpss", "op": ">", "value": 1}, timeout=0.3
        )
        assert res["success"] is False and res["timed_out"] is True
        assert res["unknown_metric"] is True
        assert res["candidates"]  # непустой список
        assert "processes.cam.state.fps" in res["candidates"]
        assert 0.25 <= res["elapsed_sec"] <= 1.0  # тот же бюджет, что и известный путь

    def test_not_yet_published_tracked_metric_not_blocked(self) -> None:
        """Главный риск: легитимная метрика (трекаемый суффикс), которая ещё не
        публиковалась, — read-model НЕПУСТ (другая камера уже наблюдалась), но у самого
        пути ни одной точки не было. Суффикс трекается → маркер НЕ ставится, отказа нет —
        обычный таймаут «данных пока нет», без изменений."""
        d = BackendDriver()
        d.dispatch_raw(_state_line("processes.cam1.state.fps", 5))  # непустой read-model
        res = d.await_condition(
            "metric_threshold", {"path": "processes.cam2.state.fps", "op": ">", "value": 1}, timeout=0.3
        )
        assert res["success"] is False and res["timed_out"] is True
        assert "unknown_metric" not in res

    def test_empty_read_model_skips_check(self) -> None:
        """Пустой свод read-model (ничего не наблюдалось вовсе) — проверка ПРОПУЩЕНА:
        даже совершенно случайный путь не получает unknown_metric (консервативность)."""
        d = BackendDriver()
        res = d.await_condition(
            "metric_threshold", {"path": "totally.unknown.path", "op": ">", "value": 1}, timeout=0.2
        )
        assert res["success"] is False and res["timed_out"] is True
        assert "unknown_metric" not in res


class TestEventMatches:
    def test_matches_plane_event_by_glob(self) -> None:
        d = BackendDriver()
        th = _feed_later(
            d,
            [
                _line({"command": "log.record", "data": {"record": {}}}),  # чужая плоскость
                _line({"command": "ui.event", "data": {"record": {"kind": "button"}}}),
            ],
        )
        res = d.await_condition("event_matches", {"plane": "ui", "pattern": "ui.*"}, timeout=2.0)
        th.join()
        assert res["success"] is True
        assert res["matched"]["matched_target"] == "ui.event"
        assert res["matched"]["event"]["command"] == "ui.event"

    def test_matches_delta_path_in_state_plane(self) -> None:
        d = BackendDriver()
        th = _feed_later(d, [_state_line("devices.plc.link", "up")])
        res = d.await_condition("event_matches", {"plane": "state", "pattern": "devices.*.link"}, timeout=2.0)
        th.join()
        assert res["success"] is True
        assert res["matched"]["matched_target"] == "devices.plc.link"

    def test_unknown_plane_teaches(self) -> None:
        d = BackendDriver()
        res = d.await_condition("event_matches", {"plane": "нет", "pattern": "*"}, timeout=0.1)
        assert res["success"] is False
        assert "plane" in res["error"]


class TestTimeoutDiagnosis:
    def test_hint_survives_irrelevant_traffic(self) -> None:
        """Фоновый трафик (логи при активном watch-профиле) не гасит подсказку.

        Ревью фазы B: hint гейтился на events_seen==0 и подавлялся ЛЮБЫМИ
        событиями — теперь он привязан к отсутствию РЕЛЕВАНТНЫХ наблюдений.
        """
        d = BackendDriver()
        th = _feed_later(d, [_line({"command": "log.record", "data": {"record": {"severity": "info"}}})] * 3)
        res = d.await_condition("state_path", {"path": "processes.cam.state.status", "value": "running"}, timeout=0.3)
        th.join()
        assert res["success"] is False
        assert res["events_seen"] >= 3  # трафик шёл...
        assert "подписка" in res["hint"]  # ...но подсказка о недостающей подписке жива

    def test_metric_threshold_wrong_type_visible_in_last_seen(self) -> None:
        """Нечисловое значение по нужному пути видно в диагнозе («не метрика»)."""
        d = BackendDriver()
        th = _feed_later(d, [_state_line("processes.cam.state.status", "running")])
        res = d.await_condition(
            "metric_threshold", {"path": "processes.cam.state.status", "op": ">", "value": 10}, timeout=0.3
        )
        th.join()
        assert res["success"] is False
        assert res["last_seen"]["value"] == "running"  # диагноз: путь отдаёт строку, не метрику
        assert "hint" not in res  # релевантное наблюдение было — подсказка о подписке не нужна

    def test_mcp_timeout_capped_and_zero_passthrough(self, monkeypatch) -> None:
        """MCP-cap: timeout=999 режется до 30; timeout=0 — валидный «проверь сейчас»."""
        from backend_ctl.mcp_tools import MAX_EVENTS_TIMEOUT, call_tool

        d = BackendDriver()
        seen: List[float] = []

        def fake_await(kind: str, spec: Any, *, timeout: float) -> Dict[str, Any]:
            seen.append(timeout)
            return {"success": False, "timed_out": True}

        monkeypatch.setattr(d, "await_condition", fake_await)
        call_tool(d, "await_condition", {"kind": "state_path", "spec": {}, "timeout": 999})
        call_tool(d, "await_condition", {"kind": "state_path", "spec": {}, "timeout": 0})
        assert seen == [MAX_EVENTS_TIMEOUT, 0.0]


class TestContract:
    def test_unknown_kind_and_bad_spec(self) -> None:
        d = BackendDriver()
        assert d.await_condition("wait_for", {}, timeout=0.1)["success"] is False
        assert d.await_condition("state_path", None, timeout=0.1)["success"] is False

    def test_timeout_hint_when_no_deltas_at_all(self) -> None:
        d = BackendDriver()
        res = d.await_condition("state_path", {"path": "processes.x.y", "value": 1}, timeout=0.2)
        assert res["success"] is False
        assert "подписка" in res["hint"]  # диагноз подсказывает вероятную причину

    def test_listener_removed_after_wait(self) -> None:
        d = BackendDriver()
        subs_before = d.events_stats()["subscribers"]
        d.await_condition("state_path", {"path": "p.q", "value": 1}, timeout=0.1)
        assert d.events_stats()["subscribers"] == subs_before  # временный подписчик снят
