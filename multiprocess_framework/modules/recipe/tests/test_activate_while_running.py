# -*- coding: utf-8 -*-
"""Task 1.5 (system-run-state) — слепой тест: отказ ``topology.apply`` в ``running`` доходит до ``recipe.activate``.

Написано ДО реализации гейта по наблюдаемым требованиям брифа (DESIGN/FILES, ``plans/**`` не читались).

Контракт (из брифа): ``recipe.activate`` собран ``build_recipe_service`` (``multiprocess_prototype/orchestrator.py``)
над ``pm._cmd_topology_apply``; в ``running`` PM отказывает ``{"success": False, "error": "running", "message":
«сначала ОСТАНОВИТЬ»}`` — отказ не теряется: он виден вызывающему ``recipe.activate``, топология и активный рецепт
прежние. Реализация ``RecipeService`` не меняется.

Допущения тестера (полный список — в отчёте):
  * ``RecipeService`` НЕ кладёт отказ PM в корень ответа: по докстрингу сервиса это ``{"success": False, "error":
    "apply_failed", "apply": <ответ PM>}``; поэтому ``error == "running"`` ищется в ``reply["apply"]`` (корневой
    ``error`` не сверяется — расхождение с формулировкой брифа вынесено в отчёт);
  * манифест и каталог рецептов — во ``tmp_path`` (реальный ``app.yaml`` и ``app.state.yaml`` не трогаются), рецепт —
    копия ``bridge_synth.yaml`` прототипа; импорт прототипа ленивый, внутри теста (как в
    ``test_lifecycle_command_classes``);
  * PM — из обвязки гейта ``process_manager_module/tests/test_run_apply_gate.py`` (``running`` через ``_run_apply``).
"""

from __future__ import annotations

import copy
import shutil
import threading
from pathlib import Path
from typing import Any

import pytest

from multiprocess_framework.modules.process_manager_module.tests.test_run_apply_gate import _effects, _pm_in

_REPO = Path(__file__).resolve().parents[4]
_RECIPE_SRC = _REPO / "multiprocess_prototype" / "recipes" / "bridge_synth.yaml"
_DEADLINE_S = 20.0


def _bounded(fn: Any) -> Any:
    box: dict[str, Any] = {}

    def run() -> None:
        try:
            box["value"] = fn()
        except BaseException as exc:  # noqa: BLE001
            box["error"] = exc

    th = threading.Thread(target=run, daemon=True, name="activate-running-bounded")
    th.start()
    th.join(_DEADLINE_S)
    assert not th.is_alive(), f"recipe.activate завис дольше {_DEADLINE_S} с"
    if "error" in box:
        raise box["error"]
    return box.get("value")


@pytest.mark.timeout(60)
def test_activate_reply_carries_running_error(tmp_path: Path) -> None:
    """``running``: ``recipe.activate`` -> ``success`` False; в ответе PM (``reply["apply"]``) ``error == "running"`` и
    «сначала ОСТАНОВИТЬ»; топология PM и ``run_event`` прежние, файл состояния активного рецепта не записан."""
    from multiprocess_prototype.orchestrator import build_recipe_service

    recipes = tmp_path / "recipes"
    recipes.mkdir()
    shutil.copy(_RECIPE_SRC, recipes / "bridge_synth.yaml")
    manifest = tmp_path / "app.yaml"
    manifest.write_text("name: demo_app\nversion: 1\npipeline: recipes/bridge_synth.yaml\nrecipes: recipes\n", "utf-8")

    pm = _pm_in("running")
    service = build_recipe_service(pm, manifest)
    assert service is not None
    before = _effects(pm)
    configs_before = copy.deepcopy(pm._process_configs)

    reply = _bounded(lambda: service.handlers()["recipe.activate"]({"name": "bridge_synth"}))

    assert isinstance(reply, dict), reply
    assert reply.get("success") is False, reply
    apply_reply = reply.get("apply")
    assert isinstance(apply_reply, dict), reply
    assert apply_reply.get("error") == "running", reply
    assert "сначала ОСТАНОВИТЬ" in str(apply_reply.get("message")), reply
    assert pm._process_configs == configs_before
    assert _effects(pm) == before
    assert not (tmp_path / "app.state.yaml").exists(), "активный рецепт записан несмотря на отказ"
