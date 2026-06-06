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

  Метаданные (params, index_usage, coll):
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
        self._stats = {"created": 0, "written": 0, "read": 0, "errors": 0}

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
        pd.custom.setdefault("memory_index_usage", {})
        pd.custom.setdefault("memory_coll", {})

        for name, params in memory_names.items():
            num_images, image_shape, dtype = params
            size = fmt.calculate_buffer_size(num_images, image_shape, dtype)
            shm_list = po.create_shm_blocks(name, size, coll)
            if shm_list is None:
                self._log_warning(f"Failed to create memory for '{name}'")
                continue

            pd.custom["memory_names"][name] = [shm.name for shm in shm_list]
            pd.custom["memory_params"][name] = params
            pd.custom["memory_index_usage"][name] = [0] * coll
            pd.custom["memory_coll"][name] = coll
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
            size = fmt.calculate_buffer_size(num_images, image_shape, dtype)
            shm_list = po.create_shm_blocks(name, size, coll)
            if shm_list is None:
                self._log_warning(f"Failed to create memory for '{name}'")
                continue

            self._local_handles.setdefault(process_name, {})[name] = shm_list
            self._local_meta.setdefault(process_name, {})[name] = _MemoryMeta(params, coll)
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
                "index_usage": pd.custom["memory_index_usage"],
                "coll": pd.custom["memory_coll"],
                "names": pd.custom["memory_names"],
            }
        else:
            meta = self._local_meta.get(process_name, {}).get(memory_name)
            if meta is None:
                return None
            return {
                "handles": handles,
                "params": {memory_name: meta.params},
                "index_usage": {memory_name: meta.index_usage},
                "coll": {memory_name: meta.coll},
                "names": {},
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
        try:
            handles = memory_data["handles"]
            shm = handles[index]
            max_images, max_shape, expected_dtype = memory_data["params"][shm_name]
            fmt.pack_images(shm.buf, images, max_shape, np.dtype(expected_dtype), fast=pack_fast)
            self._stats["written"] += 1
            return shm.name
        except Exception as e:
            self._log_error(f"write_images error: {e}")
            self._stats["errors"] += 1
            val.clear_memory_slot(memory_data.get("handles"), index)
            return None

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
            images = fmt.unpack_images(shm.buf, max_shape, np.dtype(expected_dtype), n=n, copy=copy)
            self._stats["read"] += 1
            return images
        except Exception as e:
            self._log_error(f"read_images error: {e}")
            self._stats["errors"] += 1
            return None

    def release_memory(self, process_name: str, shm_name: str, index: int) -> None:
        memory_data = self.get_memory_data(process_name, shm_name)
        if not memory_data:
            return
        val.clear_memory_slot(memory_data.get("handles"), index)
        index_usage = memory_data["index_usage"]
        if shm_name in index_usage and 0 <= index < len(index_usage[shm_name]):
            index_usage[shm_name][index] = 0

    def close_memory(self, process_name: str, shm_name: str) -> None:
        """Закрыть и очистить один shm-блок."""
        handles = self._local_handles.get(process_name, {}).get(shm_name, [])
        for shm in handles:
            self._safe_close_shm(shm, unlink=self._is_owner)
        self._local_handles.get(process_name, {}).pop(shm_name, None)

        if self._process_state_registry:
            pd = self._process_state_registry.get_process_data(process_name)
            if pd:
                for key in ("memory_names", "memory_params", "memory_index_usage", "memory_coll"):
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

    def find_free_index(self, process_name: str, shm_name: str) -> Optional[int]:
        memory_data = self.get_memory_data(process_name, shm_name)
        if not memory_data:
            return None
        usage = memory_data["index_usage"].get(shm_name)
        if usage is None:
            return None
        for i, used in enumerate(usage):
            if used == 0:
                return i
        return None

    def release_process_memory(self, process_name: str) -> None:
        """Полностью освободить SHM процесса при hot-swap (replace_blueprint).

        В отличие от ``close_all(process_name)`` (только handles) — это полный
        teardown процесса: (1) закрыть+unlink (owner) ВСЕ блоки; (2) снять процесс
        с ProcessStateRegistry (метаданные памяти уже вычищены ``close_memory``);
        (3) подчистить локальные структуры. После этого имена SHM свободны —
        новый процесс с тем же именем создаёт свежие ячейки без коллизий.
        """
        # 1. Закрыть и (owner) unlink все блоки процесса.
        #    close_memory попутно вычищает memory_* ключи из ProcessData.custom.
        for shm_name in list(self._local_handles.get(process_name, {}).keys()):
            self.close_memory(process_name, shm_name)

        # 2. Снять процесс с PSR (с PSR-режимом; без PSR — no-op)
        if self._process_state_registry is not None:
            try:
                self._process_state_registry.unregister_process(process_name)
            except Exception as e:
                self._log_error(f"release_process_memory: unregister_process('{process_name}') failed: {e}")

        # 3. Подчистить локальные структуры (handles обнулены close_memory, но
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
