"""
ConfigStore — pickle-safe хранилище конфигов всех процессов.

Отвечает только за конфиги (статичные данные).
ProcessData отвечает за runtime-состояние (динамичные данные).
Разделение жизненных циклов — ADR-017.

Валидация конфигов — в config_module через data_schema_module.
ConfigStore хранит только dict (Dict at Boundary, ADR-008).
"""

from typing import Dict, Optional

from ..core.interfaces import IConfigStore


class ConfigStore(IConfigStore):
    """
    Pickle-safe хранилище конфигов всех процессов.

    Хранит только dict — нет ссылок на Queue/Event/SharedMemory.
    Полностью pickle-safe без __getstate__/__setstate__.
    """

    def __init__(self) -> None:
        self._configs: Dict[str, dict] = {}

    # ------------------------------------------------------------------
    # IConfigStore
    # ------------------------------------------------------------------

    def store(self, name: str, config: dict) -> None:
        """Сохранить конфиг процесса. Перезаписывает если уже есть."""
        if not isinstance(config, dict):
            raise TypeError(f"config must be dict, got {type(config).__name__}")
        self._configs[name] = config.copy()

    def get(self, name: str) -> Optional[dict]:
        """Получить копию конфига процесса."""
        cfg = self._configs.get(name)
        return cfg.copy() if cfg is not None else None

    def get_all(self) -> Dict[str, dict]:
        """Получить копии всех конфигов."""
        return {k: v.copy() for k, v in self._configs.items()}

    def has(self, name: str) -> bool:
        """Проверить наличие конфига."""
        return name in self._configs

    def remove(self, name: str) -> bool:
        """Удалить конфиг. Возвращает True если был удалён."""
        if name in self._configs:
            del self._configs[name]
            return True
        return False

    # ------------------------------------------------------------------
    # Вспомогательное
    # ------------------------------------------------------------------

    def __len__(self) -> int:
        return len(self._configs)

    def __contains__(self, name: str) -> bool:
        return name in self._configs

    def __repr__(self) -> str:
        return f"ConfigStore(processes={list(self._configs.keys())})"
