"""
Базовые абстракции для платформо-зависимых операций (Refactored).
"""

from typing import Dict, Any
from multiprocessing import Process


class StubPlatformAdapter:
    """Заглушка: setup_multiprocessing, приоритеты не применяются."""

    def setup_multiprocessing(self) -> None:
        import sys
        if sys.platform == "win32":
            try:
                import multiprocessing
                multiprocessing.set_start_method("spawn", force=False)
            except RuntimeError:
                pass
            try:
                import multiprocessing
                multiprocessing.freeze_support()
            except Exception:
                pass

    def get_priority_map(self) -> Dict[str, Any]:
        return {"normal": 0}

    def apply_priority(self, process: Process, priority_name: str) -> bool:
        return False
