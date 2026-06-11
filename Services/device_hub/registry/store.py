"""RegistryStore — atomic YAML-хранилище реестра устройств.

Формат файла ``devices.yaml``::

    version: 1
    devices:
      - id: robot_main
        name: "Робот Delta"
        kind: robot
        ...

Атомарная запись: tmp-файл + ``os.replace`` (образец — recipe_store.py).
Незнакомая версия — ошибка с подсказкой.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any

import yaml

from Services.device_hub.errors import DeviceHubError
from Services.device_hub.registry.entry import DeviceEntry

# Текущая версия формата
_CURRENT_VERSION = 1


class RegistryStore:
    """Загрузка/сохранение реестра устройств из/в YAML-файл.

    Args:
        path: Путь к ``devices.yaml``.
    """

    def __init__(self, path: Path | str) -> None:
        self._path = Path(path)

    @property
    def path(self) -> Path:
        """Путь к файлу реестра."""
        return self._path

    def load(self) -> list[DeviceEntry]:
        """Прочитать реестр из файла.

        Returns:
            Список DeviceEntry. Пустой список, если файл не существует
            или devices пуст.

        Raises:
            DeviceHubError: Незнакомая версия или повреждённый формат.
        """
        if not self._path.exists():
            return []

        text = self._path.read_text(encoding="utf-8")
        if not text.strip():
            return []

        data = yaml.safe_load(text)
        if not isinstance(data, dict):
            raise DeviceHubError(f"Файл реестра {self._path} повреждён: ожидается YAML-словарь")

        version = data.get("version", 1)
        if version != _CURRENT_VERSION:
            raise DeviceHubError(
                f"Незнакомая версия реестра: {version} (поддерживается: {_CURRENT_VERSION}). "
                f"Обновите Services/device_hub или мигрируйте файл."
            )

        raw_devices = data.get("devices")
        if not raw_devices:
            return []

        if not isinstance(raw_devices, list):
            raise DeviceHubError(f"Файл реестра {self._path}: поле 'devices' должно быть списком")

        entries: list[DeviceEntry] = []
        for idx, item in enumerate(raw_devices):
            if not isinstance(item, dict):
                raise DeviceHubError(f"Файл реестра {self._path}: элемент #{idx} не dict")
            entries.append(DeviceEntry.from_dict(item))
        return entries

    def save(self, entries: list[DeviceEntry]) -> None:
        """Атомарно сохранить реестр в файл (tmp + os.replace).

        Args:
            entries: Список DeviceEntry для записи.
        """
        data: dict[str, Any] = {
            "version": _CURRENT_VERSION,
            "devices": [e.to_dict() for e in entries],
        }
        text = yaml.dump(
            data,
            default_flow_style=False,
            allow_unicode=True,
            sort_keys=False,
        )

        # Создать директорию, если не существует
        self._path.parent.mkdir(parents=True, exist_ok=True)

        # Атомарная запись: tmp рядом с целевым файлом + os.replace
        fd, tmp_path = tempfile.mkstemp(
            dir=str(self._path.parent),
            prefix=".devices_",
            suffix=".yaml.tmp",
        )
        try:
            os.write(fd, text.encode("utf-8"))
            os.close(fd)
            os.replace(tmp_path, str(self._path))
        except BaseException:
            # Очистка tmp при ошибке
            os.close(fd) if not os.get_inheritable(fd) else None  # noqa: SIM108 — fd мог быть закрыт
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
