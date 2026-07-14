"""
Платформенные операции SharedMemory.

Windows: unlink() — no-op; память освобождается при close последнего handle.
         cleanup_stale_shm: open+close освобождает mapping при последнем handle.
         Уникальные имена с PID в create_shm_blocks.
POSIX (Linux/macOS): unlink() освобождает сегмент; cleanup_stale_shm: open+close+unlink.
"""

from __future__ import annotations

import hashlib
import itertools
import os
import platform
from multiprocessing import shared_memory
from typing import Any, List, Optional

from ....logger_module.utils import FallbackLogger

_logger = FallbackLogger(__name__)

# H3 (ADR-SRM-011): предельная длина базового SHM-имени ДО суффикса ``_{idx}``.
# macOS PSHMNAMLEN ≈ 31; держим базу ≤ 26 (запас на ``_63`` при coll до 64).
_MAX_BASE_NAME_LEN = 26

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


def _extract_memory_region_names(proc_dict: dict[str, Any]) -> list[str]:
    """Извлечь БАЗОВЫЕ имена frame/data-регионов, объявленных в ``proc_dict["memory"]``.

    Общая логика для ``cleanup_known_shm_at_startup`` (точный cleanup ``{name}_{i}``) И
    ``extract_memory_region_names`` (M8a: базовые имена как ПРЕФИКСЫ для
    ``cleanup_orphaned_by_prefix`` — owner_incarnation суффиксует ДАЖЕ объявленные в
    конфиге имена, точный cleanup их тогда не поймает, только префиксный).

    Поддерживает форматы: плоский {"x": (h,w,c), "coll": 2} и вложенный {"names": {...}}.
    """
    if not isinstance(proc_dict, dict):
        return []
    mem = proc_dict.get("memory")
    if not isinstance(mem, dict):
        return []
    names_raw = mem.get("names")
    if names_raw is None:
        names_raw = {k: v for k, v in mem.items() if k != "coll" and isinstance(v, (tuple, list))}
    return list(names_raw.keys()) if isinstance(names_raw, dict) else []


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
        names = _extract_memory_region_names(proc_dict)
        for name in names:
            for i in range(coll):
                key = f"{name}_{i}"
                if key not in seen:
                    seen.add(key)
                    cleanup_stale_shm(key)


def extract_memory_region_names(processes_config: dict[str, Any] | None) -> list[str]:
    """Ф7 G.3 M8a: извлечь БАЗОВЫЕ имена ВСЕХ объявленных в конфиге memory-регионов
    (без дублей, порядок первого появления) — источник ПРЕФИКСОВ для
    ``cleanup_orphaned_by_prefix`` (вместо хардкода одного имени).

    Переиспользует ``_extract_memory_region_names`` (та же логика, что и точный
    cleanup в ``cleanup_known_shm_at_startup``), не изобретает отдельный парсер
    processes_config. Значения, приходящие в ``FrameShmMiddleware`` (напр.
    ``output_frames`` — универсальный лениво выделяемый слот generic-пайплайна) в
    processes_config НЕ объявлены — вызывающая сторона обязана добавить их к
    результату сама (см. ``SystemLauncher._cleanup_shm_at_startup``).

    Returns:
        Список базовых имён без дублей. Пустой список, если processes_config пуст,
        не содержит memory-секций, либо имеет неожиданную форму.
    """
    seen: set[str] = set()
    ordered: list[str] = []
    for proc_dict in (processes_config or {}).values():
        for name in _extract_memory_region_names(proc_dict):
            if name not in seen:
                seen.add(name)
                ordered.append(name)
    return ordered


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
    owner + pid (H2: на ВСЕХ платформах, не только Windows — иначе на POSIX
    ``_incarnation`` сбрасывается в каждом процессе → два интерпретатора дают ОДНО
    имя и один unlink'ает сегмент другого) + свежую инкарнацию на КАЖДОЕ создание.
    Два живых источника с одинаковым slot-именем в разных процессах больше не
    коллидируют; stale-процесс после switch не переиспользует чужое имя. Consumer
    читает ФАКТИЧЕСКОЕ имя (PSR memory_names / shm_actual_name) — суффикс прозрачен.

    H3 (macOS PSHMNAMLEN ~31): при переполнении ``_MAX_BASE_NAME_LEN`` имя
    детерминированно схлопывается в ``{base[:10]}_{blake2s8}`` (хеш кодирует
    owner+pid+inc → уникальность сохранена, длина ≤ лимита).
    """
    if owner_incarnation:
        parts = [base_name]
        if owner:
            parts.append(str(owner))
        parts.append(str(os.getpid()))  # H2: pid на ВСЕХ платформах
        parts.append(str(next(_incarnation)))
        return _bounded_name(base_name, "_".join(parts))
    if is_windows():
        suffix = f"_{next(_incarnation)}" if fresh else ""
        return f"{base_name}_{os.getpid()}{suffix}"
    # POSIX: unlink освобождает сразу; fresh нужен лишь если живой holder держит сегмент.
    return f"{base_name}_{next(_incarnation)}" if fresh else base_name


def _bounded_name(base_name: str, full: str) -> str:
    """H3: если ``full`` (без ``_{idx}``-суффикса от create_shm_blocks) длиннее лимита —
    детерминированно схлопнуть в ``{base[:10]}_{blake2s8}`` (≤ 19 симв., + ``_{idx}`` ≤ 30).

    Хеш от ПОЛНОГО имени (owner+pid+inc) сохраняет уникальность; человекочитаемый
    префикс base — для отладки. macOS PSHMNAMLEN ≈ 31 → держим базу ≤ 26.
    """
    if len(full) <= _MAX_BASE_NAME_LEN:
        return full
    digest = hashlib.blake2s(full.encode("utf-8"), digest_size=4).hexdigest()  # 8 hex
    return f"{base_name[:10]}_{digest}"


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
