"""displays_to_recipe.py — разовый мигратор: перенести определения из displays.yaml в рецепты.

Читает ``multiprocess_prototype/backend/config/displays.yaml`` и для каждого рецепта
в директории ``multiprocess_prototype/recipes/`` добавляет top-level секцию ``displays``
с теми дисплеями, на которые есть ссылки в ``blueprint.displays``.

К каждому определению добавляются render-дефолты:
    - position: {x: 0, y: 0}
    - fit: contain
    - scale: 100
    - rotate: 0
    - flip: none
    (crop намеренно не добавляется — default None по спеке раздела 2)

После успешной миграции всех рецептов ``displays.yaml`` переименовывается
в ``displays.yaml.bak`` — помечается устаревшим.

Важно:
    - Используется ``update_yaml_preserving`` (ruamel round-trip) — комментарии сохраняются.
    - НЕ использует yaml.safe_dump (потеря комментариев — был прецедент).
    - Рецепты без ``blueprint.displays`` — пропускаются (нет привязок → не нужно определений).
    - Рецепт ссылается на display_id, которого нет в displays.yaml → создаётся заглушка
      с дефолтами и лог-warning (рецепт не должен оставаться с висячей ссылкой).
    - displays.yaml отсутствует → no-op (лог-info).

Использование:
    python -m multiprocess_prototype.recipes.migrations.displays_to_recipe

    или программно:
        from multiprocess_prototype.recipes.migrations.displays_to_recipe import run_migration
        run_migration()

Refs: plans/displays-in-recipe/plan.md, Task 3.1
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

# Путь к директории рецептов: migrations/ -> recipes/ (один уровень вверх)
_DEFAULT_RECIPES_DIR = Path(__file__).resolve().parent.parent

# Путь к displays.yaml относительно корня проекта
_DISPLAYS_YAML = Path(__file__).resolve().parent.parent.parent / "backend" / "config" / "displays.yaml"

# Render-дефолты (спека раздел 2, раздел 10, task-инструкция)
_RENDER_DEFAULTS: dict = {
    "position": {"x": 0, "y": 0},
    "fit": "contain",
    "scale": 100,
    "rotate": 0,
    "flip": "none",
}


def _load_displays_yaml(path: Path) -> dict[str, dict]:
    """Загрузить displays.yaml → dict by id.

    Returns:
        Словарь {display_id: определение_dict}.
        Пустой dict если файл отсутствует.
    """
    if not path.exists():
        logger.info("displays_to_recipe: displays.yaml не найден (%s) — no-op", path)
        return {}

    import yaml

    with path.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    if not raw or not isinstance(raw, dict):
        logger.warning("displays_to_recipe: displays.yaml пустой или невалидный")
        return {}

    displays_list = raw.get("displays", [])
    if not isinstance(displays_list, list):
        logger.warning("displays_to_recipe: ключ 'displays' не является списком")
        return {}

    result: dict[str, dict] = {}
    for item in displays_list:
        if not isinstance(item, dict):
            continue
        display_id = item.get("id")
        if not display_id:
            logger.warning("displays_to_recipe: запись без 'id' — пропускаем: %s", item)
            continue
        result[display_id] = item

    logger.info("displays_to_recipe: загружено %d определений из displays.yaml", len(result))
    return result


def _collect_referenced_display_ids(recipe_data: dict) -> set[str]:
    """Собрать множество display_id, на которые ссылается blueprint.displays.

    Args:
        recipe_data: Загруженный YAML рецепта (dict).

    Returns:
        Set display_id из всех записей blueprint.displays.
    """
    blueprint = recipe_data.get("blueprint")
    if not isinstance(blueprint, dict):
        return set()

    bp_displays = blueprint.get("displays")
    if not isinstance(bp_displays, list) or not bp_displays:
        return set()

    ids: set[str] = set()
    for item in bp_displays:
        if isinstance(item, dict):
            did = item.get("display_id")
            if did:
                ids.add(did)

    return ids


def _build_display_entry(display_id: str, source_def: dict | None) -> dict:
    """Собрать определение дисплея с render-дефолтами.

    Args:
        display_id: ID дисплея.
        source_def: Определение из displays.yaml или None (создаётся заглушка).

    Returns:
        Dict определения дисплея с полями + render-дефолтами.
    """
    if source_def is None:
        # Создаём заглушку с дефолтными SHM-полями
        logger.warning(
            "displays_to_recipe: display_id '%s' не найден в displays.yaml — "
            "создаём заглушку с дефолтами (рецепт не должен оставаться с висячей ссылкой)",
            display_id,
        )
        entry: dict = {
            "id": display_id,
            "name": display_id,
            "width": 1280,
            "height": 720,
            "format": "BGR",
            "fps_limit": 30.0,
            "ring_buffer_blocks": 3,
        }
    else:
        # Копируем SHM-поля из displays.yaml (только известные поля)
        entry = {
            "id": source_def.get("id", display_id),
            "name": source_def.get("name", display_id),
            "width": source_def.get("width", 1280),
            "height": source_def.get("height", 720),
            "format": source_def.get("format", "BGR"),
            "fps_limit": source_def.get("fps_limit", 30.0),
            "ring_buffer_blocks": source_def.get("ring_buffer_blocks", 3),
        }

    # Добавляем render-дефолты (crop намеренно не добавляем — default None)
    entry.update(_RENDER_DEFAULTS)
    return entry


def _migrate_recipe_file(path: Path, displays_by_id: dict[str, dict]) -> bool:
    """Добавить секцию displays в один YAML-рецепт.

    Пропускает рецепты без blueprint.displays.
    Не перезаписывает, если секция displays уже есть (идемпотентность).

    Args:
        path: Путь к YAML-файлу рецепта.
        displays_by_id: Словарь определений из displays.yaml {id: dict}.

    Returns:
        True если файл был изменён.
    """
    try:
        from ruamel.yaml import YAML
        from ruamel.yaml.comments import CommentedMap
    except ModuleNotFoundError as exc:
        raise RuntimeError("ruamel.yaml не установлен. Установи зависимости: `uv sync`") from exc

    yaml_rt = YAML()
    yaml_rt.preserve_quotes = True
    yaml_rt.width = 4096
    yaml_rt.indent(mapping=2, sequence=4, offset=2)

    with path.open("r", encoding="utf-8") as f:
        data = yaml_rt.load(f)

    if not isinstance(data, (dict, CommentedMap)):
        logger.warning("Пропуск %s — не является словарём", path.name)
        return False

    # Собираем referenced display_ids из blueprint.displays
    referenced_ids = _collect_referenced_display_ids(data)
    if not referenced_ids:
        logger.debug("Пропуск %s — нет привязок в blueprint.displays", path.name)
        return False

    # Проверяем, есть ли уже секция displays (идемпотентность)
    existing_displays = data.get("displays")
    if existing_displays is not None and isinstance(existing_displays, list) and len(existing_displays) > 0:
        # Секция уже есть — проверяем, нужно ли добавить новые id
        existing_ids = {item.get("id") for item in existing_displays if isinstance(item, dict)}
        new_ids = referenced_ids - existing_ids
        if not new_ids:
            logger.debug("Пропуск %s — секция displays уже содержит все нужные id", path.name)
            return False
        # Есть новые id — добавляем их к существующим
        logger.info(
            "Рецепт %s: секция displays существует, добавляем недостающие id: %s",
            path.name,
            new_ids,
        )
        new_entries = [_build_display_entry(did, displays_by_id.get(did)) for did in sorted(new_ids)]
        existing_displays.extend(new_entries)
    else:
        # Секции нет — создаём новую
        entries = [_build_display_entry(did, displays_by_id.get(did)) for did in sorted(referenced_ids)]
        logger.info(
            "Рецепт %s: добавляем секцию displays (%d записей): %s",
            path.name,
            len(entries),
            sorted(referenced_ids),
        )

    # Записываем через update_yaml_preserving (merge, комментарии сохраняются)
    from multiprocess_prototype.recipes.yaml_io import update_yaml_preserving

    if existing_displays is not None and isinstance(existing_displays, list) and len(existing_displays) > 0:
        # Уже модифицированный список (extend выше)
        update_yaml_preserving(path, {"displays": existing_displays})
    else:
        update_yaml_preserving(path, {"displays": entries})

    return True


def run_migration(
    recipes_dir: Path | None = None,
    displays_yaml_path: Path | None = None,
    *,
    rename_displays_yaml: bool = True,
) -> list[Path]:
    """Запустить миграцию: перенести определения из displays.yaml в рецепты.

    Args:
        recipes_dir: Директория с YAML-рецептами.
                     По умолчанию — ``multiprocess_prototype/recipes/``.
        displays_yaml_path: Путь к displays.yaml.
                             По умолчанию — стандартный путь в backend/config/.
        rename_displays_yaml: Переименовать displays.yaml → displays.yaml.bak после миграции.
                               По умолчанию True.

    Returns:
        Список Path файлов, которые были изменены.
    """
    if recipes_dir is None:
        recipes_dir = _DEFAULT_RECIPES_DIR
    if displays_yaml_path is None:
        displays_yaml_path = _DISPLAYS_YAML

    recipes_dir = Path(recipes_dir)
    displays_yaml_path = Path(displays_yaml_path)

    if not recipes_dir.exists():
        raise FileNotFoundError(f"Директория рецептов не найдена: {recipes_dir}")

    # Загружаем определения из displays.yaml
    displays_by_id = _load_displays_yaml(displays_yaml_path)
    if not displays_by_id and displays_yaml_path.exists():
        # Файл есть, но пустой
        logger.warning("displays_to_recipe: displays.yaml пустой — нет данных для миграции")

    # Мигрируем каждый YAML-рецепт
    yaml_files = sorted(recipes_dir.glob("*.yaml"))
    if not yaml_files:
        logger.warning("displays_to_recipe: YAML-файлы рецептов не найдены в %s", recipes_dir)
        return []

    changed: list[Path] = []
    for path in yaml_files:
        try:
            if _migrate_recipe_file(path, displays_by_id):
                changed.append(path)
        except Exception as exc:
            logger.error("Ошибка при обработке %s: %s", path.name, exc)
            raise

    # Переименовываем displays.yaml → .bak
    if rename_displays_yaml and displays_yaml_path.exists():
        bak_path = displays_yaml_path.with_suffix(".yaml.bak")
        os.rename(displays_yaml_path, bak_path)
        logger.info("displays_to_recipe: displays.yaml переименован в %s", bak_path.name)
    elif not displays_yaml_path.exists():
        logger.info("displays_to_recipe: displays.yaml не найден — пропускаем переименование")

    return changed


if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    recipes_dir_arg = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    modified = run_migration(recipes_dir_arg)

    if modified:
        print(f"Миграция завершена. Изменено файлов: {len(modified)}")
        for p in modified:
            print(f"  - {p.name}")
    else:
        print("Миграция завершена. Файлы без изменений (нет привязок или displays уже есть).")
