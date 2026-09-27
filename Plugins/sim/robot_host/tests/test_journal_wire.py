# -*- coding: utf-8 -*-
"""Кольцо ``wire`` команды ``sim_robot.journal`` — «что дошло до робота» для пульта линии.

``recent`` отдаёт только задания (теги job/dup/done, Контракт 5.1 §2); ``wire`` — ВСЕ
строки журнала: любую запись с провода с именем регистра и события робота. Харнесс —
из ``test_journal_commands.py`` (реальный ``SimRobotServer`` на свободном порту).
"""

from __future__ import annotations

from Plugins.sim.robot_host.plugin import _JOURNAL_WIRE_MAXLEN
from Plugins.sim.robot_host.tests import test_journal_commands as _jc
from Plugins.sim.robot_host.tests.test_journal_commands import _FC_WRITE_SINGLE, _call, _drive_job

running_plugin = _jc.running_plugin  # фикстура харнесса журнала
pytestmark = _jc.pytestmark  # без pymodbus — skip, как у харнесса (ревью 6.2, п.1)

_REG_SERVO = 0x1108  # Services/robot_comm/core/registers.py: REG_SERVO


def test_wire_carries_non_job_write_that_recent_drops(running_plugin) -> None:
    plugin, _ctx, _services = running_plugin
    plugin._on_write(_FC_WRITE_SINGLE, _REG_SERVO, [1])
    plugin._publish_once()

    resp = _call(plugin, "sim_robot.journal")

    assert resp["recent"] == [], resp["recent"]
    wire = resp["wire"]
    assert len(wire) == 1, wire
    assert wire[0]["side"] == "in", wire[0]
    assert "servo" in wire[0]["text"].lower(), wire[0]  # подписано именем из карты, не адресом
    assert set(wire[0].keys()) == {"t", "side", "text", "tag", "n"}, wire[0]


def test_wire_keeps_job_lines_in_order_and_recent_unchanged(running_plugin) -> None:
    plugin, _ctx, _services = running_plugin
    _drive_job(plugin, x_mm=10.0, y_mm=20.0, ecap=1000)
    plugin._publish_once()

    resp = _call(plugin, "sim_robot.journal")

    assert [e["tag"] for e in resp["recent"]] == ["job"], resp["recent"]
    tags = [e["tag"] for e in resp["wire"]]
    # X, Y, два слова энкодера, флаг, затем строка задания — старые первыми.
    assert tags == ["", "", "", "", "flag", "job"], resp["wire"]
    times = [e["t"] for e in resp["wire"]]
    assert times == sorted(times)


def test_wire_event_from_robot_side_is_out(running_plugin) -> None:
    plugin, _ctx, _services = running_plugin
    plugin._journal.on_event("серво включено")
    plugin._publish_once()

    wire = _call(plugin, "sim_robot.journal")["wire"]

    assert [(e["side"], e["text"]) for e in wire] == [("out", "серво включено")], wire


def test_journal_reset_clears_wire(running_plugin) -> None:
    plugin, _ctx, _services = running_plugin
    plugin._on_write(_FC_WRITE_SINGLE, _REG_SERVO, [1])
    plugin._publish_once()

    assert _call(plugin, "sim_robot.journal_reset") == {"status": "ok"}

    assert _call(plugin, "sim_robot.journal")["wire"] == []


def test_wire_is_bounded_and_drops_oldest(running_plugin) -> None:
    plugin, _ctx, _services = running_plugin
    assert _JOURNAL_WIRE_MAXLEN == 200
    for value in range(250):
        plugin._on_write(_FC_WRITE_SINGLE, _REG_SERVO, [value])
    plugin._publish_once()

    wire = _call(plugin, "sim_robot.journal")["wire"]

    assert len(wire) == 200, len(wire)
    assert wire[0]["text"].endswith("= 50"), wire[0]  # первые 50 вытеснены
    assert wire[-1]["text"].endswith("= 249"), wire[-1]


def test_wire_collapses_consecutive_repeats(running_plugin) -> None:
    """keepalive моста ПЧ (одна и та же запись каждые 0.5 с) не вытесняет остальное."""
    plugin, _ctx, _services = running_plugin
    for _ in range(300):
        plugin._on_write(_FC_WRITE_SINGLE, _REG_SERVO, [1])
    plugin._publish_once()
    t_first_tick = _call(plugin, "sim_robot.journal")["wire"][0]["t"]
    for _ in range(3):
        plugin._on_write(_FC_WRITE_SINGLE, _REG_SERVO, [1])  # и через границу тика
    plugin._on_write(_FC_WRITE_SINGLE, _REG_SERVO, [0])
    plugin._on_write(_FC_WRITE_SINGLE, _REG_SERVO, [1])
    plugin._publish_once()

    wire = _call(plugin, "sim_robot.journal")["wire"]

    assert [(e["text"].split("= ")[-1], e["n"]) for e in wire] == [("1", 303), ("0", 1), ("1", 1)], wire
    assert wire[0]["t"] > t_first_tick, wire[0]  # время склейки — последней строки, не первой


def test_wire_snapshot_is_a_copy(running_plugin) -> None:
    """Склейка правит строку кольца на месте — отданный ранее ответ не должен меняться."""
    plugin, _ctx, _services = running_plugin
    plugin._on_write(_FC_WRITE_SINGLE, _REG_SERVO, [1])
    plugin._publish_once()
    first = _call(plugin, "sim_robot.journal")["wire"]
    plugin._on_write(_FC_WRITE_SINGLE, _REG_SERVO, [1])
    plugin._publish_once()

    assert first[0]["n"] == 1, first
