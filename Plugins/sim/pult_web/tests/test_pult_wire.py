# -*- coding: utf-8 -*-
"""Раздел пульта «Что дошло до робота» — настоящий ``<script>`` страницы против двойника robot.

Поле ``wire`` ответа ``sim_robot.journal`` (все строки журнала, старые первыми) страница
выводит свежими сверху: ◀ — запись от ПК, ▶ — событие робота.
"""

from __future__ import annotations

import pytest

from Plugins.sim.pult_web.tests import test_acceptance_5_3a as _acc
from Plugins.sim.pult_web.tests.test_acceptance_5_3a import _NODE, _client_for, _run_page_js

start_pult = _acc.start_pult  # фикстура: плагин с двойником DeviceHubClient

pytestmark = pytest.mark.skipif(_NODE is None, reason="node недоступен")


def _journal(wire: list[dict]) -> dict:
    counters = {"jobs": 0, "dups": 0, "done": 0, "dups_same_capture": 0, "dups_tracked": 0}
    return {"status": "ok", "counters": counters, "recent": [], "wire": wire}


def test_wire_rendered_newest_first_with_direction(start_pult) -> None:
    _plugin, _ctx, port = start_pult()
    _client_for("robot").responses["sim_robot.journal"] = _journal(
        [
            {"t": 10.0, "side": "in", "text": "fc6 servo = 1", "tag": "", "n": 3},
            {"t": 10.5, "side": "out", "text": "серво включено", "tag": "", "n": 1},
        ]
    )

    text = _run_page_js(port, "wire")["wireText"]

    assert text.split("\n") == ["-0.00 с  ▶ серво включено", "-0.50 с  ◀ fc6 servo = 1  ×3"], text


def test_wire_empty_says_nothing_yet(start_pult) -> None:
    _plugin, _ctx, port = start_pult()
    _client_for("robot").responses["sim_robot.journal"] = _journal([])

    assert _run_page_js(port, "wire")["wireText"] == "пока ничего"


def test_wire_goes_unavailable_after_ok(start_pult) -> None:
    """Журнал пропал после удачного опроса — старая лента не остаётся «свежей» (ревью 6.2, п.3)."""
    _plugin, _ctx, port = start_pult()
    robot = _client_for("robot")
    first = _journal([{"t": 1.0, "side": "in", "text": "W job_flag = 1", "tag": "flag", "n": 1}])
    replies = iter([first])
    original = robot.request

    def request(command: str, args: dict | None = None, timeout: float | None = None) -> dict:
        if command == "sim_robot.journal":
            robot.calls.append((command, dict(args or {})))
            return next(replies, {"status": "error", "message": "server_not_running"})
        return original(command, args, timeout)

    robot.request = request

    text = _run_page_js(port, "wire")["wireText"]  # 1200 мс: опрос на старте + один по таймеру

    journal_calls = [c for c in robot.calls if c[0] == "sim_robot.journal"]
    assert len(journal_calls) >= 2, journal_calls
    assert text == "журнал недоступен", text
