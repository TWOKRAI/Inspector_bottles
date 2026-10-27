# -*- coding: utf-8 -*-
"""Task 1.10 — тесты рисков автора (ревью р.1, пп. 1-2): две строки таблицы путей D4, которые приёмка R1-R14 не держит.

Обвязка — как в ``test_stop_outcome_acceptance.py`` (настоящий PM + два spawn-ребёнка ``slow`` / ``other``, окно
стопа 1,0 с). Ожидаемые значения — литералы из таблицы D4 (``plans/lifecycle-stop-ownership/tasks/T1.10.md``).

* H1 — гонка «жив для PM, мёртв для реестра»: ответ ``outcome: None``, ``success: True`` (итог берётся из канала
  ЭТОГО вызова, а не из записи реестра, которая могла остаться от прошлого стопа);
* H2 — «рестарт отказан до фазы стопа»: ответ ``outcome: None`` и после недавнего стопа на том же потоке исполнителя
  (канал вызова сбрасывает сам обработчик рестарта).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from .test_lifecycle_fifo_acceptance import Rig


@pytest.fixture
def rig(tmp_path: Path):
    """PM с окном стопа 1,0 с."""
    r = Rig(tmp_path, stop_timeout_s=1.0)
    try:
        r.start()
        yield r
    finally:
        r.close()


def _stop(rig: Rig, name: str):
    return rig.wait_reply(rig.send("process.stop", {"process_name": name}))


@pytest.mark.timeout(150)
def test_stop_reply_none_when_registry_sees_dead_after_pm_saw_alive(rig: Rig) -> None:
    """H1: ``process.stop other`` дважды; первый вызов ``is_alive`` из ``stop_process`` (проверка PM) даёт ``True``,
    дальше — настоящий ``False`` (реестр видит мёртвого) -> ``{"success": True, "process_name": "other",
    "outcome": None}``."""
    first = _stop(rig, "other")
    assert first is not None and first.result == {"success": True, "process_name": "other", "outcome": "exited"}, (
        f"предусловие: первый стоп other: {first and first.result}"
    )

    other = rig.pm._process_registry.get_process_by_name("other")
    real_is_alive = other.is_alive
    armed = {"once": True}

    def is_alive_pm_sees_alive():
        # Подмена только для проверки PM внутри stop_process; остальные вызовы (реестр, монитор) — настоящие.
        if armed["once"] and sys._getframe(1).f_code.co_name == "stop_process":
            armed["once"] = False
            return True
        return real_is_alive()

    other.is_alive = is_alive_pm_sees_alive
    try:
        second = _stop(rig, "other")
    finally:
        other.is_alive = real_is_alive

    assert armed["once"] is False, "подмена не сработала: stop_process не опрашивал is_alive"
    assert second is not None, "ответ второго process.stop other не пришёл за дедлайн"
    assert second.result == {"success": True, "process_name": "other", "outcome": None}, (
        f"второй стоп other: {second.result}"
    )


@pytest.mark.timeout(150)
def test_restart_refused_before_stop_reply_shape(rig: Rig) -> None:
    """H2: форма ответа отказанного рестарта — ``process.stop slow`` (``terminated``), затем ``process.restart ghost``
    (конфига нет, отказ до фазы стопа) -> ``{"success": False, "process_name": "ghost", "outcome": None}``.
    Утечку прошлого итога этот тест не обнаруживает (канал ключуется по имени) — её держит H2b."""
    stopped = _stop(rig, "slow")
    assert stopped is not None and stopped.result == {
        "success": True,
        "process_name": "slow",
        "outcome": "terminated",
    }, f"предусловие: стоп slow: {stopped and stopped.result}"

    refused = rig.wait_reply(rig.send("process.restart", {"process_name": "ghost"}))
    assert refused is not None, "ответ process.restart ghost не пришёл за дедлайн"
    assert refused.result == {"success": False, "process_name": "ghost", "outcome": None}, (
        f"рестарт ghost: {refused.result}"
    )


@pytest.mark.timeout(150)
def test_restart_of_dead_child_does_not_leak_previous_outcome(rig: Rig) -> None:
    """H2b: канал итога ключуется по имени, поэтому H2 (``ghost``) ловит утечку прошлого итога только чужого имени —
    а его там нет. Тот же ключ: ``process.stop slow`` (``terminated``), затем ``process.restart slow`` уже мёртвого
    (стопа нет — ``stop_process`` выходит коротко) -> ``{"success": True, "process_name": "slow", "outcome": None}``."""
    stopped = _stop(rig, "slow")
    assert stopped is not None and stopped.result == {
        "success": True,
        "process_name": "slow",
        "outcome": "terminated",
    }, f"предусловие: стоп slow: {stopped and stopped.result}"

    restarted = rig.wait_reply(rig.send("process.restart", {"process_name": "slow"}))
    assert restarted is not None, "ответ process.restart уже мёртвого slow не пришёл за дедлайн"
    assert restarted.result == {"success": True, "process_name": "slow", "outcome": None}, (
        f"рестарт мёртвого slow: {restarted.result}"
    )
