"""Карта «путь -> модуль»: загрузка modules.yaml и резолвер (Task 0.3, plans/2026-10-04_atlas).

Формат и правила — plans/2026-10-04_atlas/tasks/0.3.md. Только stdlib и PyYAML,
кода проекта не импортирует: модуль читают адаптеры атласа и хуки коммита.

Элемент `paths` с «/» на конце — префикс каталога, без «/» — точный файл.
Побеждает САМЫЙ ДЛИННЫЙ совпавший элемент, порядок строк в списке не важен.
"""

from __future__ import annotations

from pathlib import Path

import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]
_REQUIRED_KEYS = ("id", "paths", "layer", "tier", "docs", "parent")

OTHER = "other"


def load_modules(path: str | Path = "modules.yaml") -> list[dict]:
    """Читает modules.yaml. Относительный путь считается от корня репозитория, не от cwd.

    Нет файла -> FileNotFoundError. Неверная `version`, нет обязательного ключа строки
    или пустая строка в `paths` -> ValueError (в тексте ключ и 0-based индекс строки,
    значение не печатается).
    """
    file = Path(path)
    if not file.is_absolute():
        file = _REPO_ROOT / file
    data = yaml.safe_load(file.read_text(encoding="utf-8"))
    version = data.get("version") if isinstance(data, dict) else None
    if type(version) is not int or version != 1:  # bool (True == 1) не годится
        raise ValueError(f"{file.name}: ключ 'version' должен быть равен 1")
    rows = data.get("modules")
    if not isinstance(rows, list):
        raise ValueError(f"{file.name}: ключ 'modules' должен быть списком")
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError(f"{file.name}: строка {index} не является словарём")
        for key in _REQUIRED_KEYS:
            if key not in row:
                raise ValueError(f"{file.name}: в строке {index} нет ключа '{key}'")
        if not isinstance(row["paths"], list) or any(not isinstance(p, str) or p == "" for p in row["paths"]):
            raise ValueError(f"{file.name}: в строке {index} ключ 'paths' содержит пустой или нестроковый элемент")
    return rows


def resolve(rel_path: str, modules: list[dict]) -> str:
    """id строки с самым длинным совпавшим элементом `paths`, иначе "other". Не бросает.

    `modules` — список, который вернул load_modules.
    """
    path = str(rel_path).replace("\\", "/")
    best_id, best_len = OTHER, 0
    for row in modules:
        for element in row["paths"]:
            matched = path.startswith(element) if element.endswith("/") else path == element
            if matched and len(element) > best_len:
                best_id, best_len = row["id"], len(element)
    return best_id
