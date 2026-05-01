"""Cleanup осиротевших SHM-сегментов при старте и завершении приложения.

Проблема: после kill -9 SharedMemory сегменты остаются в системе.
- Linux: файлы в /dev/shm/ накапливаются
- Windows: объекты живут пока есть хотя бы один handle; при аварийном завершении
  теряются все handles и mapping освобождается ОС, но следующий старт
  с тем же именем получит FileExistsError если PID-суффикс совпадёт

Подход:
- Linux: сканировать /dev/shm/ по списку известных базовых имён
- Windows: попытаться open+close по базовым именам (без PID-суффикса)
  через реестр имён из ShmRegistry
- В обоих случаях cleanup не трогает сегменты с действующими handles (try/except)
"""

from __future__ import annotations

import logging
import platform
import sys
from multiprocessing import shared_memory
from pathlib import Path

logger = logging.getLogger(__name__)

# Количество коллекций-слотов по умолчанию для перебора имён вида {name}_0 .. {name}_{N-1}
_MAX_COLL_SCAN = 16


def _is_windows() -> bool:
    return sys.platform == "win32"


def _is_linux() -> bool:
    return sys.platform.startswith("linux")


def _try_cleanup_shm_name(name: str) -> bool:
    """Попытаться открыть и удалить SHM-сегмент с данным именем.

    Returns:
        True если сегмент был найден и очищен, False если сегмент не существует.
    """
    try:
        shm = shared_memory.SharedMemory(name=name, create=False)
        shm.close()
        if not _is_windows():
            try:
                shm.unlink()
            except FileNotFoundError:
                pass
        return True
    except FileNotFoundError:
        return False
    except Exception as exc:
        logger.debug("cleanup SHM '%s': %s", name, exc)
        return False


def _scan_linux_devshm(known_names: list[str]) -> list[str]:
    """На Linux сканировать /dev/shm/ по известным базовым именам.

    Returns:
        Список очищенных имён.
    """
    cleaned: list[str] = []
    dev_shm = Path("/dev/shm")

    if not dev_shm.exists():
        return cleaned

    try:
        existing_files = {f.name for f in dev_shm.iterdir() if f.is_file()}
    except PermissionError:
        logger.warning("Нет прав на чтение /dev/shm/")
        return cleaned

    for base_name in known_names:
        if base_name in existing_files:
            if _try_cleanup_shm_name(base_name):
                cleaned.append(base_name)
                logger.debug("Linux: очищен SHM '%s'", base_name)

        for i in range(_MAX_COLL_SCAN):
            slot_name = f"{base_name}_{i}"
            if slot_name in existing_files:
                if _try_cleanup_shm_name(slot_name):
                    cleaned.append(slot_name)
                    logger.debug("Linux: очищен SHM '%s'", slot_name)
            else:
                break

    return cleaned


def _scan_windows_known_names(known_names: list[str]) -> list[str]:
    """На Windows перебрать известные имена и попытаться очистить (best-effort).

    Returns:
        Список очищенных имён.
    """
    cleaned: list[str] = []

    for base_name in known_names:
        if _try_cleanup_shm_name(base_name):
            cleaned.append(base_name)
            logger.debug("Windows: очищен SHM '%s'", base_name)

        for i in range(_MAX_COLL_SCAN):
            slot_name = f"{base_name}_{i}"
            if _try_cleanup_shm_name(slot_name):
                cleaned.append(slot_name)
                logger.debug("Windows: очищен SHM '%s'", slot_name)

    return cleaned


def cleanup_stale_shm(known_names: list[str] | None = None) -> list[str]:
    """Очистить осиротевшие SHM-сегменты по списку известных базовых имён.

    Кросс-платформенная реализация:
    - Linux: сканировать /dev/shm/ на файлы совпадающие с known_names
    - Windows: попытка open+close по known_names (best-effort)

    Args:
        known_names: список базовых имён SHM (например ["camera_0_frame"]).
                     Если None или пустой — ничего не делает.

    Returns:
        Список имён очищенных сегментов.
    """
    if not known_names:
        logger.debug("cleanup_stale_shm: список known_names пуст, пропускаем")
        return []

    logger.info(
        "cleanup_stale_shm: проверяем %d базовых имён SHM на платформе %s",
        len(known_names),
        platform.system(),
    )

    try:
        if _is_linux():
            cleaned = _scan_linux_devshm(known_names)
        else:
            cleaned = _scan_windows_known_names(known_names)
    except Exception as exc:
        logger.error("cleanup_stale_shm: неожиданная ошибка: %s", exc)
        return []

    if cleaned:
        logger.info("cleanup_stale_shm: очищено %d SHM-сегментов: %s", len(cleaned), cleaned)
    else:
        logger.debug("cleanup_stale_shm: осиротевших SHM-сегментов не найдено")

    return cleaned
