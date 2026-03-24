"""Launcher для запуска системы."""

from .system_launcher import SystemLauncher, main as launcher_main
from .spawner import ProcessSpawner
from .schema import DEFAULT_PROCESS_SCHEMA

__all__ = ['SystemLauncher', 'ProcessSpawner', 'DEFAULT_PROCESS_SCHEMA', 'launcher_main']

