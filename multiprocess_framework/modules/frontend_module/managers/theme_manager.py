# frontend_module/managers/theme_manager.py
"""ThemeManager — generic менеджер тем оформления (QSS hot-reload + CSS-переменные).

Поддерживает два формата тем:
  1. Одиночный файл: styles/{name}.qss
  2. Модульная папка: styles/themes/{name}/*.qss (файлы склеиваются по алфавиту)

CSS-переменные:
  QSS-шаблоны содержат плейсхолдеры вида @имя_переменной (напр. @bg_deep).
  resolve_qss() подставляет значения из dict переменных.
  Дефолтные значения читаются из variables.yaml в папке темы; если файла нет —
  вызывается default_variables_provider (если задан) или возвращается {}.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Callable

import yaml

from PySide6.QtWidgets import QApplication
from ...logger_module.utils import FallbackLogger

_THEMES_SUBDIR = "themes"
_DEFAULT_THEME = "default"
_logger = FallbackLogger(__name__)


class ThemeManager:
    """Generic менеджер тем оформления — загрузка, переключение, hot-reload QSS.

    Конструктор принимает путь к styles/ снаружи — нет привязки к конкретному проекту.
    """

    def __init__(
        self,
        styles_dir: Path,
        *,
        default_variables_provider: Callable[[], dict[str, str]] | None = None,
    ) -> None:
        self._styles_dir = Path(styles_dir)
        self._themes_dir = self._styles_dir / _THEMES_SUBDIR
        self._current_theme: str = _DEFAULT_THEME
        self._default_variables_provider = default_variables_provider

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

        Модульная папка: все .qss файлы склеиваются в алфавитном порядке.
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
        Неизвестные плейсхолдеры остаются как есть (безопасный fallback).
        """
        def _replacer(m: re.Match) -> str:
            var_name = m.group(1)
            return variables.get(var_name, m.group(0))

        return re.sub(r"@(\w+)", _replacer, template)

    def read_default_variables(self, name: str) -> dict[str, str]:
        """Прочитать переменные темы из variables.yaml.

        Fallback-цепочка:
          1. Загрузить variables.yaml из папки модульной темы
          2. Если нет файла — вызвать default_variables_provider() если задан
          3. Иначе вернуть {}
        """
        # Базовые defaults от провайдера или пустой dict
        defaults: dict[str, str] = (
            self._default_variables_provider() if self._default_variables_provider is not None else {}
        )

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
                _logger.error("[ThemeManager] ошибка чтения %s: %s", yaml_path, exc)

        return defaults

    def apply_theme_with_variables(
        self, name: str, variables: dict[str, str]
    ) -> bool:
        """Применить тему с кастомными переменными к QApplication."""
        template = self.read_theme(name)
        if template is None:
            _logger.warning("[ThemeManager] тема '%s' не найдена", name)
            return False

        app = QApplication.instance()
        if app is None:
            _logger.error("[ThemeManager] QApplication не создан")
            return False

        qss = self.resolve_qss(template, variables)
        app.setStyleSheet(qss)
        self._current_theme = name
        return True

    def apply_theme(self, name: str) -> bool:
        """Применить тему к QApplication (hot-reload).

        Читает дефолтные переменные из variables.yaml, подставляет в QSS-шаблон.
        """
        variables = self.read_default_variables(name)
        return self.apply_theme_with_variables(name, variables)

    def reload_current(self) -> bool:
        """Перечитать и применить текущую тему (после редактирования файлов)."""
        return self.apply_theme(self._current_theme)
