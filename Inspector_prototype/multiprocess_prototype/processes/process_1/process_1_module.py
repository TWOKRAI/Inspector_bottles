"""
Process 1 — процесс с воркерами из конфига.
"""

from multiprocess_framework.refactored.modules.process_module import ProcessModule


class Process1Module(ProcessModule):
    """Процесс 1. Воркеры создаются из config["workers"]."""
