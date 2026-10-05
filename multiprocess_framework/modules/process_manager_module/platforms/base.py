"""
Базовые абстракции для платформо-зависимых операций (Refactored).
"""

from typing import Dict, Any
from multiprocessing import Process


class StubPlatformAdapter:
    """Заглушка: setup_multiprocessing, приоритеты не применяются."""

    def setup_multiprocessing(self) -> None:
        """Метод запуска процессов — ``spawn`` на ВСЕХ ОС (Атлас 0.8b, решение владельца 2026-10-05).

        Post: ``get_start_method(allow_none=True) == "spawn"``. Идемпотентна. Если метод уже
        выставлен другой (``fork``/``forkserver`` — например, первый же ``multiprocessing.Event()``
        на Linux зафиксировал умолчание ОС), бросает ``RuntimeError``: молча жить на другом
        методе нельзя, а смена после фиксации невозможна.
        """
        import multiprocessing
        import sys

        current = multiprocessing.get_start_method(allow_none=True)
        if current is None:
            multiprocessing.set_start_method("spawn")
        elif current != "spawn":
            raise RuntimeError(f"start method already set to {current}; framework requires spawn")
        if sys.platform == "win32":
            try:
                import multiprocessing

                multiprocessing.freeze_support()
            except Exception:
                pass

    def get_priority_map(self) -> Dict[str, Any]:
        return {"normal": 0}

    def apply_priority(self, process: Process, priority_name: str) -> bool:
        return False
