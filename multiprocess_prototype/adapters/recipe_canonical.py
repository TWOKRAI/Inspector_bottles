"""recipe_canonical.py — одна пара адаптеров сущностей прототипа и канонической формы рецепта (Task 1.1g).

Purpose:
    Канон — тело рецепта ``N(файл)`` (``RecipeManager.read_canonical``, design.md §10 п. 3). Сущности прототипа
    (``Recipe``, ``Topology``) переводятся в канон и обратно ЗДЕСЬ, на границе; вызывающий не строит рецепт целиком из
    модели. Правка модели переносится на ``base_doc`` дельтой
    ``apply_delta(base, M(base), M(edited), on_insert=minimize)``: всё, что вызывающий не менял, остаётся в канонической
    форме как есть.
    ``M`` — форма ``RecipeStoreFromManager._denormalize(Recipe.to_dict())`` (meta поднята на верхний уровень).

Public API:
    ``recipe_from_canonical(doc) -> Recipe``.
    ``recipe_to_canonical(recipe, base_doc) -> dict`` — ``base_doc`` не мутируется; ``recipe_to_canonical(
    recipe_from_canonical(d), d) == d`` для любого канонического ``d``.
    ``topology_to_canonical(topology, base_doc) -> dict`` — то же для ``blueprint.processes/wires/displays``;
    ``topology`` — dict ``blueprint`` (остальные секции ``base_doc``, ``blueprint.metadata`` и т. п. не трогаются).
    ``minimize(path, value) -> value`` — ``on_insert`` дельты: вставляемое поддерево сущности (``Process``, ``Wire``,
    ``DisplayDefinition``) теряет поля, равные умолчанию модели (``model_dump(exclude_defaults=True)``). Программа
    умолчаний не пишет (design.md §10 п. 5). Правка пользователя НА умолчание — изменённый лист, ``minimize`` её не
    видит (``apply_delta`` зовёт ``on_insert`` только для вставки целого поддерева) и она пишется явно.

Stability:
    Новый публичный модуль слоя адаптеров (new-lite). Зависит от ``domain`` и ``multiprocess_framework.modules.recipe``;
    НЕ импортирует ``recipes.save`` / ``backend`` (``recipes.save`` в Task 1.2 импортирует этот модуль).
    Файл читает backend-модель ``SystemBlueprint`` (умолчания другие, чем у доменной модели, design.md §10.2 В-П2):
    минимальная форма допустима, только если backend строит из неё то же, что из полной (поля ``ProcessConfig``,
    ``as_generic_config``, восстановленные конфиги плагинов, плоский конфиг плагина; ``adapters/tests/
    test_recipe_canonical.py`` на 22 рецептах). Плагины и воркеры минимизируются как сущности: полная запись плагина
    (``plugin_class: null``) хуже минимальной — ``_restore_plugin_configs`` не восстанавливает его конфиг.
"""

from __future__ import annotations

from typing import Any

from multiprocess_framework.modules.recipe.yaml_io import apply_delta
from multiprocess_prototype.adapters.stores.recipe_store import RecipeStoreFromManager
from multiprocess_prototype.domain.entities.display import DisplayDefinition
from multiprocess_prototype.domain.entities.plugin import PluginInstance
from multiprocess_prototype.domain.entities.process import Process
from multiprocess_prototype.domain.entities.recipe import Recipe
from multiprocess_prototype.domain.entities.topology import Topology
from multiprocess_prototype.domain.entities.wire import Wire
from multiprocess_prototype.domain.entities.worker import WorkerSpec

__all__ = ["minimize", "recipe_from_canonical", "recipe_to_canonical", "topology_to_canonical"]

# Путь списка сущностей (индекс элемента — ``*``) -> тип элемента.
_LIST_ENTITIES: dict[tuple, Any] = {
    ("displays",): DisplayDefinition,
    ("blueprint", "processes"): Process,
    ("blueprint", "wires"): Wire,
    ("blueprint", "processes", "*", "plugins"): PluginInstance,
    ("blueprint", "processes", "*", "workers"): WorkerSpec,
}


def recipe_from_canonical(doc: dict) -> Recipe:
    """Модель рецепта из канонического тела.

    Pre: ``doc`` — ``N(файл)`` (корень mapping, валидный рецепт). Post: новый ``Recipe``; ``doc`` не мутируется.
    """
    return Recipe.from_dict(doc)


def recipe_to_canonical(recipe: Recipe, base_doc: dict) -> dict:
    """Канон ``base_doc`` с правкой модели ``recipe``; поддеревья вставки проходят ``minimize``.

    Pre: ``base_doc`` — канон (``N(файл)``), ``recipe`` выведен из ``base_doc`` (``recipe_from_canonical``) и правлен:
    до-состояние дельты считается из ``base_doc``, поэтому чужая правка в ``base_doc``, которой нет в ``recipe``, будет
    откачена (защита — ``expected_rev`` менеджера).
    Post: новый dict; ``base_doc`` не мутируется; ключи и значения, которых правка не касалась, не меняются.
    """
    before = _model_form(recipe_from_canonical(base_doc))
    after = _model_form(recipe)
    return apply_delta(base_doc, before, after, on_insert=minimize)


def topology_to_canonical(topology: dict, base_doc: dict) -> dict:
    """Канон ``base_doc`` с правкой ``blueprint.processes/wires/displays`` из dict ``topology``.

    Pre: ``base_doc`` — канон с ``blueprint``, ``topology`` выведен из ``base_doc["blueprint"]`` и правлен; без
    ``blueprint`` в ``base_doc`` секция вставляется целиком (включая пустые ``wires``/``displays``).
    Post: новый dict; ``base_doc`` не мутируется; остальные секции рецепта и ``blueprint.metadata`` не меняются.
    """
    before = {"blueprint": _topology_view(base_doc.get("blueprint") or {})}
    after = {"blueprint": _topology_view(topology)}
    return apply_delta(base_doc, before, after, on_insert=minimize)


def minimize(path: tuple, value: Any) -> Any:
    """``on_insert``: убрать из вставляемого поддерева поля, равные умолчанию доменной модели.

    Pre: ``path`` — путь вставляемого поддерева в канонической форме (кортеж ключей и индексов), ``value`` — его полная
    форма из ``M(recipe)``.
    Post: новое значение, ``value`` не мутируется. Сущность определяется по пути: ``displays[i]``
    (``DisplayDefinition``),
    ``blueprint.processes[i]`` (``Process``), ``blueprint.wires[i]`` (``Wire``), ``blueprint.processes[i].plugins[j]``
    (``PluginInstance``), ``blueprint.processes[i].workers[j]`` (``WorkerSpec``); список сущностей и ``blueprint``
    обходятся по элементам. Вложенные сущности внутри процесса минимизируются вместе с ним. Прочее — как есть.
    """
    if path == ("blueprint",) and isinstance(value, dict):
        return {key: minimize(("blueprint", key), item) for key, item in value.items()}
    entity = _LIST_ENTITIES.get(_shape(path))
    if entity is not None and isinstance(value, list):
        return [_dump_minimal(entity, item) for item in value]
    entity = _LIST_ENTITIES.get(_shape(path[:-1])) if path and isinstance(path[-1], int) else None
    if entity is not None:
        return _dump_minimal(entity, value)
    return value


def _shape(path: tuple) -> tuple:
    """Путь с индексами, заменёнными на ``*``."""
    return tuple("*" if isinstance(part, int) else part for part in path)


def _model_form(recipe: Recipe) -> dict:
    """``M``: ``RecipeStoreFromManager._denormalize(Recipe.to_dict())`` (meta на верхнем уровне)."""
    return RecipeStoreFromManager._denormalize(recipe.to_dict())


def _topology_view(blueprint: dict) -> dict:
    """Секции ``processes/wires/displays`` модели ``Topology`` (полная форма) — то, что правит редактор топологии."""
    dumped = Topology.from_dict(blueprint).to_dict()
    return {key: dumped[key] for key in ("processes", "wires", "displays")}


def _dump_minimal(entity: Any, value: Any) -> Any:
    """Минимальная форма сущности; не mapping возвращается как есть. Невалидная сущность — ``ValidationError``."""
    if not isinstance(value, dict):
        return value
    return entity.model_validate(value).model_dump(mode="json", exclude_defaults=True)
