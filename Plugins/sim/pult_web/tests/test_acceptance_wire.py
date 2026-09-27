# -*- coding: utf-8 -*-
"""RED-приёмка Task 6.2, §A7 — раздел «Что дошло до робота» на странице пульта.

Независимый tester, worktree на коммите ДО реализации 6.2. Контракт — ТОЛЬКО
критерий A7 из брифа лида (plans/line-sim/plan.md, Task 6.2): заголовок
«Что дошло до робота», элемент ``id="wire"``, рендер существующего 1s-опроса
``/api/journal`` в ``#wire`` по правилу из брифа (новейшие сверху, формат строки
и агрегация ``×n``, литералы "пока ничего" / "журнал недоступен"). ``plugin.py``
этого и соседнего плагина НЕ читан.

Харнесс переиспользован (не переписан) из ``test_acceptance_5_3a.py`` (Task 5.3a,
уже ЗЕЛЁНЫЙ) — ``start_pult`` (фабрика плагина с фейковым ``DeviceHubClient``),
``_client_for``, ``_run_page_js`` (реальный ``<script>`` страницы через ``node:vm``)
— импортированы по образцу из брифа (``running_plugin = _m.running_plugin``,
иначе ruff F811).

**Догадка тестера:** содержимое строк фикстуры ``_WIRE_FIXTURE`` (тексты/теги)
полностью придумано тестером как ВХОДНЫЕ данные для рендера — формат страницы
(§A7) целиком выводится из времени ``t`` (age = t(newest) − t(row), не зависит
от реальных часов) и полей ``side``/``text``/``n``, поэтому ожидаемая строка
литеральна и не зависит от догадок о формате бэкенда.
"""

from __future__ import annotations

import pytest

from Plugins.sim.pult_web.tests import test_acceptance_5_3a as _m

pytestmark = pytest.mark.timeout(30)

start_pult = _m.start_pult
_client_for = _m._client_for
_run_page_js = _m._run_page_js

_WIRE_FIXTURE = [
    {"t": 100.0, "side": "in", "text": "servo=1", "tag": "reg", "n": 1},
    {"t": 100.5, "side": "out", "text": "серво включено", "tag": "event", "n": 1},
    {"t": 101.0, "side": "in", "text": "job_x=125", "tag": "job", "n": 2},
]

#: Новейшая (t=101.0) сверху: age = 101.0-101.0=0.00; 101.0-100.5=0.50; 101.0-100.0=1.00.
_EXPECTED_WIRE_TEXT = "-0.00 с  ◀ job_x=125  ×2\n-0.50 с  ▶ серво включено\n-1.00 с  ◀ servo=1"


@pytest.mark.skipif(_m._NODE is None, reason="node недоступен в PATH")
def test_a7_render_newest_first(start_pult) -> None:
    """Разбор §A7: newest first, join("\\n"), ◀/▶ по side, "  ×n" только при n>1."""
    _plugin, _ctx, port = start_pult()
    robot_client = _client_for("robot")
    assert robot_client is not None, "нет клиента robot — второй клиент §1 из 5.3a тут не при чём"
    robot_client.responses["sim_robot.journal"] = {
        "status": "ok",
        "counters": {},
        "recent": [],
        "wire": [dict(row) for row in _WIRE_FIXTURE],
    }

    out = _run_page_js(port, "wire_acc")

    assert out.get("wireText") == _EXPECTED_WIRE_TEXT, (
        f"ожидали {_EXPECTED_WIRE_TEXT!r}, страница показала {out.get('wireText')!r}"
    )


@pytest.mark.skipif(_m._NODE is None, reason="node недоступен в PATH")
def test_a7_empty_and_unavailable(start_pult) -> None:
    """Пустая wire -> "пока ничего"; отказ команды журнала -> "журнал недоступен"."""
    _plugin, _ctx, port = start_pult()
    robot_client = _client_for("robot")
    assert robot_client is not None, "нет клиента robot"
    robot_client.responses["sim_robot.journal"] = {"status": "ok", "counters": {}, "recent": [], "wire": []}

    out_empty = _run_page_js(port, "wire_acc")
    assert out_empty.get("wireText") == "пока ничего", out_empty

    _plugin2, _ctx2, port2 = start_pult()
    robot_client2 = _client_for("robot")
    assert robot_client2 is not None, "нет клиента robot (второй pult этого теста)"
    robot_client2.responses["sim_robot.journal"] = {"status": "error", "message": "boom"}

    out_error = _run_page_js(port2, "wire_acc")
    assert out_error.get("wireText") == "журнал недоступен", out_error
