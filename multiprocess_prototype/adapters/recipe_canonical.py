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
    поле остаётся в минимальной форме только если ``backend_load(minimize(x)) == backend_load(x)`` на 22 рецептах
    (``adapters/tests/test_recipe_canonical.py``). Расхождение сегодня одно: ``Process.plugins`` — backend хранит
    ``plugins`` как ``list[dict]``, и минимальный плагин (без ``config: {}``) не равен полному; поэтому ``plugins``
    вставляется как есть (полная форма ``PluginInstance``), остальные поля процесса минимизируются.
"""

from __future__ import annotations

from typing import Any

from multiprocess_framework.modules.recipe.yaml_io import apply_delta
from multiprocess_prototype.adapters.stores.recipe_store import RecipeStoreFromManager
from multiprocess_prototype.domain.entities.display import DisplayDefinition
from multiprocess_prototype.domain.entities.process import Process
from multiprocess_prototype.domain.entities.recipe import Recipe
from multiprocess_prototype.domain.entities.topology import Topology
from multiprocess_prototype.domain.entities.wire import Wire

__all__ = ["minimize", "recipe_from_canonical", "recipe_to_canonical", "topology_to_canonical"]

# Топологические секции canon-пути ``blueprint.<секция>`` -> тип сущности в списке.
_BLUEPRINT_ENTITIES: dict[str, Any] = {"processes": Process, "wires": Wire}
# Поля процесса, которые backend читает сырым ``dict`` — остаются в полной форме (см. Stability).
_PROCESS_RAW_FIELDS = ("plugins",)


def recipe_from_canonical(doc: dict) -> Recipe:
    """Модель рецепта из канонического тела. Pre: ``doc`` — ``N(файл)`` (корень mapping). Post: новый ``Recipe``."""
    return Recipe.from_dict(doc)


def recipe_to_canonical(recipe: Recipe, base_doc: dict) -> dict:
    """Канон ``base_doc`` с правкой модели ``recipe``; поддеревья вставки проходят ``minimize``.

    Post: новый dict; ``base_doc`` не мутируется; ключи и значения, которых правка не касалась, не меняются.
    """
    before = _model_form(recipe_from_canonical(base_doc))
    after = _model_form(recipe)
    return apply_delta(base_doc, before, after, on_insert=minimize)


def topology_to_canonical(topology: dict, base_doc: dict) -> dict:
    """Канон ``base_doc`` с правкой ``blueprint.processes/wires/displays`` из dict ``topology``.

    Post: новый dict; ``base_doc`` не мутируется; остальные секции рецепта и ``blueprint.metadata`` не меняются.
    """
    before = {"blueprint": _topology_view(base_doc.get("blueprint") or {})}
    after = {"blueprint": _topology_view(topology)}
    return apply_delta(base_doc, before, after, on_insert=minimize)


def minimize(path: tuple, value: Any) -> Any:
    """``on_insert``: убрать из вставляемого поддерева поля, равные умолчанию доменной модели.

    ``path`` — путь поддерева в канонической форме. Сущность — по пути: ``blueprint.processes[i]`` (``Process``),
    ``blueprint.wires[i]`` (``Wire``), ``displays[i]`` (``DisplayDefinition``); контейнер выше (список, ``blueprint``)
    обходится по элементам. Прочее возвращается как есть. Исходное ``value`` не мутируется.
    """
    if path == ("displays",) and isinstance(value, list):
        return [_dump_minimal(DisplayDefinition, item) for item in value]
    if len(path) == 2 and path[0] == "displays":
        return _dump_minimal(DisplayDefinition, value)
    if path == ("blueprint",) and isinstance(value, dict):
        return {key: minimize(("blueprint", key), item) for key, item in value.items()}
    if len(path) >= 2 and path[0] == "blueprint" and path[1] in _BLUEPRINT_ENTITIES:
        entity = _BLUEPRINT_ENTITIES[path[1]]
        if len(path) == 2 and isinstance(value, list):
            return [_dump_minimal(entity, item) for item in value]
        if len(path) == 3:
            return _dump_minimal(entity, value)
    return value


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
    model = entity.model_validate(value)
    minimal = model.model_dump(mode="json", exclude_defaults=True)
    if entity is Process:
        full = model.model_dump(mode="json")
        for field in _PROCESS_RAW_FIELDS:
            if field in minimal:
                minimal[field] = full[field]
    return minimal
