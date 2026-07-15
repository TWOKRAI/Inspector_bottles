"""
MemoryManager — управление SharedMemory для изображений и данных.

Pickle-safe паттерн (ADR-019):
  - В ProcessData.custom["memory_names"] хранятся только shm.name строки
  - SharedMemory объекты хранятся в _local_handles (не pickle-able)
  - reinitialize_handles() открывает shm по именам в дочернем процессе

Owner process (ProcessManager): create=True, unlink() при shutdown.
Consumer process (дочерние): create=False, close() при shutdown.

Единый путь кода:
  _local_handles: Dict[str, Dict[str, List[SharedMemory]]]
      └── process_name
              └── shm_base_name
                      └── [shm_0, shm_1, ...]

  Метаданные (params, coll, seqlock):
    - С PSR: хранятся в ProcessData.custom (pickle-safe, видны всем процессам)
    - Без PSR: хранятся в _local_meta (только для standalone/unit-test режима)
"""

from multiprocessing import shared_memory
from typing import Any, Dict, List, Optional

import numpy as np

from ....base_manager import BaseManager, ObservableMixin
from ..interfaces import IMemoryManager
from ...mixins import ManagerStatsMixin
from ...types.types import MemoryAccessStatus

from .. import format as fmt
from .. import platform as po
from .. import validation as val
from .types import _MemoryMeta

# =============================================================================
# Жизненный цикл
# =============================================================================


class MemoryManager(BaseManager, ObservableMixin, IMemoryManager, ManagerStatsMixin):
    """
    Менеджер разделяемой памяти для изображений и данных.

    Единый путь кода через _local_handles независимо от наличия PSR.
    Метаданные хранятся в ProcessData.custom (с PSR) или _local_meta (без PSR).

    Pickle-safe: _local_handles и _local_meta НЕ сериализуются.
    После unpickle вызов reinitialize_handles() восстанавливает handles по именам из PSR.
    """

    def __init__(
        self,
        manager_name: str = "MemoryManager",
        process: Optional[Any] = None,
        process_state_registry: Optional[Any] = None,
        logger: Optional[Any] = None,
        seqlock_frames: Optional[bool] = None,
        owner_incarnation: Optional[bool] = None,
        **kwargs: Any,
    ) -> None:
        BaseManager.__init__(self, manager_name=manager_name, process=process)

        managers = kwargs.get("managers", {})
        if logger and "logger" not in managers:
            managers["logger"] = logger
        ObservableMixin.__init__(
            self,
            managers=managers,
            config=kwargs.get("config", {}),
            auto_proxy=kwargs.get("auto_proxy", True),
        )

        self._process_state_registry = process_state_registry

        # Единственное хранилище handles — НЕ pickle-safe
        self._local_handles: Dict[str, Dict[str, List[shared_memory.SharedMemory]]] = {}
        # Метаданные для standalone-режима (без PSR)
        self._local_meta: Dict[str, Dict[str, _MemoryMeta]] = {}
        # Owner создаёт (create=True) и unlink при shutdown
        self._is_owner: bool = True
        # Ф7 G.3(b): формат слота seqlock (ADR-SRM-011). Стампуется на слот при
        # создании → write/read/size самосогласованы. torn — счётчик дропов гонки
        # (reader поймал перезапись под собой; наблюдаемость через get_stats).
        self._seqlock_frames: bool = self._resolve_env_flag(seqlock_frames, "FW_SHM_SEQLOCK")
        # Ф7 G.3(b) / B-6/B-7: имя SHM с owner+incarnation (ADR-SRM-011) — stale-процесс
        # не пишет в чужой сегмент, мультикамера без коллизий. Дефолт False = прежнее имя.
        self._owner_incarnation: bool = self._resolve_env_flag(owner_incarnation, "FW_SHM_OWNER_INCARNATION")
        self._stats = {
            "created": 0,
            "written": 0,
            "read": 0,
            "errors": 0,
            "torn": 0,
            "seqlock_recovered": 0,
        }

    @staticmethod
    def _resolve_env_flag(explicit: Optional[bool], env_name: str) -> bool:
        """Разрешить булев флаг Ф7 G.3 (ADR-SRM-011).

        Приоритет: явный ctor-аргумент (не None) > env ``env_name`` (в т.ч.
        явное ``=0``) > **False** (прежнее поведение, откат = флаг off).
        """
        if explicit is not None:
            return bool(explicit)
        from ....config_module.tools.env import env_flag

        return env_flag(env_name, default=False)

    def initialize(self) -> bool:
        try:
            self.is_initialized = True
            self._log_info(f"MemoryManager '{self.manager_name}' initialized")
            return True
        except Exception as e:
            self._log_error(f"MemoryManager.initialize() failed: {e}")
            return False

    def shutdown(self) -> bool:
        try:
            self._close_all_handles()
            self._local_meta.clear()
            self.is_initialized = False
            self._log_info("MemoryManager shutdown completed")
            return True
        except Exception as e:
            self._log_error(f"MemoryManager.shutdown() failed: {e}")
            return False

    def reinitialize_handles(self) -> bool:
        """
        Открыть SharedMemory по именам после unpickle в дочернем процессе (ADR-019).

        Имена берём из ProcessData.custom["memory_names"] — они pickle-safe.
        Вызывается через SRM.reinitialize_in_child().
        """
        if not self._process_state_registry:
            return True
        try:
            for process_name in self._process_state_registry.get_process_names():
                pd = self._process_state_registry.get_process_data(process_name)
                if pd is None:
                    continue
                memory_names_map: Dict[str, List[str]] = pd.custom.get("memory_names", {})
                if not memory_names_map:
                    continue
                for shm_base_name, shm_names_list in memory_names_map.items():
                    existing = self._local_handles.get(process_name, {}).get(shm_base_name)
                    if existing and all(h is not None for h in existing):
                        continue
                    self._is_owner = False
                    handles: List[Optional[shared_memory.SharedMemory]] = []
                    for shm_name in shm_names_list:
                        shm = po.open_shm_block(shm_name)
                        if shm is None:
                            self._log_error(f"reinitialize_handles: cannot open '{shm_name}'")
                            handles.append(None)
                        else:
                            handles.append(shm)
                    self._local_handles.setdefault(process_name, {})[shm_base_name] = handles
            return True
        except Exception as e:
            self._log_error(f"reinitialize_handles() failed: {e}")
            return False

    # =========================================================================
    # IMemoryManager — создание
    # =========================================================================

    def create_memory_dict(
        self,
        process_name: str,
        memory_names: Dict[str, tuple],
        coll: int,
    ) -> bool:
        """
        Создать блоки SharedMemory для процесса (owner).

        С PSR: сохраняет только shm.name строки в ProcessData.custom.
        Без PSR: сохраняет метаданные в _local_meta.
        """
        try:
            if self._process_state_registry:
                return self._create_with_psr(process_name, memory_names, coll)
            else:
                return self._create_standalone(process_name, memory_names, coll)
        except Exception as e:
            self._log_error(f"create_memory_dict('{process_name}') failed: {e}")
            self._stats["errors"] += 1
            return False

    def _create_with_psr(
        self,
        process_name: str,
        memory_names: Dict[str, tuple],
        coll: int,
    ) -> bool:
        """Создание с PSR: метаданные в ProcessData.custom (pickle-safe)."""
        pd = self._process_state_registry.get_process_data(process_name)
        if pd is None:
            self._process_state_registry.register_process(process_name)
            pd = self._process_state_registry.get_process_data(process_name)

        pd.custom.setdefault("memory_names", {})
        pd.custom.setdefault("memory_params", {})
        pd.custom.setdefault("memory_coll", {})
        pd.custom.setdefault("memory_seqlock", {})

        for name, params in memory_names.items():
            num_images, image_shape, dtype = params
            size = fmt.calculate_buffer_size(num_images, image_shape, dtype, seqlock=self._seqlock_frames)
            shm_list = po.create_shm_blocks(
                name, size, coll, owner=process_name, owner_incarnation=self._owner_incarnation
            )
            if shm_list is None:
                self._log_warning(f"Failed to create memory for '{name}'")
                continue

            pd.custom["memory_names"][name] = [shm.name for shm in shm_list]
            pd.custom["memory_params"][name] = params
            pd.custom["memory_coll"][name] = coll
            # Ф7 G.3(b): формат слота (seqlock) — pickle-safe в PSR, виден consumer-процессам.
            pd.custom["memory_seqlock"][name] = self._seqlock_frames
            self._local_handles.setdefault(process_name, {})[name] = shm_list
            self._stats["created"] += 1

        self._log_info(f"Created {len(memory_names)} memory blocks for '{process_name}'")
        return True

    def _create_standalone(
        self,
        process_name: str,
        memory_names: Dict[str, tuple],
        coll: int,
    ) -> bool:
        """Создание без PSR: метаданные в _local_meta."""
        for name, params in memory_names.items():
            num_images, image_shape, dtype = params
            size = fmt.calculate_buffer_size(num_images, image_shape, dtype, seqlock=self._seqlock_frames)
            shm_list = po.create_shm_blocks(
                name, size, coll, owner=process_name, owner_incarnation=self._owner_incarnation
            )
            if shm_list is None:
                self._log_warning(f"Failed to create memory for '{name}'")
                continue

            self._local_handles.setdefault(process_name, {})[name] = shm_list
            self._local_meta.setdefault(process_name, {})[name] = _MemoryMeta(
                params, coll, seqlock=self._seqlock_frames
            )
            self._stats["created"] += 1

        self._log_info(f"Created {len(memory_names)} memory blocks for '{process_name}' (standalone)")
        return True

    # =========================================================================
    # IMemoryManager — доступ к данным
    # =========================================================================

    def get_memory_data(
        self,
        process_name: str,
        memory_name: str,
    ) -> Optional[Dict]:
        """
        Получить унифицированный словарь метаданных блока памяти.

        Возвращает одинаковую структуру независимо от режима (с PSR или без).
        """
        handles = self._local_handles.get(process_name, {}).get(memory_name)

        if self._process_state_registry:
            pd = self._process_state_registry.get_process_data(process_name)
            if pd is None or "memory_params" not in pd.custom:
                return None
            if memory_name not in pd.custom.get("memory_params", {}):
                return None
            return {
                "handles": handles,
                "params": pd.custom["memory_params"],
                "coll": pd.custom["memory_coll"],
                "names": pd.custom["memory_names"],
                # Ф7 G.3(b): формат слота seqlock (по имени; дефолт False для старых слотов).
                "seqlock": pd.custom.get("memory_seqlock", {}).get(memory_name, False),
            }
        else:
            meta = self._local_meta.get(process_name, {}).get(memory_name)
            if meta is None:
                return None
            return {
                "handles": handles,
                "params": {memory_name: meta.params},
                "coll": {memory_name: meta.coll},
                "names": {},
                "seqlock": meta.seqlock,
            }

    def write_images(
        self,
        process_name: str,
        shm_name: str,
        images: List[np.ndarray],
        index: int,
        *,
        pack_fast: bool = True,
    ) -> Optional[str]:
        memory_data = self.get_memory_data(process_name, shm_name)
        access = val.validate_memory_access(memory_data, shm_name, index)
        if access != MemoryAccessStatus.OK:
            self._log_warning(f"Memory access failed for '{process_name}'/'{shm_name}'[{index}]: {access.value}")
            return None
        write_status = val.validate_write_operation(memory_data, shm_name, index, len(images))
        if write_status != MemoryAccessStatus.OK:
            self._log_warning(
                f"Write validation failed for '{process_name}'/'{shm_name}'[{index}]: {write_status.value}"
            )
            return None
        seqlock = bool(memory_data.get("seqlock", False))
        try:
            handles = memory_data["handles"]
            shm = handles[index]
            max_images, max_shape, expected_dtype = memory_data["params"][shm_name]
            fmt.pack_images(
                shm.buf,
                images,
                max_shape,
                np.dtype(expected_dtype),
                fast=pack_fast,
                seqlock=seqlock,
                on_recover=self._on_seqlock_recover if seqlock else None,
            )
            self._stats["written"] += 1
            return shm.name
        except Exception as e:
            self._log_error(f"write_images error: {e}")
            self._stats["errors"] += 1
            # H1c: seqlock-слот чистим по протоколу (не raw buf[:]=0 мимо generation).
            val.clear_memory_slot(memory_data.get("handles"), index, seqlock=seqlock)
            return None

    def _on_seqlock_recover(self, gen: int) -> None:
        """H1b: writer нашёл слот с НЕЧЁТНЫМ generation (прошлая запись не довелась —
        исключение без finally в старом коде / kill -9). Throttled WARNING через фасад."""
        self._stats["seqlock_recovered"] += 1
        n = self._stats["seqlock_recovered"]
        if n == 1 or n % 200 == 0:
            self._log_warning(
                f"seqlock: восстановлен отравленный слот (нечёт generation={gen}); "
                f"прошлый writer не довёл запись [всего {n}]"
            )

    def read_images(
        self,
        process_name: str,
        shm_name: str,
        index: int,
        n: int = -1,
        *,
        copy: bool = True,
    ) -> Optional[List[np.ndarray]]:
        memory_data = self.get_memory_data(process_name, shm_name)
        access = val.validate_memory_access(memory_data, shm_name, index)
        if access != MemoryAccessStatus.OK:
            self._log_warning(f"Memory read failed for '{process_name}'/'{shm_name}'[{index}]: {access.value}")
            return None
        try:
            handles = memory_data["handles"]
            shm = handles[index]
            _, max_shape, expected_dtype = memory_data["params"][shm_name]
            seqlock = bool(memory_data.get("seqlock", False))
            images = fmt.unpack_images(
                shm.buf, max_shape, np.dtype(expected_dtype), n=n, copy=copy, verify_seqlock=seqlock
            )
            if images is None:
                # Ф7 G.3(b): seqlock поймал torn/in-progress → честный drop (не порча).
                self._stats["torn"] += 1
                return None
            self._stats["read"] += 1
            return images
        except Exception as e:
            self._log_error(f"read_images error: {e}")
            self._stats["errors"] += 1
            return None

    def release_memory(self, process_name: str, shm_name: str, index: int) -> None:
        # Ф7 G.H: очистка слота (seqlock-совместимая). Учёт занятости слота — за фасадом
        # `memory.pool.FramePool` (owner-side loan-протокол), не в мёртвом index_usage.
        memory_data = self.get_memory_data(process_name, shm_name)
        if not memory_data:
            return
        val.clear_memory_slot(memory_data.get("handles"), index, seqlock=bool(memory_data.get("seqlock", False)))

    def close_memory(self, process_name: str, shm_name: str) -> None:
        """Закрыть и очистить один shm-блок."""
        handles = self._local_handles.get(process_name, {}).get(shm_name, [])
        for shm in handles:
            self._safe_close_shm(shm, unlink=self._is_owner)
        self._local_handles.get(process_name, {}).pop(shm_name, None)

        if self._process_state_registry:
            pd = self._process_state_registry.get_process_data(process_name)
            if pd:
                for key in ("memory_names", "memory_params", "memory_coll", "memory_seqlock"):
                    pd.custom.get(key, {}).pop(shm_name, None)
        else:
            self._local_meta.get(process_name, {}).pop(shm_name, None)

    # =========================================================================
    # Вспомогательные методы
    # =========================================================================

    def get_actual_shm_name(self, process_name: str, shm_name: str, index: int) -> Optional[str]:
        """Получить фактическое OS-имя SHM-блока по индексу слота.

        На Windows имена создаются с PID (camera_0_frame_{PID}_0), поэтому
        consumer-процесс не может угадать имя заранее. Этот метод позволяет
        owner-процессу передать фактическое имя через IPC (в frame_data).
        """
        handles = self._local_handles.get(process_name, {}).get(shm_name)
        if handles is None or index >= len(handles) or handles[index] is None:
            return None
        return handles[index].name

    # Ф7 G.H: find_free_index СНЯТ — мёртвый первый учёт занятости (index_usage писался
    # только в 0, «used=1» никто не ставил → всегда возвращал слот 0). Реальный free-list
    # с владением по цепочке — за фасадом `memory.pool.FramePool` (loan-протокол, G.5.d/e).

    def release_process_memory(self, process_name: str) -> None:
        """Полностью освободить SHM процесса при hot-swap (replace_blueprint).

        В отличие от ``close_all(process_name)`` (только handles) — полный
        teardown ПАМЯТИ процесса: (1) закрыть+unlink (owner) ВСЕ блоки
        (``close_memory`` попутно вычищает memory_* ключи из
        ProcessData.custom); (2) подчистить локальные структуры. После этого
        имена SHM свободны — новый процесс с тем же именем создаёт свежие
        ячейки без коллизий.

        Контракт сужен (ADR-SRM-009): ТОЛЬКО память. Снятие процесса с PSR
        (очереди/события/запись целиком) — явная операция
        ``SharedResourcesManager.unregister_process``, а не побочный эффект
        освобождения памяти.
        """
        # 1. Закрыть и (owner) unlink все блоки процесса.
        for shm_name in list(self._local_handles.get(process_name, {}).keys()):
            self.close_memory(process_name, shm_name)

        # 2. Подчистить локальные структуры (handles обнулены close_memory, но
        #    остаётся пустой dict процесса; meta — для standalone-режима)
        self._local_handles.pop(process_name, None)
        self._local_meta.pop(process_name, None)
        self._log_info(f"release_process_memory: SHM процесса '{process_name}' освобождён")

    def close_all(self, process_name: Optional[str] = None) -> None:
        if process_name:
            for shm_name in list(self._local_handles.get(process_name, {}).keys()):
                self.close_memory(process_name, shm_name)
        else:
            for pname in list(self._local_handles.keys()):
                for shm_name in list(self._local_handles[pname].keys()):
                    self.close_memory(pname, shm_name)

    def _safe_close_shm(
        self,
        shm: Optional[shared_memory.SharedMemory],
        unlink: bool = False,
    ) -> None:
        """Безопасный close/unlink с логированием."""
        if shm is None:
            return
        try:
            po.close_shm(shm, unlink=unlink)
        except FileNotFoundError:
            pass
        except Exception as e:
            self._log_error(f"shm.close/unlink failed: {e}")

    def _close_all_handles(self) -> None:
        for process_name, shm_map in list(self._local_handles.items()):
            for shm_name, handles in shm_map.items():
                for shm in handles:
                    self._safe_close_shm(shm, unlink=self._is_owner)
        self._local_handles.clear()

    # =========================================================================
    # Статистика (ManagerStatsMixin._merge_stats)
    # =========================================================================

    def get_stats(self) -> Dict[str, Any]:
        mem_stats = {
            **self._stats,
            "processes_with_handles": len(self._local_handles),
            "is_owner": self._is_owner,
        }
        return self._merge_stats("memory", mem_stats)
