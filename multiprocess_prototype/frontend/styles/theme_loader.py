"""theme_loader — загрузка и применение темы оформления для v2.

Публичный API:
    load_theme(theme_name)        — загрузить QSS с подставленными переменными
    apply_default_theme(app)      — применить innotech_theme к QApplication
    available_themes()            — список доступных тем
    create_theme_manager()        — фабрика ThemeManager (для расширенного использования)

Стратегия загрузки:
    - Если тема содержит components/ → manifest-сборка (base.qss + STYLE_MANIFEST)
    - Иначе → fallback на read_theme() (алфавитный порядок .qss файлов)
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


def _has_components(theme_name: str) -> bool:
    """Проверить наличие components/ в папке темы."""
    return (_STYLES_DIR / "themes" / theme_name / "components").is_dir()


def _get_manifest() -> list[str] | None:
    """Загрузить STYLE_MANIFEST; None если модуль недоступен."""
    try:
        from multiprocess_prototype.frontend.styles.style_manifest import STYLE_MANIFEST

        return STYLE_MANIFEST
    except ImportError:
        return None


def load_theme(theme_name: str = "innotech_theme") -> str:
    """Загрузить QSS тему, подставив переменные из variables.yaml.

    Стратегия:
      - Если тема содержит components/ и manifest доступен →
        manifest-сборка (base.qss + компонентные файлы в порядке каскада)
      - Иначе → fallback на read_theme() (все .qss по алфавиту)

    Raises:
        FileNotFoundError: если тема не найдена.
    """
    tm = create_theme_manager()
    manifest = _get_manifest()

    if manifest is not None and _has_components(theme_name):
        template = tm.read_theme_by_manifest(theme_name, manifest)
    else:
        template = tm.read_theme(theme_name)

    if template is None:
        raise FileNotFoundError(f"Тема '{theme_name}' не найдена в {_STYLES_DIR / 'themes'}")

    variables = _load_variables(theme_name)
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


def apply_default_theme(app: "QApplication", theme_name: str = "innotech_theme") -> None:
    """Применить тему к QApplication (имя — из главного конфига app.yaml).

    Использует manifest-сборку если components/ доступна,
    иначе fallback через load_theme().

    Args:
        app:        QApplication.
        theme_name: Имя темы (стилевого рецепта) из ``styles.active`` манифеста.
    """
    _register_theme_fonts(theme_name)

    manifest = _get_manifest()
    if manifest is not None and _has_components(theme_name):
        tm = create_theme_manager()
        variables = _load_variables(theme_name)
        if not tm.apply_theme_by_manifest(theme_name, manifest, variables):
            # fallback если manifest-сборка не удалась
            qss = load_theme(theme_name)
            app.setStyleSheet(qss)
    else:
        qss = load_theme(theme_name)
        app.setStyleSheet(qss)


def available_themes() -> list[str]:
    """Список доступных тем (сканирует директорию themes/)."""
    tm = create_theme_manager()
    return tm.available_themes()
