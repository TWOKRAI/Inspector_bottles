"""
Process 2 — процесс с воркерами из конфига.
"""

from multiprocess_framework.refactored.modules.process_module import ProcessModule


class Process2Module(ProcessModule):
    """Процесс 2. Воркеры создаются из config["workers"]."""
