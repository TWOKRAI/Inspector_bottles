"""drop_display_name.py — разовый мигратор: удалить display_name из blueprint.displays.

Удаляет поле ``display_name`` из каждой записи ``blueprint.displays`` во всех
YAML-рецептах в директории. Работает через ruamel round-trip (``update_yaml_preserving``),
сохраняя комментарии и структуру файлов.

Контекст:
    Phase 0 плана ``plans/displays-in-recipe/plan.md``.
    DisplayInstance получает extra='forbid' без display_name (Task 0.3).
    Сначала мигрируем YAML, затем удаляем поле из entity.

Использование:
    python -m multiprocess_prototype.recipes.migrations.drop_display_name

    или программно:
        from multiprocess_prototype.recipes.migrations.drop_display_name import run_migration
        run_migration(recipes_dir)

Refs: plans/displays-in-recipe/plan.md
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# Путь к директории рецептов относительно этого файла:
# migrations/ -> recipes/ (родитель двух уровней)
_DEFAULT_RECIPES_DIR = Path(__file__).resolve().parent.parent


def _drop_display_name_from_yaml(path: Path) -> bool:
    """Удалить display_name из blueprint.displays в одном YAML-файле через ruamel.

    Возвращает True если файл был изменён, False — если поле не найдено или пропущен.
    """
    try:
        from ruamel.yaml import YAML
        from ruamel.yaml.comments import CommentedMap
    except ModuleNotFoundError as exc:
        raise RuntimeError("ruamel.yaml не установлен. Установи зависимости: `uv sync`") from exc

    yaml = YAML()
    yaml.preserve_quotes = True
    yaml.width = 4096
    yaml.indent(mapping=2, sequence=4, offset=2)

    with path.open("r", encoding="utf-8") as f:
        data = yaml.load(f)

    if not isinstance(data, (dict, CommentedMap)):
        logger.warning("Пропуск %s — не является словарём", path.name)
        return False

    blueprint = data.get("blueprint")
    if not isinstance(blueprint, (dict, CommentedMap)):
        logger.debug("Пропуск %s — нет секции blueprint", path.name)
        return False

    displays = blueprint.get("displays")
    if not isinstance(displays, list) or not displays:
        logger.debug("Пропуск %s — нет записей в blueprint.displays", path.name)
        return False

    # Проверяем, есть ли хоть один display_name для удаления
    has_display_name = any(isinstance(item, (dict, CommentedMap)) and "display_name" in item for item in displays)
    if not has_display_name:
        logger.debug("Пропуск %s — display_name не найден в blueprint.displays", path.name)
        return False

    # Удаляем display_name из каждой записи
    changed_count = 0
    for item in displays:
        if isinstance(item, (dict, CommentedMap)) and "display_name" in item:
            del item["display_name"]
            changed_count += 1

    logger.info("Обновлён %s — удалён display_name из %d записей", path.name, changed_count)

    # Записываем обратно через update_yaml_preserving (сохраняет комментарии файла)
    # Передаём весь blueprint как top-level ключ, чтобы merge сохранил остальные поля
    from multiprocess_prototype.recipes.yaml_io import update_yaml_preserving

    update_yaml_preserving(path, {"blueprint": blueprint})
    return True


def run_migration(recipes_dir: Path | None = None) -> list[Path]:
    """Запустить миграцию на всех YAML-рецептах в директории.

    Args:
        recipes_dir: директория с рецептами. По умолчанию — ``multiprocess_prototype/recipes/``.

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
            if _drop_display_name_from_yaml(path):
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
        print(f"Миграция завершена. Изменено файлов: {len(modified)}")
        for p in modified:
            print(f"  - {p.name}")
    else:
        print("Миграция завершена. Файлы без изменений (display_name не найден).")
