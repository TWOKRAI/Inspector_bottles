"""WorkerAdapter — IPC/SHM facade для ProcessorWorkerProcess."""
from __future__ import annotations

import numpy as np
from multiprocess_framework.modules.process_module import ProcessIO


class WorkerAdapter:
    """Реализует IPC/SHM операции для воркера через ProcessIO facade.

    Инкапсулирует:
    - Чтение input frame из SHM другого процесса (по координатам из запроса)
    - Запись output frame в собственный SHM-слот
    - Отправка response обратно source-процессу
    """

    def __init__(self, process, result_shm_slot: str) -> None:
        self._io = ProcessIO(process)
        self._process = process
        self._result_shm_slot = result_shm_slot

    def read_input_frame(
        self,
        shm_name: str,
        owner: str,
        index: int,
        shape: tuple,
    ) -> np.ndarray | None:
        """Прочитать frame из SHM по координатам из worker_task_request.

        Args:
            shm_name: Имя SHM-слота (например 'processor_0_worker_pool_input').
            owner: Имя процесса-владельца SHM (например 'processor').
            index: Индекс кадра в SHM-блоке.
            shape: Ожидаемая форма кадра (H, W, C).

        Returns:
            np.ndarray кадра или None если чтение не удалось.
        """
        mm = self._process.memory_manager
        if not mm:
            self._io.log_error("MemoryManager недоступен для чтения input frame")
            return None

        # Определяем владельца SHM: если явно указан — используем,
        # иначе пытаемся извлечь из имени SHM
        if not owner:
            # Fallback: владелец — первая часть имени SHM до '_'
            # (processor_0_worker_pool_input → processor)
            owner = shm_name.split("_")[0] if shm_name else ""

        frames = mm.read_images(owner, shm_name, index, n=1, copy=True)
        if not frames:
            self._io.log_error(
                f"Не удалось прочитать frame из SHM: owner={owner}, "
                f"slot={shm_name}, index={index}"
            )
            return None

        return frames[0]

    def write_output_frame(self, frame: np.ndarray) -> tuple[str, int] | None:
        """Записать output frame в собственный SHM-слот результата.

        Returns:
            Tuple (shm_actual_name, index) или None если запись не удалась.
        """
        result = self._io.write_frames_to_shm(
            self._process.name, self._result_shm_slot, [frame]
        )
        if result is None:
            self._io.log_error(
                f"Не удалось записать output frame в SHM: "
                f"slot={self._result_shm_slot}"
            )
            return None
        return result.get("shm_actual_name", self._result_shm_slot), result.get("shm_index", 0)

    def send_response(self, target: str, response_dict: dict) -> None:
        """Отправить worker_task_response обратно source-процессу."""
        self._io.send_data(target, "worker_task_response", response_dict)
