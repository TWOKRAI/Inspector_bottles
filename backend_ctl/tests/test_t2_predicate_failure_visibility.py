# -*- coding: utf-8 -*-
"""Т.2, авторские hazard-тесты к ветке удаления предка (`plans/observation-port/plan.md`).

Ветка «удалили предка» добавила в предикат обращение к ``delta["path"]`` как к
строке. Два риска, которых у прежнего кода не было:

1. **Дельта без строкового ``path``.** Прежний код сравнивал её на равенство и
   спокойно шёл дальше; новая ветка складывает ``candidate + "."``. На ``None``
   это ``TypeError`` — а ``_Waiter.offer`` ловит любое исключение и выходит,
   то есть теряет ВЕСЬ пакет, включая настоящее совпадение в его хвосте.
2. **Тишина самого отказа.** До Т.2 упавший предикат не оставлял следа: ответ по
   таймауту выглядел как «релевантных наблюдений не было». «Наблюдений не было»
   и «наблюдения были, но их разбор упал» — два РАЗНЫХ факта, и различить их
   снаружи было нечем.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Dict, List

from backend_ctl import conditions as C
from backend_ctl.driver import BackendDriver
from backend_ctl.tests.conftest import wire_line as _line

MISSING = C.MISSING_MARKER


def _deltas_line(deltas: List[Dict[str, Any]]) -> bytes:
    return _line({"command": "state.changed", "data": {"deltas": deltas}})


def _feed_later(d: BackendDriver, lines: List[bytes], delay: float = 0.05) -> threading.Thread:
    def run() -> None:
        time.sleep(delay)
        for raw in lines:
            d.dispatch_raw(raw)

    th = threading.Thread(target=run, daemon=True)
    th.start()
    return th


class TestMalformedDeltaDoesNotKillTheBatch:
    """Риск 1: дельта без строкового ``path`` не должна ронять разбор пакета."""

    def test_delta_without_path_does_not_swallow_a_real_match_in_the_same_batch(self) -> None:
        # Порядок важен: битая дельта ПЕРВОЙ. Если предикат на ней падает,
        # offer() выходит целиком и совпадение во второй дельте теряется.
        d = BackendDriver()
        th = _feed_later(
            d,
            [
                _deltas_line(
                    [
                        {"new_value": MISSING},  # без "path" вообще
                        {"path": None, "new_value": MISSING},  # path не строка
                        {"path": "processes.cam.state.status", "new_value": "running"},
                    ]
                )
            ],
        )
        res = d.await_condition("state_path", {"path": "processes.cam.state.status", "value": "running"}, timeout=2.0)
        th.join(timeout=5.0)
        assert th.is_alive() is False, "producer-поток не завершился"
        assert res["success"] is True, res
        assert res["matched"]["value"] == "running", res
        assert res.get("predicate_failures") is None, f"предикат упал там, где не должен: {res}"

    def test_same_for_metric_threshold(self) -> None:
        d = BackendDriver()
        th = _feed_later(
            d,
            [
                _deltas_line(
                    [
                        {"path": None, "new_value": MISSING},
                        {"path": "processes.cam.state.fps", "new_value": 30.0},
                    ]
                )
            ],
        )
        res = d.await_condition(
            "metric_threshold",
            {"path": "processes.cam.state.fps", "op": ">=", "value": 10},
            timeout=2.0,
        )
        th.join(timeout=5.0)
        assert res["success"] is True, res
        assert res["matched"]["value"] == 30.0, res


class TestPredicateFailureIsCountedNotSwallowed:
    """Риск 2: отказ предиката — считаемый факт, а не пустой ``last_seen``."""

    def test_waiter_counts_failures_and_remembers_the_first(self) -> None:
        def boom(_msg: Dict[str, Any]) -> None:
            raise ValueError("разбор дельты упал")

        waiter = C._Waiter(boom)
        waiter.offer({"command": "state.changed"})
        waiter.offer({"command": "state.changed"})

        assert waiter.predicate_failures == 2, waiter.predicate_failures
        assert waiter.first_predicate_error == "ValueError: разбор дельты упал", waiter.first_predicate_error
        # Отказ не считается наблюдением: events_seen не растёт, совпадения нет.
        assert waiter.events_seen == 0, waiter.events_seen
        assert waiter.matched is None

    def test_healthy_predicate_leaves_the_counter_at_zero(self) -> None:
        """Контроль к предыдущему: ноль засчитывается только рядом с ненулевым."""
        waiter = C._Waiter(lambda _msg: None)
        waiter.offer({"command": "state.changed"})

        assert waiter.predicate_failures == 0
        assert waiter.first_predicate_error is None
        assert waiter.events_seen == 1

    def test_timeout_answer_names_the_failure_instead_of_pretending_silence(self, monkeypatch) -> None:
        """Ответ по таймауту обязан назвать отказ, а не выдать «наблюдений не было»."""

        def boom(_msg: Dict[str, Any]) -> None:
            raise KeyError("plugins")

        def fake_setup(_drv: Any, _kind: str, _spec: Any, **_kw: Any):
            return C._Waiter(boom), lambda: None

        monkeypatch.setattr(C, "setup_condition", fake_setup)

        d = BackendDriver()
        th = _feed_later(d, [_deltas_line([{"path": "processes.cam.state.status", "new_value": "running"}])])
        res = C.await_condition(
            d, "state_path", {"path": "processes.cam.state.status", "value": "running"}, timeout=1.0
        )
        th.join(timeout=5.0)

        assert res["success"] is False and res["timed_out"] is True, res
        assert res["predicate_failures"] == 1, res
        assert res["first_predicate_error"] == "KeyError: 'plugins'", res
        # last_seen пуст — но теперь рядом стоит причина, почему он пуст.
        assert res["last_seen"] is None, res

    def test_healthy_run_does_not_carry_the_failure_keys(self) -> None:
        """Контроль: у исправного ожидания ключей отказа в ответе нет вообще."""
        d = BackendDriver()
        res = d.await_condition("state_path", {"path": "processes.cam.state.status", "value": "running"}, timeout=0.2)

        assert res["timed_out"] is True, res
        assert "predicate_failures" not in res, res
        assert "first_predicate_error" not in res, res
