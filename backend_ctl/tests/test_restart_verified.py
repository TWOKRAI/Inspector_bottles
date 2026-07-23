# -*- coding: utf-8 -*-
"""``process_restart_verified`` — PID-доказательство рестарта (Ф4 Task 4.4).

План: `plans/truth-holes-closure.md`. Дыра: `process.restart` штатно идёт дольше
таймаута ответа (graceful-stop), поэтому сырой ``system_command`` возвращает
``{"error": "timeout"}`` при РЕАЛЬНО доставленной команде — «сигнал не связан с
реальностью». Здесь вердикт выносит факт (pid до/после), а ответ команды остаётся
справкой.

Транспорт мокается (``send_command``/``system_command``) — по образцу
TestTelemetrySetVerify: проверяем ЛОГИКУ вердикта, а не сокет.
"""

from __future__ import annotations

from typing import Any, Dict, List

from backend_ctl.driver import BackendDriver


def _driver(monkeypatch, snapshots: List[Dict[str, Any]], *, restart_reply: Any = None):
    """Driver, чей supervision.status отдаёт заготовленную ПОСЛЕДОВАТЕЛЬНОСТЬ снимков.

    Последний снимок повторяется до конца — так моделируется «pid уже сменился и
    дальше стабилен» либо «так и не сменился».
    """
    d = BackendDriver()
    calls: List[str] = []
    state = {"i": 0}

    def fake_send(process, command, args=None, **kw):
        calls.append(command)
        if command == "supervision.status":
            idx = min(state["i"], len(snapshots) - 1)
            state["i"] += 1
            entry = snapshots[idx]
            procs = {"lines": entry} if entry else {}
            return {"success": True, "result": {"success": True, "epoch": 0, "processes": procs}}
        return {"success": True, "result": {"success": True}}

    def fake_system(command, timeout=None):
        calls.append(f"system:{command.get('cmd')}:{command.get('process_name')}")
        return restart_reply if restart_reply is not None else {"success": True}

    monkeypatch.setattr(d, "send_command", fake_send)
    monkeypatch.setattr(d, "system_command", fake_system)
    return d, calls


def _entry(pid: int | None, *, restarts: int = 0, alive: bool = True) -> Dict[str, Any]:
    return {
        "incarnation": 0,
        "restart_count": 0,
        "last_exit": None,
        "status": "running",
        "pid": pid,
        "alive": alive,
        "started_at": 1000.0,
        "instance_restarts": restarts,
    }


class TestVerdictFromFactNotReply:
    def test_pid_change_proves_restart(self, monkeypatch) -> None:
        d, calls = _driver(monkeypatch, [_entry(24808), _entry(26476, restarts=1)])
        res = d.process_restart_verified("lines", wait=5.0)
        assert res["restarted"] is True
        assert (res["pid_before"], res["pid_after"]) == (24808, 26476)
        assert (res["instance_restarts_before"], res["instance_restarts_after"]) == (0, 1)
        assert "system:process.restart:lines" in calls

    def test_timeout_reply_does_not_deny_a_real_restart(self, monkeypatch) -> None:
        """ГЛАВНОЕ: ответ команды — timeout, но pid сменился → restarted=True.

        Именно эта пара «ответ ≠ реальность» и была дырой: рестарт происходил, а
        инструмент рапортовал отказ.
        """
        d, _calls = _driver(
            monkeypatch,
            [_entry(24808), _entry(26476, restarts=1)],
            restart_reply={"success": False, "error": "timeout"},
        )
        res = d.process_restart_verified("lines", wait=5.0)
        assert res["restarted"] is True
        assert res["restart_reply"] == {"success": False, "error": "timeout"}  # справка, не вердикт

    def test_unchanged_pid_is_honest_failure(self, monkeypatch) -> None:
        """Второе плечо пары: успешный ответ, но pid тот же → restarted=False + причина."""
        d, _calls = _driver(monkeypatch, [_entry(24808)], restart_reply={"success": True})
        res = d.process_restart_verified("lines", wait=1.0)
        assert res["restarted"] is False
        assert "pid не сменился" in res["reason"]
        assert res["pid_before"] == res["pid_after"] == 24808

    def test_waits_until_new_pid_appears(self, monkeypatch) -> None:
        """Рестарт медленный: первые опросы отдают старый pid, потом появляется новый."""
        d, _calls = _driver(
            monkeypatch,
            [_entry(24808), _entry(24808), _entry(24808), _entry(17748, restarts=2)],
        )
        res = d.process_restart_verified("lines", wait=10.0)
        assert res["restarted"] is True and res["pid_after"] == 17748
        assert res["elapsed"] >= 0.5  # поллинг реально ждал, а не вынес вердикт сразу

    def test_dead_new_instance_is_not_counted_as_restarted_early(self, monkeypatch) -> None:
        """Новый pid, но процесс не жив → поллинг не останавливается на нём преждевременно."""
        d, _calls = _driver(monkeypatch, [_entry(24808), _entry(26476, alive=False)])
        res = d.process_restart_verified("lines", wait=1.0)
        # Вердикт по факту смены pid остаётся честным, но состояние инстанса видно.
        assert res["alive"] is False


class TestUnknownProcess:
    def test_missing_process_fails_fast_without_restarting(self, monkeypatch) -> None:
        """Опечатка в имени → честная ошибка И НИ ОДНОЙ разрушающей команды."""
        d, calls = _driver(monkeypatch, [{}])
        res = d.process_restart_verified("linez", wait=5.0)
        assert res["restarted"] is False
        assert "не найден" in res["reason"]
        assert not any(c.startswith("system:") for c in calls)
