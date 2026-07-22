# -*- coding: utf-8 -*-
"""Task 6.1 ГАП 2 — ``watch_like_gui`` наполняет несколько плоскостей ``events_page``,
для «тихих» плоскостей — явная фиксация, что тишина есть свойство рецепта, а не дыра
в проводке.

Профиль GUI (``watch_like_gui`` = ``state.subscribe`` + ``observability.tail``) пушит
события в курсорный ``EventHub`` (``events.py``), который классифицирует их по
плоскостям (:data:`backend_ctl.events.PLANES`): ``state.changed`` разносится ЦЕЛИКОМ в
``state`` И поштучно (по дельте) в ``telemetry`` — та же живая система, тот же источник,
поэтому обе плоскости доказуемо ненулевые под активным watch на любом рецепте, где вообще
идёт какое-то состояние (``region_pipeline`` — синтетический, но живой конвейер).

``errors`` (ErrorManager-записи) и ``ui`` (клики GUI) — плоскости, для которых
black-box live-пруф ненуля на ЭТОМ рецепте принципиально недостижим:

  - ``ui`` наполняется ТОЛЬКО явными ``ui.event`` push'ами, которые шлёт живой GUI-клик
    (или ``ui_tap``/``ui_tap_ping`` — здесь не вызываются); headless-прогон без единого
    клика не может произвести на ней ни одного события — не флаки, а архитектурный факт;
  - ``errors`` наполняется ErrorManager (не Logger — см. проектное разделение
    logger/error/stats), т.е. реальными зафиксированными ошибками процессов;
    ``region_pipeline`` в штатном режиме (без внедрённых сбоев) их не производит.

Урок Task 6.1 плана: для таких плоскостей корректный уровень доказательства —
unit-инвариант классификации (docstring ``events.py`` + существующие fake-push тесты
``test_events_page.py``), а НЕ живой ненуль. Здесь тишина явно фиксируется, а не
замалчивается: ассерт стоит на ``count == 0`` (архитектурно гарантированный факт для
этого рецепта), а не пропускается молча.
"""

from __future__ import annotations

import time

import pytest

from backend_ctl.driver import BackendDriver
from backend_ctl.harness import BackendHarness

_PORT = 8797  # уникальный порт этого модуля (назначен координатором, Task 6.1 плана)


def _wait_plane_nonempty(drv: BackendDriver, plane: str, deadline: float) -> dict:
    """Дождаться первой непустой курсорной страницы заданной плоскости (с начала кольца)."""
    page = drv.events_page(plane=plane)
    while time.time() < deadline:
        page = drv.events_page(plane=plane)
        if page.get("count", 0) > 0:
            return page
        time.sleep(0.2)
    return page


@pytest.mark.harness_smoke
def test_watch_like_gui_state_and_telemetry_planes_nonzero_live() -> None:
    """Плечо ненуля BCTL-ADR-007: под watch_like_gui state/telemetry реально наполняются."""
    harness = BackendHarness(with_base=True, port=_PORT)
    try:
        drv = harness.start()
        res = drv.watch_like_gui()
        assert res.get("success") is True

        state_page = _wait_plane_nonempty(drv, "state", time.time() + 15.0)
        assert state_page["success"] is True
        assert state_page["count"] > 0, "живая система обязана публиковать state.changed под watch_like_gui"

        # Тот же push state.changed фан-аутится по дельте в telemetry-плоскость
        # (events.py: классификация «state.changed → state целиком + telemetry поштучно») —
        # доказано ТЕМ ЖЕ источником, отдельного ожидания не требуется.
        telemetry_page = drv.events_page(plane="telemetry")
        assert telemetry_page["success"] is True
        assert telemetry_page["count"] > 0, "telemetry-плоскость — производная от тех же дельт, что state"
    finally:
        harness.stop()


@pytest.mark.harness_smoke
def test_watch_like_gui_quiet_planes_are_recipe_property_not_bug_live() -> None:
    """Тишина ui/errors — свойство рецепта headless region_pipeline, не баг проводки."""
    harness = BackendHarness(with_base=True, port=_PORT)
    try:
        drv = harness.start()
        assert drv.watch_like_gui().get("success") is True

        # Дать системе прожить немного времени: если бы ui/errors ЧТО-ТО производили,
        # у них было бы окно на это (не ждём наполнения — тишина здесь ОЖИДАЕМА).
        time.sleep(2.0)

        errors_page = drv.events_page(plane="errors")
        ui_page = drv.events_page(plane="ui")
        assert errors_page["success"] is True
        assert ui_page["success"] is True
        # НЕ ассертим ненуль (BCTL-ADR-007 запрещает выдумывать ненуль там, где его нет) —
        # ассертим именно то, что архитектурно гарантировано для ЭТОГО рецепта:
        assert ui_page["count"] == 0, "headless-прогон без единого клика не может дать ui.event"
        assert errors_page["count"] == 0, "здоровый region_pipeline без внедрённых сбоев не пишет в ErrorManager"
    finally:
        harness.stop()
