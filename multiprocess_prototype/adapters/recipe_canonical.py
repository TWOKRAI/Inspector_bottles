"""recipe_canonical.py — одна пара адаптеров сущностей прототипа и канонической формы рецепта (Task 1.1g).

Purpose:
    Канон — тело рецепта ``N(файл)`` (``RecipeManager.read_canonical``, design.md §10 п. 3). Сущности прототипа
    (``Recipe``, ``Topology``) переводятся в канон и обратно ЗДЕСЬ, на границе; вызывающий не строит рецепт целиком из
    модели. Правка модели переносится на ``base_doc`` дельтой
    ``apply_delta(base, M(base), M(edited), on_insert=minimize)``: всё, что вызывающий не менял, остаётся в канонической
    форме как есть.
    ``M`` — форма ``denormalize_recipe_dict(Recipe.to_dict())`` (meta поднята на верхний уровень).

Public API:
    ``denormalize_recipe_dict(data) -> dict`` — ``meta`` -> верхний уровень, порядок секций (Q2 Variant A);
    ``RecipeStoreFromManager._denormalize`` делегирует сюда.
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
    НЕ импортирует ``recipes.save`` / ``backend`` / ``adapters.stores.recipe_store``: ``recipes.save`` (Task 1.2)
    и ``RecipeStoreFromManager`` импортируют этот модуль.
    Файл читает backend-модель ``SystemBlueprint`` (умолчания другие, чем у доменной модели, design.md §10.2 В-П2):
    минимальная форма допустима, только если backend строит из неё то же, что из полной (поля ``ProcessConfig``,
    ``as_generic_config``, восстановленные конфиги плагинов, плоский конфиг плагина; ``adapters/tests/
    test_recipe_canonical.py`` на 22 рецептах). Плагины и воркеры минимизируются как сущности: полная запись плагина
    (``plugin_class: null``) хуже минимальной — ``_restore_plugin_configs`` не восстанавливает его конфиг.
"""

from __future__ import annotations

from typing import Any

from multiprocess_framework.modules.recipe.detect import has_top_level_blueprint
from multiprocess_framework.modules.recipe.yaml_io import apply_delta
from multiprocess_prototype.domain.entities.display import DisplayDefinition
from multiprocess_prototype.domain.entities.plugin import PluginInstance
from multiprocess_prototype.domain.entities.process import Process
from multiprocess_prototype.domain.entities.recipe import Recipe
from multiprocess_prototype.domain.entities.topology import Topology
from multiprocess_prototype.domain.entities.wire import Wire
from multiprocess_prototype.domain.entities.worker import WorkerSpec

__all__ = [
    "denormalize_recipe_dict",
    "minimize",
    "recipe_from_canonical",
    "recipe_to_canonical",
    "topology_to_canonical",
]

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


def denormalize_recipe_dict(data: dict[str, Any]) -> dict[str, Any]:
    """Денормализовать meta -> top-level для backward-compat с live YAML.

    Recipe.to_dict() выдаёт: {"meta": {"name": ..., "version": ..., ...}, "blueprint": ..., ...}
    Live YAML формат (v2):   {"name": ..., "version": ..., "blueprint": ..., ...}

    Решение Q2 Variant A: извлечь все поля из meta на верхний уровень,
    удалить ключ meta. Это сохраняет совместимость с:
    - RecipeManager.read_recipe() (raw YAML reader)
    - Recipe.from_dict() (понимает оба формата)
    - Legacy GUI reader'ы (ожидают top-level name/version)

    Порядок ключей в результирующем YAML для читаемости (Task 1.3):
        1. meta-поля (name, version, description, created_at)
        2. displays — определения дисплеев (DisplayDefinition, top-level секция)
        3. blueprint — топология рецепта
        4. остальные поля (active_services, display_bindings, gui_positions, ...)

    Поле ``displays`` (tuple[DisplayDefinition,...]) сохраняется автоматически
    через denormalized.update(result) — оно НЕ входит в meta и не требует
    специальной обработки. Явное позиционирование перед blueprint — только
    для читаемости итогового YAML файла.
    """
    result = dict(data)
    meta = result.pop("meta", {})
    if isinstance(meta, dict):
        # 1. Сначала meta-поля (верхний уровень, читаемость YAML)
        denormalized: dict[str, Any] = {}
        for key in ("name", "version", "description", "created_at"):
            if key in meta:
                denormalized[key] = meta[key]
        # Оставшиеся meta-поля (если появятся в будущем)
        for key, value in meta.items():
            if key not in denormalized:
                denormalized[key] = value

        # 2. displays — определения дисплеев рецепта (перед blueprint для читаемости).
        #    Сохраняется как top-level секция, НЕ внутри blueprint.
        #    (blueprint.displays = привязки node_id→display_id — другая секция)
        if "displays" in result:
            denormalized["displays"] = result.pop("displays")

        # 3. blueprint — топология (процессы, провода, привязки дисплеев)
        if has_top_level_blueprint(result):
            denormalized["blueprint"] = result.pop("blueprint")

        # 4. Остальные поля Recipe (active_services, display_bindings, gui_positions, ...)
        denormalized.update(result)
        return denormalized
    return result


def _model_form(recipe: Recipe) -> dict:
    """``M``: ``denormalize_recipe_dict(Recipe.to_dict())`` (meta на верхнем уровне)."""
    return denormalize_recipe_dict(recipe.to_dict())


def _topology_view(blueprint: dict) -> dict:
    """Секции ``processes/wires/displays`` модели ``Topology`` (полная форма) — то, что правит редактор топологии."""
    dumped = Topology.from_dict(blueprint).to_dict()
    return {key: dumped[key] for key in ("processes", "wires", "displays")}


def _dump_minimal(entity: Any, value: Any) -> Any:
    """Минимальная форма сущности; не mapping возвращается как есть. Невалидная сущность — ``ValidationError``."""
    if not isinstance(value, dict):
        return value
    return entity.model_validate(value).model_dump(mode="json", exclude_defaults=True)
