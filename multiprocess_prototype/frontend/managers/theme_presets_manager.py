"""ThemePresetsManager — менеджер default и custom тем оформления.

Концепция:
    - **Default-темы** — read-only, хранятся в styles/themes/*/variables.yaml.
      Сканируются из подпапок: каждая папка с файлом variables.yaml — это тема.
    - **Custom-темы** — создаются пользователем, хранятся в data/custom_themes/*.yaml.
      Каждая тема — отдельный YAML-файл (stem = имя темы).

Сериализация через ThemeVariables (SchemaBase/Pydantic):
    - Чтение: yaml.safe_load → ThemeVariables.model_validate(data)
    - Запись: variables.model_dump() → yaml.dump(data, file)

API:
    mgr = ThemePresetsManager()
    mgr.list_defaults()                          # ["innotech_theme", ...]
    mgr.list_custom()                            # ["my_dark", ...]
    mgr.list_all()                               # [("innotech_theme", "default"), ...]
    mgr.get_variables("innotech_theme")          # ThemeVariables(...)
    mgr.save_custom("my_dark", variables)
    mgr.delete_custom("my_dark")                 # True / False
    mgr.copy_theme("innotech_theme", "my_copy")
    mgr.rename_custom("my_copy", "final_name")   # True / False
"""

from __future__ import annotations

import logging
from pathlib import Path

import yaml

from multiprocess_prototype.registers.theme.schemas import ThemeVariables

_logger = logging.getLogger(__name__)

# Пути по умолчанию относительно расположения этого файла:
#   managers/theme_presets_manager.py
#   → parent       = managers/
#   → parent.parent = frontend/
#   → parent.parent.parent = multiprocess_prototype/
_DEFAULT_STYLES_DIR = Path(__file__).resolve().parent.parent / "styles"
_DEFAULT_DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"

# Имя YAML-файла с переменными внутри каждой папки темы
_VARIABLES_FILENAME = "variables.yaml"

# Папка для пользовательских тем внутри data/
_CUSTOM_THEMES_SUBDIR = "custom_themes"


class ThemePresetsManager:
    """Менеджер тем оформления: default (read-only) + custom (CRUD).

    Default-темы берутся из styles/themes/*/variables.yaml.
    Custom-темы хранятся в data/custom_themes/*.yaml — по одному файлу на тему.
    Данные десериализуются в ThemeVariables и сериализуются обратно через Pydantic.
    """

    def __init__(
        self,
        styles_dir: Path | None = None,
        data_dir: Path | None = None,
    ) -> None:
        """
        Args:
            styles_dir: корень стилей (содержит подпапку themes/).
                        По умолчанию: multiprocess_prototype/frontend/styles/
            data_dir:   корень данных (будет создан custom_themes/ внутри).
                        По умолчанию: multiprocess_prototype/data/
        """
        self._default_dir: Path = (styles_dir or _DEFAULT_STYLES_DIR) / "themes"
        self._custom_dir: Path = (data_dir or _DEFAULT_DATA_DIR) / _CUSTOM_THEMES_SUBDIR

    # ------------------------------------------------------------------
    # Чтение
    # ------------------------------------------------------------------

    def list_defaults(self) -> list[str]:
        """Список имён default-тем (папки в styles/themes/ с variables.yaml).

        Имя темы = имя папки. Список отсортирован.

        Returns:
            Отсортированный список имён default-тем.
        """
        if not self._default_dir.is_dir():
            _logger.debug(
                "[ThemePresetsManager] каталог default-тем не найден: %s",
                self._default_dir,
            )
            return []

        names: list[str] = []
        for entry in self._default_dir.iterdir():
            if entry.is_dir() and (entry / _VARIABLES_FILENAME).is_file():
                names.append(entry.name)

        return sorted(names)

    def list_custom(self) -> list[str]:
        """Список имён custom-тем (файлы *.yaml в data/custom_themes/).

        Имя темы = stem файла (без расширения). Список отсортирован.

        Returns:
            Отсортированный список имён custom-тем.
        """
        if not self._custom_dir.is_dir():
            return []

        names: list[str] = [
            f.stem for f in self._custom_dir.iterdir()
            if f.is_file() and f.suffix in (".yaml", ".yml")
        ]
        return sorted(names)

    def list_all(self) -> list[tuple[str, str]]:
        """Все темы в формате [(name, kind), ...].

        kind = "default" для default-тем, "custom" для пользовательских.
        Порядок: сначала default (отсортированные), потом custom (отсортированные).

        Returns:
            Список кортежей (имя_темы, "default"|"custom").
        """
        result: list[tuple[str, str]] = []
        for name in self.list_defaults():
            result.append((name, "default"))
        for name in self.list_custom():
            result.append((name, "custom"))
        return result

    def get_variables(self, name: str) -> ThemeVariables:
        """Загрузить переменные темы по имени.

        Поиск: сначала в custom (data/custom_themes/{name}.yaml),
        затем в default (styles/themes/{name}/variables.yaml).
        Если тема не найдена ни там ни там — возвращает ThemeVariables() (defaults).

        Args:
            name: имя темы.

        Returns:
            Объект ThemeVariables с переменными темы.
        """
        # 1. Ищем в custom
        custom_path = self._custom_dir / f"{name}.yaml"
        if custom_path.is_file():
            return self._load_yaml(custom_path, name)

        # 2. Ищем в default
        default_path = self._default_dir / name / _VARIABLES_FILENAME
        if default_path.is_file():
            return self._load_yaml(default_path, name)

        # 3. Тема не найдена — возвращаем дефолтные значения
        _logger.warning(
            "[ThemePresetsManager] тема '%s' не найдена, возвращаются дефолтные значения",
            name,
        )
        return ThemeVariables()

    def is_default(self, name: str) -> bool:
        """Проверить, является ли тема default (read-only).

        Args:
            name: имя темы.

        Returns:
            True если тема найдена в styles/themes/{name}/variables.yaml.
        """
        default_path = self._default_dir / name / _VARIABLES_FILENAME
        return default_path.is_file()

    # ------------------------------------------------------------------
    # CRUD (только custom)
    # ------------------------------------------------------------------

    def get_parent(self, name: str) -> str:
        """Получить имя родительской темы для custom-темы.

        Родительская тема хранится в поле ``_parent`` YAML-файла.
        Для default-тем возвращает пустую строку (они сами являются корнями).

        Args:
            name: имя темы.

        Returns:
            Имя родительской темы или пустая строка.
        """
        if self.is_default(name):
            return ""
        custom_path = self._custom_dir / f"{name}.yaml"
        if not custom_path.is_file():
            return ""
        try:
            with open(custom_path, encoding="utf-8") as f:
                raw = yaml.safe_load(f)
            if isinstance(raw, dict):
                return str(raw.get("_parent", ""))
        except Exception:
            pass
        return ""

    def save_custom(
        self, name: str, variables: ThemeVariables, parent: str = "",
    ) -> None:
        """Сохранить (или перезаписать) custom-тему.

        Создаёт директорию data/custom_themes/ если не существует.
        Сериализует через variables.model_dump() → yaml.dump().
        Дополнительно сохраняет поле ``_parent`` — имя родительской темы.

        Args:
            name:      имя темы (будет именем файла без расширения).
            variables: объект ThemeVariables с переменными.
            parent:    имя родительской темы (опционально).
        """
        self._custom_dir.mkdir(parents=True, exist_ok=True)
        target = self._custom_dir / f"{name}.yaml"

        data = variables.model_dump()
        if parent:
            data["_parent"] = parent
        try:
            with open(target, "w", encoding="utf-8") as f:
                yaml.dump(data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
            _logger.debug("[ThemePresetsManager] custom-тема '%s' сохранена: %s", name, target)
        except Exception as exc:
            _logger.error(
                "[ThemePresetsManager] ошибка сохранения custom-темы '%s': %s", name, exc
            )
            raise

    def delete_custom(self, name: str) -> bool:
        """Удалить custom-тему.

        Args:
            name: имя темы.

        Returns:
            True если файл существовал и был удалён, False если не найден.
        """
        target = self._custom_dir / f"{name}.yaml"
        if not target.is_file():
            _logger.debug(
                "[ThemePresetsManager] delete_custom: тема '%s' не найдена (%s)",
                name,
                target,
            )
            return False

        try:
            target.unlink()
            _logger.debug("[ThemePresetsManager] custom-тема '%s' удалена", name)
            return True
        except Exception as exc:
            _logger.error(
                "[ThemePresetsManager] ошибка удаления custom-темы '%s': %s", name, exc
            )
            raise

    def copy_theme(self, src_name: str, dst_name: str) -> None:
        """Копировать тему (default или custom) в новый custom-файл.

        Загружает переменные из src_name (через get_variables) и сохраняет
        как новую custom-тему с именем dst_name. Родительская тема наследуется:
        для default-источника parent = src_name, для custom — его parent.

        Args:
            src_name: имя исходной темы (default или custom).
            dst_name: имя новой custom-темы.
        """
        variables = self.get_variables(src_name)
        # Определить parent: default → сама; custom → её parent
        if self.is_default(src_name):
            parent = src_name
        else:
            parent = self.get_parent(src_name) or src_name
        self.save_custom(dst_name, variables, parent=parent)
        _logger.debug(
            "[ThemePresetsManager] тема '%s' скопирована в custom '%s'",
            src_name,
            dst_name,
        )

    def rename_custom(self, old_name: str, new_name: str) -> bool:
        """Переименовать custom-тему (copy → delete old).

        Операция атомарна в смысле «создать новый файл, потом удалить старый».
        Если old_name не является custom-темой — ничего не делает и возвращает False.

        Args:
            old_name: текущее имя custom-темы.
            new_name: новое имя.

        Returns:
            True если переименование выполнено, False если old_name не custom-тема.
        """
        old_path = self._custom_dir / f"{old_name}.yaml"
        if not old_path.is_file():
            _logger.debug(
                "[ThemePresetsManager] rename_custom: '%s' не является custom-темой",
                old_name,
            )
            return False

        # Загружаем, сохраняем под новым именем (с parent), удаляем старый файл
        variables = self._load_yaml(old_path, old_name)
        parent = self.get_parent(old_name)
        self.save_custom(new_name, variables, parent=parent)
        self.delete_custom(old_name)
        _logger.debug(
            "[ThemePresetsManager] custom-тема переименована: '%s' → '%s'",
            old_name,
            new_name,
        )
        return True

    # ------------------------------------------------------------------
    # Вспомогательные методы
    # ------------------------------------------------------------------

    def _load_yaml(self, path: Path, name: str) -> ThemeVariables:
        """Загрузить ThemeVariables из YAML-файла.

        При любой ошибке (файл не читается, невалидные данные) возвращает
        ThemeVariables() с дефолтными значениями и логирует ошибку.

        Args:
            path: путь к YAML-файлу.
            name: имя темы (для сообщений в лог).

        Returns:
            Объект ThemeVariables.
        """
        try:
            with open(path, encoding="utf-8") as f:
                raw = yaml.safe_load(f)

            if not isinstance(raw, dict):
                _logger.warning(
                    "[ThemePresetsManager] тема '%s': ожидался dict, получен %s — "
                    "используются дефолтные значения",
                    name,
                    type(raw).__name__,
                )
                return ThemeVariables()

            return ThemeVariables.model_validate(raw)

        except Exception as exc:
            _logger.error(
                "[ThemePresetsManager] ошибка загрузки темы '%s' из %s: %s",
                name,
                path,
                exc,
            )
            return ThemeVariables()
