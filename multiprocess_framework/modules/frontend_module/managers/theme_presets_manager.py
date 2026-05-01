# frontend_module/managers/theme_presets_manager.py
"""ThemePresetsManager — хранилище пользовательских пресетов переменных тем.

Пресеты хранятся в YAML-файле.
Каждый пресет — плоский dict[str, str] с именованными переменными.

API:
    mgr = ThemePresetsManager(data_dir=Path("/path/to/data"))
    mgr.list_presets()                # ["default", "high-contrast"]
    mgr.get_preset("default")         # {"bg_deep": "#1a1f28", ...}
    mgr.save_preset("my", data)       # сохранить / перезаписать
    mgr.delete_preset("my")           # удалить
    mgr.rename_preset("my", "new")    # переименовать
"""

from __future__ import annotations

from pathlib import Path

import yaml

from ...logger_module.utils import FallbackLogger

_logger = FallbackLogger(__name__)

_PRESETS_FILE = "theme_presets.yaml"


class ThemePresetsManager:
    """Менеджер пресетов переменных тем (YAML-backed).

    Путь к директории данных передаётся снаружи — нет привязки к конкретному проекту.
    """

    def __init__(self, data_dir: Path) -> None:
        self._data_dir = Path(data_dir)
        self._file = self._data_dir / _PRESETS_FILE
        self._cache: dict[str, dict[str, str]] | None = None

    # ------------------------------------------------------------------
    # Внутренние методы
    # ------------------------------------------------------------------

    def _load(self) -> dict[str, dict[str, str]]:
        """Загрузить пресеты из YAML-файла (с кэшированием)."""
        if self._cache is not None:
            return self._cache

        if not self._file.is_file():
            self._cache = {}
            return self._cache

        try:
            with open(self._file, encoding="utf-8") as f:
                data = yaml.safe_load(f)
            if isinstance(data, dict):
                # Убедимся что каждый пресет — dict[str, str]
                self._cache = {
                    str(k): {str(kk): str(vv) for kk, vv in v.items()}
                    for k, v in data.items()
                    if isinstance(v, dict)
                }
            else:
                self._cache = {}
        except Exception as exc:
            _logger.error("[ThemePresetsManager] ошибка чтения %s: %s", self._file, exc)
            self._cache = {}

        return self._cache

    def _save(self) -> None:
        """Записать кэш обратно в YAML."""
        self._data_dir.mkdir(parents=True, exist_ok=True)
        try:
            with open(self._file, "w", encoding="utf-8") as f:
                yaml.dump(
                    self._cache,
                    f,
                    default_flow_style=False,
                    allow_unicode=True,
                    sort_keys=False,
                )
        except Exception as exc:
            _logger.error("[ThemePresetsManager] ошибка записи %s: %s", self._file, exc)

    def _invalidate(self) -> None:
        """Сбросить кэш (для принудительной перечитки)."""
        self._cache = None

    # ------------------------------------------------------------------
    # Публичный API
    # ------------------------------------------------------------------

    def list_presets(self) -> list[str]:
        """Список имён всех пресетов, отсортированный."""
        return sorted(self._load().keys())

    def get_preset(self, name: str) -> dict[str, str] | None:
        """Получить переменные пресета по имени. None если не найден."""
        return self._load().get(name)

    def save_preset(self, name: str, data: dict[str, str]) -> None:
        """Сохранить (или перезаписать) пресет."""
        presets = self._load()
        presets[name] = dict(data)
        self._save()

    def delete_preset(self, name: str) -> bool:
        """Удалить пресет. Вернёт True если существовал и удалён."""
        presets = self._load()
        if name not in presets:
            return False
        del presets[name]
        self._save()
        return True

    def rename_preset(self, old: str, new: str) -> bool:
        """Переименовать пресет. Вернёт False если old не найден или new уже есть."""
        presets = self._load()
        if old not in presets or new in presets:
            return False
        presets[new] = presets.pop(old)
        self._save()
        return True
