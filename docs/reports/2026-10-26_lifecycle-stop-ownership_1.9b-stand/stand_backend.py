# -*- coding: utf-8 -*-
"""Вход бэкенда для стенда T1.9b: то же, что ``multiprocess_prototype/run.py --headless``, с двумя отличиями.

1. Без venv-guard ``run.py``: он переключается на ``<корень>/.venv``, а в worktree ``.venv`` нет
   (``run.py:34-41`` вернул бы «не найден проектный venv»). Дальше путь тот же: ``main.main(headless=True)``.
2. ``STAND_STOP_PROCESS_TIMEOUT`` (если задан) кладёт ``stop_process_timeout`` в ``orchestrator_config`` ProcessManager.
   Другого пути к этому ключу нет: ``launch.py:750-791`` собирает ``orchestrator_config`` литералом без него, в
   ``system.yaml`` его нет, env он не читает; ``process_manager_process.py:1978,3829,4388`` берут ``... or 5.0``.
   ``shutdown_timeout`` этим входом НЕ задаётся: он едет из ``system.stop_timeout`` временного ``system.yaml``
   (``launch.py:786`` -> ``spawner.py:90-92``).
3. ``STAND_MAX_STOP_WINDOW`` (если задан; S7, T1.11) кладёт ``max_stop_window_s`` в тот же ``orchestrator_config``
   тем же патчем (потолок окон ``stop_window_s`` детей; PM читает ``get_config("max_stop_window_s")``).

Подмена живёт только в этом процессе (временный патч атрибута пакета ``launcher``); закоммиченные файлы не меняются.
Строка ``[stand] ...`` в stdout — доказательство, что подмена сработала (``stand_l9.py`` проверяет её наличие).
"""

from __future__ import annotations

import os
import sys


def _install_stop_process_timeout(value: str | None, max_window: str | None = None) -> None:
    """Один патч ``assemble_launcher`` на два ключа: ``stop_process_timeout`` (S1-S7), ``max_stop_window_s`` (S7).

    ``max_stop_window_s`` - потолок окон ``stop_window_s`` детей; PM читает его ``get_config("max_stop_window_s")``
    из ``orchestrator_config``. Задан только он (R2-C) - ``stop_process_timeout`` не трогается.
    """
    import multiprocess_framework.modules.process_manager_module.launcher as launcher_pkg

    original = launcher_pkg.assemble_launcher
    timeout = float(value) if value else None
    ceiling = float(max_window) if max_window else None

    def patched(proc_dicts, *args, orchestrator_config=None, **kwargs):
        cfg = dict(orchestrator_config or {})
        if timeout is not None:
            cfg["stop_process_timeout"] = timeout
            print(
                f"[stand] orchestrator_config.stop_process_timeout={timeout} stop_timeout={kwargs.get('stop_timeout')}",
                flush=True,
            )
        if ceiling is not None:
            cfg["max_stop_window_s"] = ceiling
            print(f"[stand] orchestrator_config.max_stop_window_s={ceiling}", flush=True)
        return original(proc_dicts, *args, orchestrator_config=cfg, **kwargs)

    launcher_pkg.assemble_launcher = patched


def main() -> int:
    value = os.environ.get("STAND_STOP_PROCESS_TIMEOUT")
    max_window = os.environ.get("STAND_MAX_STOP_WINDOW")
    if value or max_window:
        _install_stop_process_timeout(value, max_window)
    from multiprocess_prototype.main import main as app_main

    return app_main(None, headless=True)


if __name__ == "__main__":
    sys.exit(main())
