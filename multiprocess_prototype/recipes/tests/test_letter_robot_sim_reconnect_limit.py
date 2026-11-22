"""Рецепт letter_robot_sim: у робота и ПЧ снят лимит переподключения (решение владельца 2026-11-20).

Путь ``params`` от рецепта до драйвера доказывает ``Plugins/hub/device_hub/tests/test_recipe_params_reach_driver_acceptance.py``.
Здесь — только содержимое рецепта: ключ стоит в ``params`` обеих записей и равен литералу 0.
"""

from pathlib import Path

import yaml

from multiprocess_prototype.recipes.devices_sync import extract_recipe_devices

_RECIPE = Path(__file__).resolve().parents[1] / "letter_robot_sim.yaml"


def test_robot_and_vfd_have_unlimited_reconnect() -> None:
    devices = {d["id"]: d for d in extract_recipe_devices(yaml.safe_load(_RECIPE.read_text(encoding="utf-8")))}
    assert devices["robot_main"]["params"]["max_reconnect_attempts"] == 0
    assert devices["vfd_belt"]["params"]["max_reconnect_attempts"] == 0
