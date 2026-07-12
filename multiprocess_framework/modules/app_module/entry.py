"""``run_app`` / ``build_app`` — точка входа «рыбы» (Ф5.11).

Новое приложение = данные + декларации, ``run.py`` в ~3 строки::

    from multiprocess_framework.modules.app_module import run_app
    run_app(Path(__file__).parent / "app.yaml")

``build_app`` собирает (не запускает) ``SystemLauncher`` — удобно тестам/harness'у
(headless smoke без блокирующего ``run()``). ``run_app`` = ``build_app`` + ``run()``.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Union

from .builder import AppSpec, SystemBuilder

if TYPE_CHECKING:
    from multiprocess_framework.modules.process_manager_module.launcher.system_launcher import (
        SystemLauncher,
    )

#: Что принимает вход: путь к ``app.yaml`` (generic-дефолты) ИЛИ :class:`AppSpec` (DI).
AppInput = Union[str, Path, AppSpec]


def _coerce_spec(app: AppInput) -> AppSpec:
    if isinstance(app, AppSpec):
        return app
    return AppSpec(manifest_path=Path(app))


def build_app(app: AppInput) -> "SystemLauncher":
    """Собрать ``SystemLauncher`` из ``app.yaml`` или :class:`AppSpec` (без запуска).

    Args:
        app: путь к манифесту (generic-путь) или :class:`AppSpec` (полный DI).

    Returns:
        Сконфигурированный, НЕ запущенный ``SystemLauncher``.
    """
    return SystemBuilder(_coerce_spec(app)).build()


def run_app(app: AppInput) -> int:
    """Собрать и запустить приложение (блокирующий ``launcher.run()``).

    Args:
        app: путь к ``app.yaml`` или :class:`AppSpec`.

    Returns:
        Код возврата (0 — штатное завершение).
    """
    launcher = build_app(app)
    launcher.run()
    return 0
