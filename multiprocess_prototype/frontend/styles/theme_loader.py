"""theme_loader — загрузка и применение темы оформления для v2.

Публичный API:
    load_theme(theme_name)        — загрузить QSS с подставленными переменными
    apply_default_theme(app)      — применить innotech_theme к QApplication
    available_themes()            — список доступных тем
    create_theme_manager()        — фабрика ThemeManager (для расширенного использования)
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

from multiprocess_framework.modules.frontend_module.managers.theme_manager import ThemeManager

if TYPE_CHECKING:
    from PySide6.QtWidgets import QApplication

# Директория styles/ в v2 (родительская для этого файла)
_STYLES_DIR = Path(__file__).resolve().parent


def create_theme_manager() -> ThemeManager:
    """Создать ThemeManager с путём к v2 styles/ и провайдером дефолтных переменных.

    default_variables_provider = get_default_variables из registers/theme/schemas
    — без него read_default_variables() возвращает {} (фильтрует по пустому defaults).
    """
    from multiprocess_prototype.registers.theme.schemas import get_default_variables

    return ThemeManager(_STYLES_DIR, default_variables_provider=get_default_variables)


def _load_variables(theme_name: str) -> dict[str, str]:
    """Загрузить переменные из variables.yaml для указанной темы.

    Читает yaml напрямую — обходит ограничение ThemeManager.read_default_variables,
    которое фильтрует только ключи из defaults (пустой dict без провайдера).
    """
    yaml_path = _STYLES_DIR / "themes" / theme_name / "variables.yaml"
    if not yaml_path.is_file():
        return {}
    with open(yaml_path, encoding="utf-8") as f:
        loaded = yaml.safe_load(f)
    if not isinstance(loaded, dict):
        return {}
    return {k: str(v) for k, v in loaded.items()}


def load_theme(theme_name: str = "innotech_theme") -> str:
    """Загрузить QSS тему, подставив переменные из variables.yaml.

    Шаги:
      1. Читает variables.yaml из папки темы
      2. Читает main.qss (или склеенные .qss-файлы для модульных тем)
      3. Заменяет @variable_name на значения из yaml
      4. Возвращает готовый QSS

    Raises:
        FileNotFoundError: если тема не найдена.
    """
    tm = create_theme_manager()
    template = tm.read_theme(theme_name)
    if template is None:
        raise FileNotFoundError(f"Тема '{theme_name}' не найдена в {_STYLES_DIR / 'themes'}")

    variables = _load_variables(theme_name)
    # Подставляем @variable_name → значение; неизвестные плейсхолдеры остаются
    resolved = re.sub(
        r"@(\w+)",
        lambda m: variables.get(m.group(1), m.group(0)),
        template,
    )
    return resolved


def _register_theme_fonts(theme_name: str) -> None:
    """Зарегистрировать OTF/TTF шрифты из папки темы в QFontDatabase."""
    from PySide6.QtGui import QFontDatabase

    theme_dir = _STYLES_DIR / "themes" / theme_name
    for ext in ("*.otf", "*.ttf", "*.OTF", "*.TTF"):
        for font_path in theme_dir.glob(ext):
            QFontDatabase.addApplicationFont(str(font_path))


def apply_default_theme(app: "QApplication") -> None:
    """Применить дефолтную тему innotech_theme к QApplication."""
    _register_theme_fonts("innotech_theme")
    qss = load_theme("innotech_theme")
    app.setStyleSheet(qss)


def available_themes() -> list[str]:
    """Список доступных тем (сканирует директорию themes/)."""
    tm = create_theme_manager()
    return tm.available_themes()
