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

  Нет _local_memories, нет дублирующих путей.
"""

import struct
from multiprocessing import shared_memory
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from ...base_manager import BaseManager, ObservableMixin
from ..core.interfaces import IMemoryManager

# Синтетическое имя процесса для standalone-режима (без PSR)
_STANDALONE_PROCESS = "_standalone"


class _MemoryMeta:
    """Метаданные одного shm-блока (params, index_usage, coll)."""

    __slots__ = ("params", "index_usage", "coll")

    def __init__(self, params: tuple, coll: int) -> None:
        self.params = params          # (num_images, image_shape, dtype)
        self.index_usage: List[int] = [0] * coll
        self.coll: int = coll


class MemoryManager(BaseManager, ObservableMixin, IMemoryManager):
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
        # {process_name: {shm_base_name: [SharedMemory, ...]}}
        self._local_handles: Dict[str, Dict[str, List[shared_memory.SharedMemory]]] = {}

        # Метаданные для standalone-режима (без PSR)
        # {process_name: {shm_base_name: _MemoryMeta}}
        self._local_meta: Dict[str, Dict[str, _MemoryMeta]] = {}

        # Owner создаёт (create=True) и unlink при shutdown.
        # Consumer только открывает (create=False) и close при shutdown.
        self._is_owner: bool = True

        self._stats = {"created": 0, "written": 0, "read": 0, "errors": 0}

    # =========================================================================
    # Жизненный цикл
    # =========================================================================

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
            return True  # standalone-режим: handles уже живут локально
        try:
            self._is_owner = False
            for process_name in self._process_state_registry.get_process_names():
                pd = self._process_state_registry.get_process_data(process_name)
                if pd is None:
                    continue
                memory_names_map: Dict[str, List[str]] = pd.custom.get("memory_names", {})
                if not memory_names_map:
                    continue
                for shm_base_name, shm_names_list in memory_names_map.items():
                    handles: List[Optional[shared_memory.SharedMemory]] = []
                    for shm_name in shm_names_list:
                        try:
                            shm = shared_memory.SharedMemory(name=shm_name, create=False)
                            handles.append(shm)
                        except Exception as e:
                            self._log_error(
                                f"reinitialize_handles: cannot open '{shm_name}': {e}"
                            )
                            handles.append(None)
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
        В обоих случаях handles живут в _local_handles[process_name].
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
            size = self._calculate_memory_size(num_images, image_shape, dtype)
            shm_list = self._create_shm_blocks(name, size, coll)
            if shm_list is None:
                self._log_warning(f"Failed to create memory for '{name}'")
                continue

            # Только имена в ProcessData — pickle-safe
            pd.custom["memory_names"][name] = [shm.name for shm in shm_list]
            pd.custom["memory_params"][name] = params
            pd.custom["memory_index_usage"][name] = [0] * coll
            pd.custom["memory_coll"][name] = coll

            # Handles — локально, не pickle
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
        """Создание без PSR: метаданные в _local_meta (только для текущего процесса)."""
        for name, params in memory_names.items():
            num_images, image_shape, dtype = params
            size = self._calculate_memory_size(num_images, image_shape, dtype)
            shm_list = self._create_shm_blocks(name, size, coll)
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
    ) -> Optional[str]:
        if not self._validate_memory_access(process_name, shm_name, index):
            return None
        if not self._validate_write_operation(process_name, shm_name, index, len(images)):
            return None
        try:
            memory_data = self.get_memory_data(process_name, shm_name)
            if not memory_data:
                return None

            handles = memory_data["handles"]
            shm = handles[index]
            buffer = shm.buf
            max_images, max_shape, expected_dtype = memory_data["params"][shm_name]
            max_h, max_w, max_c = max_shape

            buffer[0:4] = struct.pack("I", len(images))
            offset = 4
            for img in images:
                if img.dtype != expected_dtype:
                    raise ValueError(f"dtype mismatch: {img.dtype} != {expected_dtype}")
                h, w = img.shape[:2]
                c = 1 if img.ndim == 2 else img.shape[2]
                if h > max_h or w > max_w or c > max_c:
                    raise ValueError(
                        f"Image shape ({h}x{w}x{c}) exceeds max ({max_h}x{max_w}x{max_c})"
                    )
                buffer[offset:offset + 12] = struct.pack("III", h, w, c)
                offset += 12
                buffer[offset] = ord(img.dtype.char)
                offset += 1
                img_bytes = img.tobytes()
                buffer[offset:offset + len(img_bytes)] = img_bytes
                offset += len(img_bytes)
                padding = max_h * max_w * max_c * img.dtype.itemsize - len(img_bytes)
                if padding > 0:
                    buffer[offset:offset + padding] = b"\x00" * padding
                    offset += padding

            self._stats["written"] += 1
            return shm.name
        except Exception as e:
            self._log_error(f"write_images error: {e}")
            self._stats["errors"] += 1
            self._clear_memory(process_name, shm_name, index)
            return None

    def read_images(
        self,
        process_name: str,
        shm_name: str,
        index: int,
        n: int = -1,
    ) -> Optional[List[np.ndarray]]:
        if not self._validate_read_operation(process_name, shm_name, index):
            return None
        try:
            memory_data = self.get_memory_data(process_name, shm_name)
            if not memory_data:
                return None

            handles = memory_data["handles"]
            shm = handles[index]
            buffer = shm.buf
            _, max_shape, expected_dtype = memory_data["params"][shm_name]
            max_h, max_w, max_c = max_shape
            itemsize = np.dtype(expected_dtype).itemsize

            num_images = struct.unpack("I", buffer[0:4])[0]
            if num_images == 0:
                return []
            if n != -1:
                num_images = min(n, num_images)

            offset = 4
            images = []
            for _ in range(num_images):
                h, w, c = struct.unpack("III", buffer[offset:offset + 12])
                offset += 12
                dtype_char = chr(buffer[offset])
                dtype = np.dtype(dtype_char)
                offset += 1
                arr = np.frombuffer(buffer, dtype=dtype, count=h * w * c, offset=offset)
                images.append(arr.reshape((h, w, c)).copy())
                offset += max_h * max_w * max_c * itemsize

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
        self._clear_memory(process_name, shm_name, index)
        index_usage = memory_data["index_usage"]
        if shm_name in index_usage and 0 <= index < len(index_usage[shm_name]):
            index_usage[shm_name][index] = 0

    def close_memory(self, process_name: str, shm_name: str) -> None:
        """Закрыть и очистить один shm-блок."""
        handles = self._local_handles.get(process_name, {}).get(shm_name, [])
        for shm in handles:
            self._safe_close_shm(shm, unlink=self._is_owner)
        self._local_handles.get(process_name, {}).pop(shm_name, None)

        # Удалить метаданные
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
        """Единый безопасный close/unlink (DRY)."""
        if shm is None:
            return
        try:
            shm.close()
        except Exception as e:
            self._log_error(f"shm.close() failed: {e}")
        if unlink:
            try:
                shm.unlink()
            except FileNotFoundError:
                pass
            except Exception as e:
                self._log_error(f"shm.unlink() failed: {e}")

    def _close_all_handles(self) -> None:
        for process_name, shm_map in list(self._local_handles.items()):
            for shm_name, handles in shm_map.items():
                for shm in handles:
                    self._safe_close_shm(shm, unlink=self._is_owner)
        self._local_handles.clear()

    def _create_shm_blocks(
        self, shm_name_orig: str, size: int, coll: int
    ) -> Optional[List[shared_memory.SharedMemory]]:
        shm_list: List[shared_memory.SharedMemory] = []
        for i in range(coll):
            shm_name = f"{shm_name_orig}_{i}"
            try:
                shm = shared_memory.SharedMemory(name=shm_name, create=True, size=size)
                shm_list.append(shm)
            except Exception as e:
                self._log_error(f"Cannot create SharedMemory '{shm_name}': {e}")
                for created in shm_list:
                    self._safe_close_shm(created, unlink=True)
                return None
        return shm_list

    def _calculate_memory_size(
        self, num_images: int, image_shape: tuple, dtype: Any
    ) -> int:
        h, w, c = image_shape
        itemsize = np.dtype(dtype).itemsize
        return 4 + num_images * (12 + 1 + h * w * c * itemsize)

    def _validate_memory_access(
        self, process_name: str, shm_name: str, index: int
    ) -> bool:
        memory_data = self.get_memory_data(process_name, shm_name)
        if not memory_data:
            self._log_warning(f"Memory '{shm_name}' not initialized for '{process_name}'")
            return False
        coll = memory_data["coll"]
        if shm_name not in coll or index >= coll[shm_name]:
            self._log_warning(f"Invalid index {index} for '{shm_name}'")
            return False
        handles = memory_data.get("handles")
        if handles is None or index >= len(handles) or handles[index] is None:
            self._log_warning(f"Memory handle {index} for '{shm_name}' is None")
            return False
        return True

    def _validate_write_operation(
        self, process_name: str, shm_name: str, index: int, num_images: int
    ) -> bool:
        memory_data = self.get_memory_data(process_name, shm_name)
        if not memory_data:
            return False
        coll = memory_data["coll"]
        if shm_name not in coll or index >= coll[shm_name]:
            self._log_warning(f"Invalid index {index} for '{shm_name}'")
            return False
        max_images = memory_data["params"][shm_name][0]
        if num_images > max_images:
            self._log_warning(f"Too many images ({num_images} > {max_images})")
            return False
        return True

    def _validate_read_operation(
        self, process_name: str, shm_name: str, index: int
    ) -> bool:
        return self._validate_memory_access(process_name, shm_name, index)

    def _clear_memory(self, process_name: str, shm_name: str, index: int) -> None:
        if self._validate_memory_access(process_name, shm_name, index):
            memory_data = self.get_memory_data(process_name, shm_name)
            if memory_data:
                handles = memory_data.get("handles")
                if handles and index < len(handles) and handles[index]:
                    try:
                        handles[index].buf[:] = b"\x00" * handles[index].size
                    except Exception as e:
                        self._log_error(f"_clear_memory error: {e}")

    # =========================================================================
    # Статистика
    # =========================================================================

    def get_stats(self) -> Dict[str, Any]:
        base = super().get_stats() if hasattr(super(), "get_stats") else {}
        mem_stats = {
            **self._stats,
            "processes_with_handles": len(self._local_handles),
            "is_owner": self._is_owner,
        }
        if isinstance(base, dict):
            base["memory"] = mem_stats
        else:
            base = {"memory": mem_stats}
        return base
