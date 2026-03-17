# multiprocess_prototype\utils\shm_utils.py
"""
Утилиты для работы с SharedMemory (формат MemoryManager).
"""

import struct
from multiprocessing import shared_memory

import numpy as np


def read_frame_from_shm(shm_actual_name: str, width: int, height: int):
    """
    Прочитать кадр из SharedMemory по имени (формат MemoryManager).
    Возвращает np.ndarray или None при ошибке.
    """
    if not shm_actual_name or not isinstance(shm_actual_name, str):
        return None
    try:
        shm = shared_memory.SharedMemory(name=shm_actual_name, create=False)
        try:
            buffer = shm.buf
            num_images = struct.unpack("I", buffer[0:4])[0]
            if num_images == 0:
                return None
            offset = 4
            h, w, c = struct.unpack("III", buffer[offset : offset + 12])
            offset += 12
            dtype_char = chr(buffer[offset])
            dtype = np.dtype(dtype_char)
            offset += 1
            arr = np.frombuffer(
                buffer, dtype=dtype, count=h * w * c, offset=offset
            )
            result = arr.reshape((h, w, c)).copy()
            del arr  # освободить view до close — иначе BufferError на Windows
            return result
        finally:
            shm.close()
    except FileNotFoundError as e:
        print(
            f"[shm_utils] SharedMemory '{shm_actual_name}' not found (FileNotFoundError): {e}",
            flush=True,
        )
        return None
    except Exception as e:
        print(
            f"[shm_utils] read_frame_from_shm('{shm_actual_name}') failed: {type(e).__name__}: {e}",
            flush=True,
        )
        return None
