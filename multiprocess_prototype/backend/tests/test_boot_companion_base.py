# -*- coding: utf-8 -*-
"""ФР-3 на дороге BOOT прототипа: спутник не въезжает в базу слоя L2.

Находка X2-1 сквозного ревью Ф5, класс «дефект чинится на одном пути из двух».

``SystemBuilder.build()`` домерживал спутник рецепта прямо в
``bp_dict["observability"]`` — то есть в секцию, из которой ассемблер режет
БАЗУ слоя (``proc_dict["config"]["observability_override"]``). База живёт в
конфиге процесса и переживает пересборки, а слой заменяется целиком: значит
ключ, снятый оператором из спутника, оставался в базе НАВСЕГДА. Generic-дорога
(``app_module.SystemBuilder``) спутника не мержила и тот же ключ теряла честно —
одна система вела себя двумя способами.

Здесь дёргается НАСТОЯЩИЙ ``build()`` (headless, без камеры) — потому что
проверяемое место живёт именно в нём, а не в ассемблере: ассемблер спутника не
читал никогда, и тест против него был бы зелёным при живом дефекте.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any, Dict

import pytest

from multiprocess_framework.modules.process_module.configs.observability_companion import (
    companion_path,
    compose_recipe_layer,
    write_companion,
)
from multiprocess_framework.modules.process_module.configs.observability_layers import (
    OVERRIDE_CONFIG_KEY,
    RECIPE_PATH_CONFIG_KEY,
)
from multiprocess_prototype.backend.config.schemas import SystemConfig
from multiprocess_prototype.backend.launch import SystemBuilder

#: Минимальный blueprint: один процесс, ни плагинов, ни проводов.
_BLUEPRINT: Dict[str, Any] = {
    "name": "frq3",
    "processes": [{"process_name": "seg", "process_class": "some.module.SegApp", "plugins": []}],
    "wires": [],
    "observability": {"processes": {"seg": {"log_level": "WARNING"}}},
}

#: Секция рецепта из блюпринта — ожидание записано ЛИТЕРАЛОМ, не производным
#: от кода: сверка «база == то, что положил build» согласна с любым ответом.
_RECIPE_SLICE = {"log_level": "WARNING"}


class _Svc:
    """Процесс-заглушка, читающая конфиг ровно так же, как настоящий."""

    def __init__(self, name: str, config: Dict[str, Any]) -> None:
        self.name = name
        self._config = config

    def get_config(self, key, default=None):
        return self._config.get(key, default)


@pytest.fixture()
def recipe(tmp_path: Path) -> Path:
    path = tmp_path / "frq3.yaml"
    path.write_text("name: frq3\n", encoding="utf-8")
    return path


def _build_seg_config(recipe_path: Path) -> Dict[str, Any]:
    """Настоящий boot прототипа → ``config`` процесса ``seg``."""
    sys_config = SystemConfig.model_validate({"discovery": {"auto_discover": False}})
    launcher = SystemBuilder(
        sys_config=sys_config,
        blueprint=copy.deepcopy(_BLUEPRINT),
        topology_path=recipe_path,
    ).build()
    procs = dict(launcher._processes)
    return procs["seg"]["config"]


def test_boot_base_carries_the_recipe_slice_without_the_companion(recipe) -> None:
    """База в конфиге процесса = долька РЕЦЕПТА, буквально."""
    write_companion(recipe, {"processes": {"seg": {"log_level": "DEBUG"}}})

    config = _build_seg_config(recipe)

    assert config[OVERRIDE_CONFIG_KEY] == _RECIPE_SLICE, (
        f"спутник въехал в базу слоя на boot: {config[OVERRIDE_CONFIG_KEY]}"
    )
    assert config[RECIPE_PATH_CONFIG_KEY] == str(recipe), "адрес рецепта не доехал — спутник некому будет прочитать"


def test_live_companion_still_wins_on_boot(recipe) -> None:
    """Вторая половина пары: чистая база не отменяет спутника.

    Без неё тест выше зелен и у реализации «спутник вообще не применять» — то
    есть страж стерёг бы отсутствие механизма. Слой собирает та же
    ``compose_recipe_layer``, которую зовёт процесс на старте.
    """
    write_companion(recipe, {"processes": {"seg": {"log_level": "DEBUG"}}})

    config = _build_seg_config(recipe)
    body, source = compose_recipe_layer(_Svc("seg", config))

    assert body == {"log_level": "DEBUG"}, f"живой спутник не применён на boot: {body}"
    assert source == str(companion_path(recipe))


def test_key_removed_from_the_companion_returns_to_the_recipe_on_boot(recipe) -> None:
    """ГЛАВНОЕ утверждение ФР-3 на дороге boot: снятый ключ исчезает.

    База собирается ОДИН раз (boot, спутник ещё жив), а слой пересобирается без
    новой базы — так работает раздача правки спутника (watcher оркестратора шлёт
    ``observability_recipe_reload``, секция по проводу не едет). Пересобери мы
    базу заново, дефект бы не проявился: он живёт именно в том, что база
    ПЕРЕЖИВАЕТ пересборку слоя, а слой заменяется целиком.
    """
    write_companion(recipe, {"processes": {"seg": {"log_level": "DEBUG"}}})
    config = _build_seg_config(recipe)
    svc = _Svc("seg", config)
    assert compose_recipe_layer(svc)[0] == {"log_level": "DEBUG"}

    # Оператор снял ключ из спутника; процесс живёт со СВОЕЙ базой.
    write_companion(recipe, {"processes": {"seg": {}}})

    assert compose_recipe_layer(svc)[0] == _RECIPE_SLICE, "снятый из спутника ключ воскрес из базы слоя"


def test_broken_companion_refuses_the_boot_loudly(recipe) -> None:
    """Отказ на boot остаётся ровно в одной точке — в ``build()``.

    Каждый процесс дальше глотает эту ошибку в лог (падать на старте из-за
    спутника ему нельзя), поэтому если ``build()`` перестанет читать файл,
    битый спутник станет строкой в логе — то есть «сохранённые настройки не
    применились» будет выясняться сравнением файлов.
    """
    companion_path(recipe).write_text("observability: [не словарь\n", encoding="utf-8")

    with pytest.raises(Exception):
        _build_seg_config(recipe)
