# -*- coding: utf-8 -*-
"""RED-приёмка Task 6.2, §A1-A6 — лента «что дошло до робота» (``wire``) в
команде ``sim_robot.journal`` (``SimRobotHostPlugin``).

Независимый tester, worktree на коммите ДО реализации 6.2. Контракт — ТОЛЬКО
критерии приёмки из брифа лида (DESIGN A1-A6, plans/line-sim/plan.md, Task 6.2),
переданные тестеру напрямую (включая точные вызовы ``plugin._journal.on_event(...)``
и ``plugin._publish_once()`` — не угаданные имена, они даны лидом). ``plugin.py``
этого плагина НЕ читан — блиндность обеспечена деревом (worktree на коммите до
правки), а не только прозой.

Харнесс скопирован (не переписан заново) с ``test_journal_commands.py`` (фикстура
``running_plugin`` + ``_call`` + ``_drive_job`` + FC-константы — уже ЗЕЛЁНЫЙ файл,
реюз через импорт по образцу из брифа: ``running_plugin = _m.running_plugin``,
иначе ruff F811) и с ``test_job_done_wiring_lead.py`` (паттерн рестарта сервера
через монkeypatch ``SimRobotServer`` + ``plugin._start_server`` напрямую — для A5(b)).

**Догадки тестера (см. финальный отчёт про "что интерпретировано, а не дано"):**

1. Категория «flag lines (tag 'flag')» из A1 — не расшифрована лидом однозначно.
   Интерпретация: это запись в любой *_flag регистр, КРОМЕ ``job_flag`` (у него
   уже есть свой tag «job» из Task 5.1) — например ``REG_PLACE_FLAG``.
   **Сверка лида после переноса (2026-09-27): догадка НЕВЕРНА.** ``SimJournal._tag_of``
   ставит «flag» ТОЛЬКО записи в ``REG_JOB_FLAG``; запись в ``REG_PLACE_FLAG`` идёт с
   тегом ``""``. Строка «flag» в тесте A1 приходит из ``_drive_job`` (маркер
   ``job_flag``), запись ``REG_PLACE_FLAG`` остаётся как ещё одна регистровая строка.
2. Сторона (``side``) записи регистра — "in" (запись ПК -> робот), сторона события
   ``on_event`` — "out" (робот -> ПК). Выведено из §A7 правила рендера
   (``"◀ " if side=="in" else "▶ "``) и формулировки A1 "robot-side events (side
   'out')" — не догадка, а прямое чтение брифа.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

import Services.robot_comm.server.sim_robot as sim_robot_module
from Plugins.sim.robot_host.plugin import SimRobotHostPlugin
from Plugins.sim.robot_host.tests import test_journal_commands as _m
from Services.robot_comm.core.registers import REG_JOB_ECAP, REG_JOB_FLAG, REG_PLACE_FLAG, REG_SERVO, SERVO_ON

pytestmark = _m.pytestmark

running_plugin = _m.running_plugin
_call = _m._call
_drive_job = _m._drive_job
_FC_WRITE_SINGLE = _m._FC_WRITE_SINGLE
_FC_WRITE_MULTI = _m._FC_WRITE_MULTI

_WIRE_KEYS = {"t", "side", "text", "tag", "n"}
_RECENT_KEYS = {"t", "side", "text", "tag"}


class _FakeServer:
    """Копия двойника сервера из ``test_job_done_wiring_lead.py`` — для A5(b)."""

    def __init__(self, host, port, unit_id, *, core=None, on_write=None):
        self.core = core

    def start(self):
        pass

    def stop(self):
        pass


# --------------------------------------------------------------------------- #
# A1 — wire несёт ВСЕ строки журнала независимо от тега                       #
# --------------------------------------------------------------------------- #


def test_a1_wire_carries_all_lines(running_plugin) -> None:
    plugin, _ctx, _services = running_plugin

    # TRAPS: запись N регистров -> N строк (один per регистр). job_ecap — DW,
    # FC16 на 2 слова с РАЗНЫМИ значениями (не схлопнутся между собой).
    plugin._on_write(_FC_WRITE_MULTI, REG_JOB_ECAP, [111, 222])
    plugin._publish_once()
    wire0 = _call(plugin, "sim_robot.journal")["wire"]
    assert len(wire0) == 2, f"запись 2 регистров (FC16) должна дать 2 строки в wire: {wire0!r}"

    # Категория «обычная запись регистра» — текст несёт ИМЯ регистра, не адрес.
    plugin._on_write(_FC_WRITE_SINGLE, REG_SERVO, [SERVO_ON])
    # Категория «событие со стороны робота» (side "out").
    plugin._journal.on_event("серво включено")
    # Категория «job» — существующая с Task 5.1 транзакция задания.
    _drive_job(plugin, x_mm=10.0, y_mm=20.0, ecap=1000)
    # Регистровая запись вне задания (тег ""); тег «flag» даёт job_flag из _drive_job выше.
    plugin._on_write(_FC_WRITE_SINGLE, REG_PLACE_FLAG, [1])

    plugin._publish_once()
    resp = _call(plugin, "sim_robot.journal")
    assert resp["status"] == "ok", resp

    wire = resp["wire"]
    assert isinstance(wire, list)
    assert len(wire) > len(wire0), "wire не выросла после новых записей/событий"

    for entry in wire:
        assert set(entry.keys()) == _WIRE_KEYS, entry

    ts = [entry["t"] for entry in wire]
    assert ts == sorted(ts), f"wire должна быть отсортирована по возрастанию t (старые первыми): {ts!r}"

    servo_entries = [e for e in wire if "servo" in e["text"].lower()]
    assert servo_entries, f"нет строки о записи в REG_SERVO по имени регистра 'servo': {wire!r}"
    for e in servo_entries:
        assert e["side"] == "in", e
        assert "1108" not in e["text"], f"текст показывает сырой адрес вместо имени регистра: {e!r}"

    out_entries = [e for e in wire if e["side"] == "out" and e["text"] == "серво включено"]
    assert len(out_entries) == 1, f"нет ровно одной строки события робота (on_event) в wire: {wire!r}"

    job_entries = [e for e in wire if e["tag"] == "job"]
    assert job_entries, f"нет строки с tag='job' в wire: {wire!r}"

    flag_entries = [e for e in wire if e["tag"] == "flag"]
    assert flag_entries, f"нет строки с tag='flag' в wire (маркер job_flag из _drive_job): {wire!r}"


# --------------------------------------------------------------------------- #
# A2 — recent не меняется: только job/dup/done, без ключа n                  #
# --------------------------------------------------------------------------- #


def test_a2_recent_contract_unchanged(running_plugin) -> None:
    plugin, _ctx, _services = running_plugin
    _drive_job(plugin, x_mm=10.0, y_mm=20.0, ecap=1000)
    plugin._publish_once()

    resp = _call(plugin, "sim_robot.journal")
    recent = resp["recent"]
    assert isinstance(recent, list)
    assert recent, "recent должен содержать хотя бы одну строку задания"
    for entry in recent:
        assert set(entry.keys()) == _RECENT_KEYS, entry
        assert entry["tag"] in {"job", "dup", "done"}, entry


# --------------------------------------------------------------------------- #
# A3 — схлопывание подряд идущих одинаковых строк (side И text), через такты  #
# --------------------------------------------------------------------------- #


def test_a3_collapse_runs(running_plugin) -> None:
    plugin, _ctx, _services = running_plugin

    plugin._journal.on_event("A")
    plugin._publish_once()
    wire1 = _call(plugin, "sim_robot.journal")["wire"]
    assert [(e["side"], e["text"], e["n"]) for e in wire1] == [("out", "A", 1)], wire1
    t_after_first = wire1[0]["t"]

    plugin._journal.on_event("A")
    plugin._publish_once()
    wire2 = _call(plugin, "sim_robot.journal")["wire"]
    assert [(e["side"], e["text"], e["n"]) for e in wire2] == [("out", "A", 2)], wire2
    assert wire2[0]["t"] > t_after_first, "t должно сдвинуться на время последней слитой строки"

    plugin._journal.on_event("B")
    plugin._publish_once()
    wire3 = _call(plugin, "sim_robot.journal")["wire"]
    assert [(e["text"], e["n"]) for e in wire3] == [("A", 2), ("B", 1)], wire3

    plugin._journal.on_event("A")
    plugin._publish_once()
    wire4 = _call(plugin, "sim_robot.journal")["wire"]
    assert [(e["text"], e["n"]) for e in wire4] == [("A", 2), ("B", 1), ("A", 1)], wire4


# --------------------------------------------------------------------------- #
# A4 — предел 200 строк, старые отбрасываются первыми                        #
# --------------------------------------------------------------------------- #


def test_a4_bounded_200(running_plugin) -> None:
    plugin, _ctx, _services = running_plugin
    total = 205
    for i in range(total):
        plugin._journal.on_event(f"line-{i:03d}")
        if i % 50 == 49:
            plugin._publish_once()
    plugin._publish_once()

    wire = _call(plugin, "sim_robot.journal")["wire"]
    assert len(wire) == 200, f"wire должна быть ограничена 200 записями, получили {len(wire)}"
    assert wire[0]["text"] == "line-005", f"старые записи должны отбрасываться первыми: {wire[0]!r}"
    assert wire[-1]["text"] == "line-204", wire[-1]


# --------------------------------------------------------------------------- #
# A5 — journal_reset и рестарт сервера чистят wire                           #
# --------------------------------------------------------------------------- #


def test_a5_reset_and_restart_clear(running_plugin, monkeypatch: pytest.MonkeyPatch) -> None:
    plugin, _ctx, _services = running_plugin

    plugin._journal.on_event("x1")
    plugin._journal.on_event("x2")
    plugin._publish_once()
    wire_before = _call(plugin, "sim_robot.journal")["wire"]
    assert wire_before, "wire должна быть непустой до reset"

    reset_resp = _call(plugin, "sim_robot.journal_reset")
    assert reset_resp == {"status": "ok"}, reset_resp

    wire_after_reset = _call(plugin, "sim_robot.journal")["wire"]
    assert wire_after_reset == [], wire_after_reset

    # Рестарт сервера — паттерн test_job_done_wiring_lead.py::test_restart_starts_with_empty_recent.
    monkeypatch.setattr(sim_robot_module, "SimRobotServer", _FakeServer)
    restart_ctx = MagicMock()
    restart_ctx.config = {"host": "127.0.0.1", "port": 0, "unit_id": 2, "auto_start": False}
    restart_plugin = SimRobotHostPlugin()
    restart_plugin.configure(restart_ctx)
    monkeypatch.setattr(restart_plugin, "_probe_port_free", lambda: None)
    restart_plugin._start_server(restart_ctx)
    restart_plugin._on_write(_FC_WRITE_SINGLE, REG_JOB_FLAG, [1])
    restart_plugin._publish_journal_once()
    assert restart_plugin.cmd_journal({})["wire"], "wire должна быть непустой перед рестартом"

    restart_plugin._server = None  # сервер остановлен
    restart_plugin._start_server(restart_ctx)
    journal = restart_plugin.cmd_journal({})
    assert journal["wire"] == [], "рестарт сервера должен начинать с пустой wire"


# --------------------------------------------------------------------------- #
# A6 — снимок: последующее схлопывание не меняет уже отданный ответ           #
# --------------------------------------------------------------------------- #


def test_a6_snapshot(running_plugin) -> None:
    plugin, _ctx, _services = running_plugin

    plugin._journal.on_event("X")
    plugin._publish_once()
    resp1 = _call(plugin, "sim_robot.journal")
    wire1 = resp1["wire"]
    assert wire1[-1]["n"] == 1, wire1

    plugin._journal.on_event("X")
    plugin._publish_once()

    assert wire1[-1]["n"] == 1, "ранее отданный снимок изменился после последующего слияния строк"

    resp2 = _call(plugin, "sim_robot.journal")
    assert resp2["wire"][-1]["n"] == 2, resp2["wire"]
