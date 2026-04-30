# multiprocess_prototype/frontend/managers/theme_manager.py
"""ThemeManager — менеджер тем оформления (QSS hot-reload + CSS-переменные).

Поддерживает два формата тем:
  1. Одиночный файл: styles/{name}.qss
  2. Модульная папка: styles/themes/{name}/*.qss (файлы склеиваются по алфавиту)

CSS-переменные:
  QSS-шаблоны содержат плейсхолдеры вида @имя_переменной (напр. @bg_deep).
  resolve_qss() подставляет значения из dict переменных.
  Дефолтные значения читаются из variables.yaml в папке темы (fallback — ThemeVariables).

Использование:
    from multiprocess_prototype.frontend.managers.theme_manager import ThemeManager

    tm = ThemeManager()
    tm.apply_theme("innotech_theme")
    names = tm.available_themes()     # ["innotech_theme", ...]
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

from PySide6.QtWidgets import QApplication

_STYLES_DIR = Path(__file__).resolve().parent.parent / "styles"
_THEMES_SUBDIR = "themes"
_DEFAULT_THEME = "innotech_theme"


class ThemeManager:
    """Менеджер тем оформления — загрузка, переключение, hot-reload QSS."""

    def __init__(self, styles_dir: Path | None = None) -> None:
        self._styles_dir = styles_dir or _STYLES_DIR
        self._themes_dir = self._styles_dir / _THEMES_SUBDIR
        self._current_theme: str = _DEFAULT_THEME

    @property
    def styles_dir(self) -> Path:
        """Директория styles/."""
        return self._styles_dir

    @property
    def themes_dir(self) -> Path:
        """Директория styles/themes/ (модульные темы)."""
        return self._themes_dir

    @property
    def current_theme(self) -> str:
        """Имя текущей активной темы."""
        return self._current_theme

    def available_themes(self) -> list[str]:
        """Список доступных тем, отсортированный.

        Собирается из:
          - папок в styles/themes/ (модульные)
          - .qss файлов в styles/ (одиночные)
        Дубликаты исключаются (папка приоритетнее файла).
        """
        names: set[str] = set()
        # Модульные темы (папки)
        if self._themes_dir.is_dir():
            for d in self._themes_dir.iterdir():
                if d.is_dir() and any(d.glob("*.qss")):
                    names.add(d.name)
        # Одиночные файлы
        if self._styles_dir.is_dir():
            for f in self._styles_dir.glob("*.qss"):
                names.add(f.stem)
        return sorted(names)

    def read_theme(self, name: str) -> str | None:
        """Прочитать QSS темы. Приоритет: модульная папка > одиночный файл.

        Модульная папка: все .qss файлы склеиваются в алфавитном порядке
        (нумерация 01_, 02_ ... гарантирует правильный каскад).
        """
        # 1) Модульная папка
        theme_dir = self._themes_dir / name
        if theme_dir.is_dir():
            parts = sorted(theme_dir.glob("*.qss"))
            if parts:
                chunks = []
                for p in parts:
                    try:
                        chunks.append(p.read_text(encoding="utf-8"))
                    except OSError:
                        continue
                if chunks:
                    return "\n".join(chunks)

        # 2) Одиночный файл
        single = self._styles_dir / f"{name}.qss"
        if single.is_file():
            try:
                return single.read_text(encoding="utf-8")
            except OSError:
                return None

        return None

    def theme_parts(self, name: str) -> list[str]:
        """Список файлов-частей модульной темы (для UI: показать структуру)."""
        theme_dir = self._themes_dir / name
        if not theme_dir.is_dir():
            return []
        return sorted(p.name for p in theme_dir.glob("*.qss"))

    def is_modular(self, name: str) -> bool:
        """True если тема хранится как модульная папка."""
        theme_dir = self._themes_dir / name
        return theme_dir.is_dir() and any(theme_dir.glob("*.qss"))

    # ------------------------------------------------------------------
    # CSS-переменные: чтение, подстановка, применение
    # ------------------------------------------------------------------

    @staticmethod
    def resolve_qss(template: str, variables: dict[str, str]) -> str:
        """Подставить значения переменных в QSS-шаблон.

        Плейсхолдеры вида @имя_переменной заменяются на соответствующее значение.
        Плейсхолдеры внутри кавычек ("@font_family") тоже обрабатываются.
        Неизвестные плейсхолдеры остаются как есть (безопасный fallback).
        """
        def _replacer(m: re.Match) -> str:
            var_name = m.group(1)
            return variables.get(var_name, m.group(0))

        return re.sub(r"@(\w+)", _replacer, template)

    def read_default_variables(self, name: str) -> dict[str, str]:
        """Прочитать переменные темы из variables.yaml (fallback — ThemeVariables).

        Ищет файл variables.yaml в папке модульной темы.
        Если файла нет или тема одиночная — возвращает дефолтные из ThemeVariables.
        """
        from multiprocess_prototype.registers.theme.schemas import (
            get_default_variables,
        )

        defaults = get_default_variables()

        # Попробовать загрузить variables.yaml из папки темы
        yaml_path = self._themes_dir / name / "variables.yaml"
        if yaml_path.is_file():
            try:
                with open(yaml_path, encoding="utf-8") as f:
                    loaded = yaml.safe_load(f)
                if isinstance(loaded, dict):
                    # Обновляем дефолты значениями из файла
                    defaults.update(
                        {k: str(v) for k, v in loaded.items() if k in defaults}
                    )
            except Exception as exc:
                print(f"[ThemeManager] ошибка чтения {yaml_path}: {exc}")

        return defaults

    def apply_theme_with_variables(
        self, name: str, variables: dict[str, str]
    ) -> bool:
        """Применить тему с кастомными переменными.

        Читает QSS-шаблон, подставляет переменные, применяет к QApplication.
        """
        template = self.read_theme(name)
        if template is None:
            print(f"[ThemeManager] тема '{name}' не найдена")
            return False

        app = QApplication.instance()
        if app is None:
            print("[ThemeManager] QApplication не создан")
            return False

        qss = self.resolve_qss(template, variables)
        app.setStyleSheet(qss)
        self._current_theme = name
        return True

    def apply_theme(self, name: str) -> bool:
        """Применить тему к QApplication (hot-reload).

        Обратно совместимый метод: читает дефолтные переменные из variables.yaml,
        подставляет в QSS-шаблон и применяет.

        Returns:
            True если тема успешно применена, False при ошибке.
        """
        variables = self.read_default_variables(name)
        return self.apply_theme_with_variables(name, variables)

    def reload_current(self) -> bool:
        """Перечитать и применить текущую тему (после редактирования файлов)."""
        return self.apply_theme(self._current_theme)
