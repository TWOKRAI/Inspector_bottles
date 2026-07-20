# -*- coding: utf-8 -*-
"""Тесты B.1: курсорные плоскости EventHub (events_page).

Acceptance плана (plans/backend-ctl-debug-console.md, Task B.1):
- два независимых курсора читают одну плоскость без взаимной кражи;
- переполнение кольца → dropped>0 виден читателю;
- next_cursor монотонен.

Легаси-дренаж ``events()`` (был вместе с events_page до F.1 — back-compat тест
``test_page_and_legacy_drain_do_not_consume_each_other``) удалён вместе с самим
методом; F.1 см. plans/backend-ctl-debug-console.md.

Инжекция входящих строк — через dispatch_raw (как в TestEventChannel), без сокета
и без live-бэкенда.
"""

from __future__ import annotations

from typing import Any, Dict, List

from backend_ctl.driver import BackendDriver


from backend_ctl.tests.conftest import wire_line as _line  # noqa: E402 — общий хелпер


def _push_state(d: BackendDriver, value: Any, path: str = "processes.cam.state.fps") -> None:
    d.dispatch_raw(_line({"command": "state.changed", "data": {"deltas": [{"path": path, "new_value": value}]}}))


def _push_supervisor(d: BackendDriver, event: str, name: str = "cam") -> None:
    """Push supervisor-перехода наблюдаемого процесса (state.changed)."""
    d.dispatch_raw(
        _line(
            {
                "command": "state.changed",
                "data": {"deltas": [{"path": f"processes.{name}.supervisor.event", "new_value": event}]},
            }
        )
    )


def _seqs(page: Dict[str, Any]) -> List[int]:
    return [it["seq"] for it in page["items"]]


class TestPlaneClassification:
    def test_state_changed_lands_in_state_and_telemetry(self) -> None:
        d = BackendDriver()
        d.dispatch_raw(
            _line(
                {
                    "command": "state.changed",
                    "data": {
                        "deltas": [
                            {"path": "processes.cam.state.fps", "new_value": 30},
                            {"path": "system.mode", "new_value": "run"},
                        ]
                    },
                }
            )
        )
        state = d.events_page("state")
        assert state["success"] is True
        assert state["count"] == 1
        assert state["items"][0]["event"]["command"] == "state.changed"
        # telemetry — per-delta зеркало ingest-потока read-model: 2 дельты → 2 item'а.
        tele = d.events_page("telemetry")
        assert tele["count"] == 2
        assert [it["event"]["command"] for it in tele["items"]] == ["telemetry.delta", "telemetry.delta"]
        assert tele["items"][0]["event"]["data"]["path"] == "processes.cam.state.fps"
        assert tele["items"][1]["event"]["data"]["new_value"] == "run"

    def test_log_ui_unknown_planes(self) -> None:
        d = BackendDriver()
        d.dispatch_raw(_line({"command": "log.record", "data": {"record": {"severity": "error"}}}))
        d.dispatch_raw(_line({"command": "ui.event", "data": {"record": {"kind": "button"}}}))
        d.dispatch_raw(_line({"command": "какая-то.новая", "data": {}}))
        d.dispatch_raw(_line({"request_id": "no-such-id", "result": {"x": 1}}))  # некарантинный поздний reply
        assert d.events_page("logs")["count"] == 1
        assert d.events_page("ui")["count"] == 1
        other = d.events_page("other")
        assert other["count"] == 2  # незнакомая команда + reply-как-событие: не потеряны молча
        assert d.events_page("all")["count"] == 4

    def test_observability_batch_split_by_kind(self) -> None:
        d = BackendDriver()
        d.dispatch_raw(
            _line(
                {
                    "command": "observability.record",
                    "data": {
                        "process": "cam",
                        "records": [
                            {"kind": "log", "severity": "info", "message": "a"},
                            {"kind": "stats", "severity": "gauge", "message": "b"},
                            {"kind": "log", "severity": "warning", "message": "c"},
                        ],
                    },
                }
            )
        )
        d.dispatch_raw(
            _line({"command": "observability.record", "data": {"record": {"kind": "error", "message": "boom"}}})
        )
        logs = d.events_page("logs")
        assert logs["count"] == 1
        log_view = logs["items"][0]["event"]
        assert log_view["command"] == "observability.record"
        assert [r["message"] for r in log_view["data"]["records"]] == ["a", "c"]
        assert log_view["data"]["process"] == "cam"  # прочие ключи data сохранены
        stats = d.events_page("stats")
        assert [r["message"] for r in stats["items"][0]["event"]["data"]["records"]] == ["b"]
        errors = d.events_page("errors")
        # Одиночная data.record нормализована в батч из одной записи.
        assert [r["message"] for r in errors["items"][0]["event"]["data"]["records"]] == ["boom"]
        # Оригиналы в arrival НЕ расщеплены: 2 сообщения как пришли.
        assert d.events_page("all")["count"] == 2

    def test_telemetry_delta_marks_deletion(self) -> None:
        """Удаление узла (__MISSING__) в telemetry-плоскости помечено deleted=True.

        B.2 metric_threshold не должен сравнивать строку-сентинел с числом
        (вскрыто ревью B.1).
        """
        d = BackendDriver()
        d.dispatch_raw(
            _line(
                {
                    "command": "state.changed",
                    "data": {
                        "deltas": [
                            {"path": "processes.cam.state.fps", "new_value": "__MISSING__"},
                            {"path": "processes.cam.state.uptime", "new_value": 5},
                        ]
                    },
                }
            )
        )
        items = d.events_page("telemetry")["items"]
        assert items[0]["event"]["data"]["deleted"] is True
        assert "deleted" not in items[1]["event"]["data"]

    def test_observability_record_without_kind_goes_other(self) -> None:
        d = BackendDriver()
        d.dispatch_raw(_line({"command": "observability.record", "data": {"records": [{"message": "нет kind"}]}}))
        assert d.events_page("other")["count"] == 1
        assert d.events_page("logs")["count"] == 0


class TestCursorIndependence:
    def test_two_cursors_read_same_plane_without_theft(self) -> None:
        d = BackendDriver()
        for i in range(3):
            _push_state(d, i)
        a1 = d.events_page("state")
        b1 = d.events_page("state")
        # Оба читателя видят ВСЕ события — никто ни у кого не украл.
        assert _seqs(a1) == [1, 2, 3]
        assert _seqs(b1) == [1, 2, 3]
        # Продолжение каждого курсора независимо: догнали хвост — пусто, без потерь.
        a2 = d.events_page("state", cursor=a1["next_cursor"])
        assert a2["items"] == [] and a2["dropped"] == 0
        _push_state(d, 99)
        a3 = d.events_page("state", cursor=a2["next_cursor"])
        b2 = d.events_page("state", cursor=b1["next_cursor"])
        assert _seqs(a3) == [4]
        assert _seqs(b2) == [4]


class TestDroppedAndMonotonic:
    def test_overflow_dropped_visible(self) -> None:
        d = BackendDriver(event_queue_maxlen=3)
        for i in range(5):
            _push_state(d, i)
        page = d.events_page("state")
        # Кольцо на 3: события seq 1–2 вытеснены — потеря ВИДНА, не съедена молча.
        assert page["dropped"] == 2
        assert _seqs(page) == [3, 4, 5]

    def test_dropped_relative_to_cursor(self) -> None:
        d = BackendDriver(event_queue_maxlen=3)
        for i in range(5):
            _push_state(d, i)
        cursor = d.events_page("state")["next_cursor"]  # прочитано до seq 5
        for i in range(5):
            _push_state(d, 10 + i)  # seq 6..10; кольцо держит 8..10
        page = d.events_page("state", cursor=cursor)
        assert page["dropped"] == 2  # seq 6–7 вытеснены МЕЖДУ чтениями
        assert _seqs(page) == [8, 9, 10]

    def test_next_cursor_monotonic_across_pages(self) -> None:
        d = BackendDriver()
        for i in range(5):
            _push_state(d, i)
        seen: List[int] = []
        cursor = None
        for _ in range(4):
            page = d.events_page("state", cursor=cursor, limit=2)
            seen.extend(_seqs(page))
            cursor = page["next_cursor"]
        assert seen == [1, 2, 3, 4, 5]
        assert seen == sorted(seen)  # seq строго возрастает, без повторов

    def test_caught_up_cursor_stable(self) -> None:
        d = BackendDriver()
        _push_state(d, 1)
        p1 = d.events_page("state")
        p2 = d.events_page("state", cursor=p1["next_cursor"])
        assert p2["items"] == [] and p2["dropped"] == 0
        assert p2["next_cursor"] == p1["next_cursor"]

    def test_empty_plane_returns_empty_page(self) -> None:
        d = BackendDriver()
        page = d.events_page("errors")
        assert page["success"] is True
        assert page["items"] == [] and page["dropped"] == 0
        assert page["next_cursor"] == page["bookmark"]

    def test_limit_clamped_to_at_least_one(self) -> None:
        d = BackendDriver()
        _push_state(d, 1)
        _push_state(d, 2)
        page = d.events_page("state", limit=0)
        assert page["count"] == 1  # limit<1 поднят до 1, не «всё» и не ошибка


class TestCursorSafety:
    def test_plane_mismatch_cursor_error(self) -> None:
        d = BackendDriver()
        _push_state(d, 1)
        d.dispatch_raw(_line({"command": "log.record", "data": {}}))
        log_cursor = d.events_page("logs")["next_cursor"]
        res = d.events_page("state", cursor=log_cursor)
        assert res["success"] is False
        assert "плоскост" in res["error"]
        assert res["reset_required"] is True
        assert res["bookmark"].startswith("state:")

    def test_foreign_generation_cursor_reset_required(self) -> None:
        d1 = BackendDriver()
        _push_state(d1, 1)
        stale = d1.events_page("state")["next_cursor"]
        d2 = BackendDriver()  # реконнект = новый driver = новый hub/gen
        _push_state(d2, 1)
        res = d2.events_page("state", cursor=stale)
        assert res["success"] is False
        assert res["reset_required"] is True
        assert "bookmark" in res
        assert "cursor=null" in res["error"]

    def test_cursor_ahead_of_stream_reset_required(self) -> None:
        d = BackendDriver()
        _push_state(d, 1)
        # Валидный gen, seq впереди потока: собрать из настоящего next_cursor.
        cur = d.events_page("state")["next_cursor"]  # 'state:1@<gen>'
        gen = cur.rpartition("@")[2]
        res = d.events_page("state", cursor=f"state:999@{gen}")
        assert res["success"] is False
        assert res["reset_required"] is True

    def test_truncated_cursor_forms_rejected(self) -> None:
        """Курсор без @gen или без префикса плоскости — отказ, не тихое чтение.

        Усечённая форма пропускала бы проверку поколения/плоскости и молча
        читала не с того места (вскрыто ревью B.1) — принимается только полная
        форма из next_cursor/bookmark.
        """
        d = BackendDriver()
        for i in range(3):
            _push_state(d, i)
        for bad in ("state:2", "2", "state@2", f"logs:1@{'x' * 6}"):
            res = d.events_page("state", cursor=bad)
            assert res["success"] is False, bad
            assert res["reset_required"] is True, bad

    def test_unknown_plane_lists_valid_planes(self) -> None:
        d = BackendDriver()
        res = d.events_page("нет-такой")
        assert res["success"] is False
        assert "state" in res["planes"] and "all" in res["planes"]

    def test_empty_plane_string_rejected(self) -> None:
        d = BackendDriver()
        res = d.events_page("")
        assert res["success"] is False  # пустая строка ≠ "all": ошибка вызывающего видна

    def test_bookmark_jumps_to_tail(self) -> None:
        d = BackendDriver()
        for i in range(3):
            _push_state(d, i)
        bookmark = d.events_page("state", limit=1)["bookmark"]
        fresh = d.events_page("state", cursor=bookmark)
        assert fresh["items"] == [] and fresh["dropped"] == 0  # старое пропущено сознательно
        _push_state(d, 42)
        after = d.events_page("state", cursor=fresh["next_cursor"])
        assert after["count"] == 1
        assert after["items"][0]["event"]["data"]["deltas"][0]["new_value"] == 42


class TestEventsStats:
    def test_stats_expose_eviction_and_sizes(self) -> None:
        d = BackendDriver(event_queue_maxlen=3)
        for i in range(5):
            _push_state(d, i)
        stats = d.events_stats()
        assert stats["all"] == {"seq": 5, "size": 3, "evicted": 2}
        assert stats["planes"]["state"] == {"seq": 5, "size": 3, "evicted": 2}
        assert stats["planes"]["logs"]["seq"] == 0


class TestRestartBoundaryGating:
    """§8 (ревью-фикс #3): ТОЛЬКО ``recovered`` (новая инкарнация ожила) ротирует
    generation-токен → курсор «до рестарта» даёт reset_required, а не читает молча
    СКВОЗЬ границу инкарнации (долг B.1). ``crashed``/``gave_up`` = процесс мёртв
    (новых событий нет) → НЕ ротируют (иначе reset-thrashing в crash-loop)."""

    def test_recovered_event_invalidates_prior_cursor(self) -> None:
        d = BackendDriver()
        _push_state(d, 1)
        stale = d.events_page("state")["next_cursor"]
        _push_supervisor(d, "recovered")  # процесс вернулся с новой инкарнацией
        res = d.events_page("state", cursor=stale)
        assert res["success"] is False
        assert res["reset_required"] is True
        assert "cursor=null" in res["error"]

    def test_crashed_and_gave_up_do_not_rotate(self) -> None:
        # Процесс мёртв: новых событий инкарнации нет → курсор остаётся валидным
        # (ротация на них лишь плодила бы reset-thrashing в crash-loop — фикс #3).
        for event in ("crashed", "gave_up"):
            d = BackendDriver()
            _push_state(d, 1)
            cur = d.events_page("state")["next_cursor"]
            _push_supervisor(d, event)
            assert d.events_page("state", cursor=cur)["success"] is True
        assert d.events_stats()["gen_rotations"] == 0

    def test_in_progress_supervisor_event_does_not_rotate(self) -> None:
        # restarting/unresponsive — рестарт в процессе, идентичность ещё не сменилась.
        d = BackendDriver()
        _push_state(d, 1)
        cur = d.events_page("state")["next_cursor"]
        _push_supervisor(d, "restarting")
        res = d.events_page("state", cursor=cur)
        assert res["success"] is True  # курсор НЕ инвалидирован

    def test_fresh_cursor_after_rotation_is_stable(self) -> None:
        d = BackendDriver()
        _push_state(d, 1)
        _push_supervisor(d, "recovered")
        fresh = d.events_page("state")["bookmark"]  # bookmark уже с новым gen
        _push_state(d, 2)
        res = d.events_page("state", cursor=fresh)
        assert res["success"] is True

    def test_gen_rotations_counter(self) -> None:
        d = BackendDriver()
        _push_supervisor(d, "recovered")
        _push_supervisor(d, "crashed")  # не ротирует
        _push_supervisor(d, "recovered")
        assert d.events_stats()["gen_rotations"] == 2
