# -*- coding: utf-8 -*-
"""canonicalize_gui_positions.py — свернуть дубль gui_positions к одной секции.

Контекст (Ф4.8, mini-GATE, plans/2026-07-06_constructor-master/plan.md):
    Аудит дублей 2026-07-10 (analysis.md, п.5) зафиксировал: рецепт v3 пишет
    ``gui_positions`` (позиции узлов node_id → [x, y]) ДВАЖДЫ —

    - ``blueprint.metadata.gui_positions`` — КАНОНИЧЕСКАЯ копия. Именно её читает
      живой путь редактора (``LayoutController.load_topology_from_config`` →
      ``metadata.get("gui_positions")``) и cold-start бэкенда (``unwrap_recipe``
      копирует ``raw["blueprint"]`` целиком, включая ``metadata``).
    - top-level ``gui_positions`` — legacy-копия «для обратной совместимости»
      (см. комментарий ``LayoutController.save_to_active_recipe``: «Top-level
      gui_positions оставляем для обратной совместимости (Recipes-tab + старые
      рецепты)»). На практике НИ ОДИН живой read-путь её не читает:
      ``unwrap_recipe`` берёт позиции только из ``raw["blueprint"]`` (top-level
      ``gui_positions`` не упоминается вообще); ``RecipesPresenter.on_save``
      читает ``topo.get("gui_positions", {})`` из ``TopologyRepository.load()``,
      но тот отдаёт ``Topology.to_dict()``, где positions лежат под
      ``metadata.gui_positions`` — top-level "gui_positions" там всегда {}.

    Обе копии пишутся ОДНИМ save (``save_to_active_recipe``), но раздельно —
    отсюда возможен дрейф значений. На живых рецептах (``phone_sketch``,
    ``hikvision_letter_robot``) дрейф уже есть: 2 из 20 узлов в
    ``hikvision_letter_robot.yaml`` имеют РАЗНЫЕ координаты в canonical- и
    top-level-копии (какая из них "верна" — решает canonical, т.к. только она
    участвует в реальной загрузке).

    Дубль ``displays`` (bindings в ``blueprint.displays`` vs definitions в
    top-level ``displays``, тот же аудит) сюда НЕ входит: это не дубль
    содержимого (bindings — node_id/display_id, definitions — id/width/height/…),
    а коллизия ИМЕНИ ключа на двух уровнях. Схлопнуть их в «одну секцию»
    означало бы либо потерять данные, либо переименовать ключи и обновить
    ~10 читающих мест (``unwrap_recipe``, ``RecipesPresenter``,
    ``RecipeStoreFromManager._denormalize``, domain ``Recipe``/``Topology``) —
    структурная миграция за рамками dict→dict канонизации 4.8. См. diff-отчёт
    ``plans/2026-07-06_constructor-master/f4.8-canonicalization-diff.md``.

Решение (doc_type/версия):
    Зарегистрирован как ``@migration("recipe.layout", from_=1, to=2)`` — та же
    инфраструктура C2 (ADR-RCP-003), что и остальные шаги ``recipes/migrations/``.
    ``from_``/``to`` здесь — ВНУТРЕННЯЯ бухгалтерия реестра миграций («шаг
    применён / не применён»), НЕ поле ``version:`` самого файла рецепта: то
    поле — произвольный номер итерации автора рецепта (``phone_sketch.yaml``
    несёт ``version: 1`` при этом являясь v3-blueprint форматом по
    ``has_top_level_blueprint``) и НЕ трогается этим шагом. Нормализация формы,
    не смена версии рецепта.

Шаг — pure dict→dict (``canonicalize_gui_positions``), не читает и не пишет
файлы. Отдельно — ``run_migration()`` (file-writer, ruamel round-trip, тот же
паттерн что ``drop_display_name.py``/``displays_to_recipe.py`` в этом пакете)
для будущего одобренного применения к реальным файлам: Ф4.8 — это mini-GATE
владельца, применение к ``multiprocess_prototype/recipes/*.yaml`` НЕ входит в
эту задачу и НЕ вызывается отсюда.

Использование (после одобрения владельцем):
    python -m multiprocess_prototype.recipes.migrations.canonicalize_gui_positions

    или программно:
        from multiprocess_prototype.recipes.migrations.canonicalize_gui_positions import (
            run_migration,
        )
        run_migration()

Refs: plans/2026-07-06_constructor-master/plan.md (задача 4.8),
      plans/2026-07-06_constructor-master/f4.8-canonicalization-diff.md
"""

from __future__ import annotations

import copy
import logging
from collections.abc import MutableMapping
from pathlib import Path
from typing import Any

from multiprocess_framework.modules.recipe.migrations import migration

logger = logging.getLogger(__name__)

# doc_type реестра миграций (C2) — namespace, отличает этот шаг от
# "recipe.config_snapshot" (backend/state/recipes/migrations/v1_to_v2.py) и
# "recipe.file_format" (format_v1_to_v2.py в этом же пакете).
DOC_TYPE = "recipe.layout"

# Путь к директории рецептов относительно этого файла: migrations/ -> recipes/
_DEFAULT_RECIPES_DIR = Path(__file__).resolve().parent.parent


def _canonicalize_gui_positions_inplace(data: MutableMapping) -> bool:
    """Свернуть дубль gui_positions на месте (мутирует ``data``).

    Работает как с plain dict (in-memory pure-путь), так и с ruamel
    ``CommentedMap`` (file writer — сохраняет комментарии): обе поддерживают
    протокол ``MutableMapping`` (get/[]=/del/in), поэтому одна и та же логика
    обслуживает оба сценария без дублирования.

    Правила:
      - нет вложенного ``blueprint`` (не v3-рецепт) — канонизировать нечего,
        no-op;
      - canonical (``blueprint.metadata.gui_positions``) пуст/отсутствует, а
        top-level ``gui_positions`` непуст — top-level ПОДНИМАЕТСЯ в canonical
        (данные не теряются даже для рецептов, где canonical ещё не заполнен);
      - canonical непуст — он побеждает БЕЗ СЛИЯНИЯ (это единственная копия,
        которую читает живой путь редактора/cold-start; top-level мог
        разъехаться и правкой не считается источником истины);
      - top-level ``gui_positions`` (после переноса, если он был) — удаляется.

    Returns:
        True если ``data`` была изменена (что-то поднято и/или удалено).
    """
    blueprint = data.get("blueprint")
    if not isinstance(blueprint, MutableMapping):
        return False

    top_level_positions = data.get("gui_positions")
    changed = False

    metadata = blueprint.get("metadata")
    canonical_positions = metadata.get("gui_positions") if isinstance(metadata, MutableMapping) else None

    if not canonical_positions and top_level_positions:
        if not isinstance(metadata, MutableMapping):
            metadata = type(blueprint)()
            blueprint["metadata"] = metadata
        metadata["gui_positions"] = copy.deepcopy(top_level_positions)
        changed = True

    if "gui_positions" in data:
        del data["gui_positions"]
        changed = True

    return changed


@migration(DOC_TYPE, from_=1, to=2)
def canonicalize_gui_positions(data: dict) -> dict:
    """Свернуть дубль ``gui_positions`` (top-level + ``blueprint.metadata``) в одну секцию.

    Чистая функция: исходный ``data`` не мутируется, возвращается новый dict
    (``copy.deepcopy`` — как ``migrate_v1_to_v2`` в ``format_v1_to_v2.py``).

    Идемпотентна: повторное применение к уже канонизированным данным — no-op
    (top-level ``gui_positions`` уже отсутствует, ``blueprint.metadata.gui_positions``
    не трогается вторым проходом).

    Args:
        data: raw dict рецепта (v3-blueprint, top-level) ИЛИ произвольный
            dict без вложенного ``blueprint`` — тогда возвращается без изменений
            (graceful: шаг не про v3-рецепты не трогает).

    Returns:
        Новый dict — копия ``data`` с единственной канонической секцией
        ``blueprint.metadata.gui_positions``.
    """
    if not isinstance(data, dict):
        return data
    result = copy.deepcopy(data)
    _canonicalize_gui_positions_inplace(result)
    return result


# ---------------------------------------------------------------------------
# File writer (Phase F4.8 follow-up — применяется ТОЛЬКО после одобрения
# владельцем diff-отчёта; НЕ вызывается из этого модуля/задачи автоматически).
# ---------------------------------------------------------------------------


def _make_yaml() -> Any:
    """Сконфигурированный ruamel YAML (round-trip) — та же настройка, что
    ``drop_display_name.py``/``displays_to_recipe.py``/``yaml_io._make_yaml``.
    """
    try:
        from ruamel.yaml import YAML
    except ModuleNotFoundError as exc:  # pragma: no cover - зависит от окружения
        raise RuntimeError("ruamel.yaml не установлен. Установи зависимости: `uv sync`") from exc

    yaml = YAML()
    yaml.preserve_quotes = True
    yaml.width = 4096
    yaml.indent(mapping=2, sequence=4, offset=2)
    return yaml


def _migrate_recipe_file(path: Path) -> bool:
    """Канонизировать один YAML-рецепт на диске (ruamel round-trip, комментарии целы).

    В отличие от ``update_yaml_preserving`` (merge-семантика, только SET ключей),
    здесь нужно УДАЛИТЬ top-level ``gui_positions`` — поэтому документ читается,
    мутируется на месте (``_canonicalize_gui_positions_inplace`` — тот же helper,
    что и pure-путь) и пишется обратно целиком, как в ``drop_display_name.py``.

    Returns:
        True если файл был изменён.
    """
    from ruamel.yaml.comments import CommentedMap

    yaml = _make_yaml()
    with path.open("r", encoding="utf-8") as f:
        data = yaml.load(f)

    if not isinstance(data, (dict, CommentedMap)):
        logger.warning("Пропуск %s — не является словарём", path.name)
        return False

    changed = _canonicalize_gui_positions_inplace(data)
    if not changed:
        logger.debug("Пропуск %s — gui_positions уже канонизирован", path.name)
        return False

    with path.open("w", encoding="utf-8") as f:
        yaml.dump(data, f)

    logger.info("Рецепт %s канонизирован (gui_positions → одна секция)", path.name)
    return True


def run_migration(recipes_dir: Path | None = None) -> list[Path]:
    """Запустить канонизацию на всех YAML-рецептах в директории.

    НЕ вызывается автоматически (Ф4.8 — mini-GATE, применение к реальным
    рецептам — отдельный шаг ПОСЛЕ одобрения владельцем byte-diff отчёта).

    Args:
        recipes_dir: директория с рецептами. По умолчанию —
            ``multiprocess_prototype/recipes/``.

    Returns:
        Список Path файлов, которые были изменены.
    """
    if recipes_dir is None:
        recipes_dir = _DEFAULT_RECIPES_DIR

    recipes_dir = Path(recipes_dir)
    if not recipes_dir.exists():
        raise FileNotFoundError(f"Директория рецептов не найдена: {recipes_dir}")

    yaml_files = sorted(recipes_dir.glob("*.yaml"))
    if not yaml_files:
        logger.warning("YAML-файлы рецептов не найдены в %s", recipes_dir)
        return []

    changed: list[Path] = []
    for path in yaml_files:
        try:
            if _migrate_recipe_file(path):
                changed.append(path)
        except Exception as exc:
            logger.error("Ошибка при обработке %s: %s", path.name, exc)
            raise

    return changed


if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    recipes_dir_arg = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    modified = run_migration(recipes_dir_arg)

    if modified:
        print(f"Канонизация завершена. Изменено файлов: {len(modified)}")
        for p in modified:
            print(f"  - {p.name}")
    else:
        print("Канонизация завершена. Файлы без изменений (gui_positions уже канонизирован).")


__all__ = ["canonicalize_gui_positions", "run_migration", "DOC_TYPE"]
