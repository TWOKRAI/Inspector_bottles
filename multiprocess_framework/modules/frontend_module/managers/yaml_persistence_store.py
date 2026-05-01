"""YamlPersistenceStore — generic YAML-хранилище именованных профилей/снимков конфигурации."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any, Callable, Generic, TypeVar

import yaml

T = TypeVar("T")

STORE_FILE_VERSION = 1
DEFAULT_PROFILE_ID = "default"


class YamlPersistenceStore(Generic[T]):
    """Generic YAML-хранилище именованных профилей/снимков конфигурации.

    Формат файла::

        version: 1
        current_profile: "default"
        profiles:
          default:
            ...
          other:
            ...

    Параметры конструктора позволяют адаптировать под любой домен
    без подкласса — достаточно передать фабрики.
    """

    def __init__(
        self,
        file_path: Path,
        *,
        default_snapshot_factory: Callable[[], dict[str, Any]],
        from_dict: Callable[[dict[str, Any]], T] | None = None,
        file_version: int = STORE_FILE_VERSION,
        default_profile_id: str = DEFAULT_PROFILE_ID,
    ) -> None:
        self._path = Path(file_path)
        self._default_snapshot_factory = default_snapshot_factory
        self._from_dict = from_dict
        self._file_version = file_version
        self._default_profile_id = default_profile_id

    @property
    def path(self) -> Path:
        """Путь к YAML-файлу."""
        return self._path

    # ------------------------------------------------------------------
    # Внутренние методы
    # ------------------------------------------------------------------

    def _read_raw(self) -> dict[str, Any] | None:
        """Прочитать YAML; None если файла нет или он битый."""
        if not self._path.is_file():
            return None
        try:
            with open(self._path, encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
        except (yaml.YAMLError, OSError):
            return None
        return data if isinstance(data, dict) else None

    def _write_raw(self, payload: dict[str, Any]) -> bool:
        """Записать payload в YAML (создаёт директорию при необходимости)."""
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._path, "w", encoding="utf-8") as f:
                yaml.safe_dump(
                    payload, f, allow_unicode=True, default_flow_style=False, sort_keys=False
                )
            return True
        except OSError:
            return False

    # ------------------------------------------------------------------
    # Публичный API
    # ------------------------------------------------------------------

    def read_dict(self) -> dict[str, Any] | None:
        """Прочитать YAML как raw dict; None если файла нет или битый."""
        return self._read_raw()

    def read(self, profile_id: str | None = None) -> T | dict[str, Any]:
        """Прочитать профиль по ID и вернуть объект типа T (или dict если from_dict не задан).

        Если profile_id не указан — используется current_profile из YAML.
        При ошибке — возвращает результат default_snapshot_factory().
        """
        data = self._read_raw() or {}
        resolved_id = (
            profile_id
            if profile_id is not None
            else data.get("current_profile", self._default_profile_id)
        )

        profiles = data.get("profiles", {})
        profile_dict = profiles.get(resolved_id, {})

        # Применить from_dict если задан
        if self._from_dict is not None:
            try:
                return self._from_dict(profile_dict)
            except Exception as exc:
                print(
                    f"WARNING: профиль '{resolved_id}' содержит невалидные значения, "
                    f"применяются defaults. Ошибки: {exc}"
                )
                try:
                    return self._from_dict(self._default_snapshot_factory())
                except Exception:
                    return self._default_snapshot_factory()

        return copy.deepcopy(profile_dict) if profile_dict else self._default_snapshot_factory()

    def save(
        self,
        profile_id: str,
        data: dict[str, Any],
        *,
        current_profile: str | None = None,
    ) -> bool:
        """Сохранить (или перезаписать) профиль в YAML.

        Args:
            profile_id: идентификатор профиля.
            data: dict со снимком профиля.
            current_profile: если задан — обновить current_profile в YAML.
        """
        raw = self._read_raw() or {}
        profiles: dict[str, Any] = raw.get("profiles", {})
        profiles[profile_id] = copy.deepcopy(data)

        payload: dict[str, Any] = {
            "version": raw.get("version", self._file_version),
            "current_profile": current_profile or raw.get("current_profile", self._default_profile_id),
            "profiles": profiles,
        }
        return self._write_raw(payload)

    def list_profiles(self) -> list[str]:
        """Список идентификаторов профилей из YAML."""
        raw = self._read_raw() or {}
        return list(raw.get("profiles", {}).keys())

    def get_current_profile_id(self) -> str:
        """Текущий профиль из YAML (или default_profile_id)."""
        raw = self._read_raw() or {}
        return raw.get("current_profile", self._default_profile_id)
