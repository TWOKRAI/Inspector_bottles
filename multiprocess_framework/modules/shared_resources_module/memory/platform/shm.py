"""
Платформенные операции SharedMemory.

Windows: unlink() — no-op; память освобождается при close последнего handle.
         cleanup_stale_shm: open+close освобождает mapping при последнем handle.
         Уникальные имена с PID в create_shm_blocks.
POSIX (Linux/macOS): unlink() освобождает сегмент; cleanup_stale_shm: open+close+unlink.
"""

from __future__ import annotations

import itertools
import os
import platform
from multiprocessing import shared_memory
from typing import Any, List, Optional

from ....logger_module.utils import FallbackLogger

_logger = FallbackLogger(__name__)

# Счётчик инкарнаций имени SHM в рамках процесса. Нужен для hot-swap: при пересоздании
# сегмента (новый рецепт) старый на Windows освобождается АСИНХРОННО (unlink — no-op,
# segment жив пока открыт хоть один handle; terminate закрывает handles не мгновенно).
# Свежая инкарнация в имени избегает FileExistsError на переходном окне. Consumer'ы
# читают ФАКТИЧЕСКИЕ имена (memory_names в PSR / shm_actual_name в frame_data), поэтому
# суффикс прозрачен.
_incarnation = itertools.count(1)

# Тип для SharedMemory (Any для избежания прямого импорта в интерфейсах)
ShmType = shared_memory.SharedMemory


def is_windows() -> bool:
    """Проверка платформы Windows."""
    return platform.system() == "Windows"


def is_posix() -> bool:
    """Проверка POSIX-платформы (Linux, macOS)."""
    return platform.system() in ("Linux", "Darwin")


def cleanup_stale_shm(name: str) -> None:
    """
    Попытка удалить устаревший shm сегмент от предыдущих запусков.

    POSIX: открыть + close + unlink (освобождает сегмент).
    Windows: открыть + close (освобождает mapping, если последний handle).
    """
    try:
        stale = shared_memory.SharedMemory(name=name, create=False)
        stale.close()
        if is_posix():
            try:
                stale.unlink()
            except FileNotFoundError:
                pass
    except FileNotFoundError:
        pass
    except Exception:
        pass


def cleanup_known_shm_at_startup(processes_config: dict[str, Any]) -> None:
    """
    Очистить известные SharedMemory блоки перед стартом приложения.

    Извлекает имена из config["memory"] каждого процесса и вызывает cleanup_stale_shm
    для {name}_0, {name}_1, ... {name}_{coll-1}. Работает на Windows, Linux, macOS.

    Поддерживает форматы: плоский {"x": (h,w,c), "coll": 2} и вложенный {"names": {...}}.

    Args:
        processes_config: {process_name: proc_dict}, proc_dict может содержать "memory".
    """
    seen: set = set()
    for proc_dict in (processes_config or {}).values():
        if not isinstance(proc_dict, dict):
            continue
        mem = proc_dict.get("memory")
        if not isinstance(mem, dict):
            continue
        coll = mem.get("coll", 2)
        names_raw = mem.get("names")
        if names_raw is None:
            names_raw = {k: v for k, v in mem.items() if k != "coll" and isinstance(v, (tuple, list))}
        names = list(names_raw.keys()) if isinstance(names_raw, dict) else []
        for name in names:
            for i in range(coll):
                key = f"{name}_{i}"
                if key not in seen:
                    seen.add(key)
                    cleanup_stale_shm(key)


def _unique_base_name(
    base_name: str,
    *,
    fresh: bool = False,
    owner: str | None = None,
    owner_incarnation: bool = False,
) -> str:
    """Уникальное имя SHM.

    На Windows дополняется PID (избежать FileExistsError от предыдущих ЗАПУСКОВ).
    ``fresh=True`` дополнительно добавляет инкарнацию — для пересоздания внутри одного
    процесса (hot-swap), когда старый сегмент с тем же PID-именем ещё не освобождён.

    Ф7 G.3(b) / B-6/B-7 (ADR-SRM-011), ``owner_incarnation=True``: имя ВСЕГДА несёт
    owner + свежую инкарнацию (+ pid на Windows) на КАЖДОЕ создание. Два живых
    источника с одинаковым slot-именем в разных процессах больше не коллидируют
    (owner+pid+inc уникальны); stale-процесс после switch не переиспользует чужое имя
    (in-flight сообщение со старым именем читает пусто, не чужой кадр). Consumer читает
    ФАКТИЧЕСКОЕ имя (PSR memory_names / shm_actual_name) — суффикс прозрачен.
    """
    if owner_incarnation:
        parts = [base_name]
        if owner:
            parts.append(str(owner))
        if is_windows():
            parts.append(str(os.getpid()))
        parts.append(str(next(_incarnation)))
        return "_".join(parts)
    if is_windows():
        suffix = f"_{next(_incarnation)}" if fresh else ""
        return f"{base_name}_{os.getpid()}{suffix}"
    # POSIX: unlink освобождает сразу; fresh нужен лишь если живой holder держит сегмент.
    return f"{base_name}_{next(_incarnation)}" if fresh else base_name


def create_shm_block(name: str, size: int) -> ShmType:
    """
    Создать блок SharedMemory.

    Перед созданием всегда выполняется cleanup_stale_shm (все платформы).

    Returns:
        SharedMemory

    Raises:
        Exception: при ошибке создания
    """
    cleanup_stale_shm(name)
    return shared_memory.SharedMemory(name=name, create=True, size=size)


def open_shm_block(name: str) -> Optional[ShmType]:
    """
    Открыть (attach) существующий блок SharedMemory.

    На Windows при spawn возможна гонка: повторная попытка через 50–100ms.

    Returns:
        SharedMemory или None при ошибке
    """
    import time

    for attempt in range(3):
        try:
            return shared_memory.SharedMemory(name=name, create=False)
        except Exception:
            if attempt < 2 and is_windows():
                time.sleep(0.05 * (attempt + 1))
            else:
                break
    return None


def close_shm(shm: Optional[ShmType], unlink: bool = False) -> None:
    """
    Закрыть SharedMemory с опциональным unlink.

    На Windows unlink() — no-op (документация Python).
    На POSIX unlink освобождает сегмент.

    FileNotFoundError при unlink игнорируется (сегмент уже удалён).
    """
    if shm is None:
        return
    try:
        shm.close()
    except Exception:
        raise
    if unlink and is_posix():
        try:
            shm.unlink()
        except FileNotFoundError:
            pass
        except Exception:
            raise


def create_shm_blocks(
    base_name: str,
    size: int,
    coll: int,
    *,
    owner: str | None = None,
    owner_incarnation: bool = False,
) -> Optional[List[ShmType]]:
    """
    Создать coll блоков SharedMemory с именами {base_name}_0, {base_name}_1, ...

    На Windows base_name дополняется PID для избежания FileExistsError от предыдущих запусков.
    Фактические имена (shm.name) сохраняются в memory_names для consumer-процессов.

    Ф7 G.3(b): ``owner_incarnation=True`` → имя несёт owner+инкарнацию всегда (B-6/B-7,
    ADR-SRM-011), см. ``_unique_base_name``.

    При ошибке создания любого блока — закрывает и удаляет уже созданные,
    возвращает None.
    """
    # До 3 попыток: при FileExistsError (сегмент предыдущей инкарнации ещё не
    # освобождён — hot-swap на Windows) пересоздаём набор со СВЕЖИМ именем. Старый
    # сегмент освободится, когда ОС закроет handles умершего процесса; новая инкарнация
    # не ждёт этого окна. Consumer'ы читают фактические имена → суффикс прозрачен.
    last_exc: Exception | None = None
    for attempt in range(3):
        base = _unique_base_name(base_name, fresh=(attempt > 0), owner=owner, owner_incarnation=owner_incarnation)
        shm_list: List[ShmType] = []
        try:
            for i in range(coll):
                shm_list.append(create_shm_block(f"{base}_{i}", size))
            if attempt > 0:
                _logger.warning(
                    "[MemoryManager] SHM '%s' пересоздан со свежей инкарнацией '%s' "
                    "(старый сегмент ещё держался — hot-swap)",
                    base_name,
                    base,
                )
            return shm_list
        except FileExistsError as e:
            last_exc = e
            for created in shm_list:
                close_shm(created, unlink=True)
            continue
        except Exception as e:
            for created in shm_list:
                close_shm(created, unlink=True)
            _logger.error("[MemoryManager] SharedMemory create failed for '%s': %s", base_name, e)
            return None
    _logger.error(
        "[MemoryManager] SharedMemory create failed for '%s' после 3 попыток: %s",
        base_name,
        last_exc,
    )
    return None
