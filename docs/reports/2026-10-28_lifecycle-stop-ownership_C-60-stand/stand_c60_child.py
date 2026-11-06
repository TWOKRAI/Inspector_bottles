# -*- coding: utf-8 -*-
"""Ребёнок ``c60`` стенда C-60/S8: процесс с исполнителем ``io`` (serial) и плагином-зондом.

Production-код не тронут. Класс грузится дочерним процессом по dotted-пути ``stand_c60_child.C60Child``; для этого
каталог стенда стоит в ``PYTHONPATH`` бэкенда (его ставит ``stand_c60.py``).

Лишние ключи чертежа ``topology.apply`` до ребёнка не доезжают (см. ``stand_slow_child.py``), поэтому конфиг
(исполнитель + плагин) вшит в ``__init__``, а путь метки и длина операции едут через окружение бэкенда
(``STAND_C60_MARK``, ``STAND_C60_L``): spawn-дети наследуют env.

Зонд пишет в файл-метку строки ``<событие>\\t<time.monotonic()>``:
``op_start`` / ``op_end`` (долгая операция ``c60.slow_io``), ``request_stop`` и ``shutdown`` (хуки плагина).
Метод ``request_stop`` определён в классе всегда: на базе (``da3febe8e``) фреймворк его не зовёт (хука там нет),
на ветке C-60 зовёт. Падать зонду от отсутствия хука нечем: ``super().request_stop`` не вызывается.
"""

from __future__ import annotations

import os
import time
from typing import Any

from multiprocess_framework.modules.process_module.generic.generic_process import GenericProcess
from multiprocess_framework.modules.process_module.plugins.base import PluginContext, ProcessModulePlugin

PLUGIN_NAME = "c60probe"
COMMAND = "c60.slow_io"
DEFAULT_L_S = 10.0


def write_mark(path: str, event: str) -> None:
    """Дописать метку и закрыть файл (метка видна сразу, даже если процесс потом убьют)."""
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(f"{event}\t{time.monotonic():.6f}\n")


class C60Probe(ProcessModulePlugin):
    """Зонд: долгая команда на исполнителе ``io`` и метки хуков остановки."""

    name = PLUGIN_NAME
    commands = {COMMAND: "slow_io"}

    def __init__(self) -> None:
        super().__init__()
        self._mark = ""
        self._length_s = DEFAULT_L_S

    def configure(self, ctx: PluginContext) -> None:
        self._mark = str(ctx.config.get("mark_path", ""))
        self._length_s = float(ctx.config.get("slow_s", DEFAULT_L_S))

    def start(self, ctx: PluginContext) -> None:
        pass

    def command_options(self, command_name: str) -> dict[str, Any]:
        if command_name == COMMAND:
            return {"executor": "io", "targets": "all"}
        return {}

    def slow_io(self, data: dict) -> dict:
        """Операция на потоке исполнителя ``io``: спит ``L`` с без прерывания."""
        write_mark(self._mark, "op_start")
        time.sleep(self._length_s)
        write_mark(self._mark, "op_end")
        return {"success": True}

    def request_stop(self, ctx: PluginContext) -> None:
        write_mark(self._mark, "request_stop")

    def shutdown(self, ctx: PluginContext) -> None:
        write_mark(self._mark, "shutdown")


class C60Child(GenericProcess):
    """GenericProcess с исполнителем ``io`` (serial) и плагином-зондом; конфиг вшит, пути — из env."""

    def __init__(self, name: str, shared_resources: Any, config: Any, *args: Any, **kwargs: Any) -> None:
        cfg = dict(config) if isinstance(config, dict) else {}
        inner = dict(cfg.get("config") or {})
        inner["executors"] = {"io": {"serial": True}}
        inner["plugins"] = [
            {
                "plugin_name": PLUGIN_NAME,
                "plugin_class": f"{__name__}.C60Probe",
                "config": {
                    "mark_path": os.environ.get("STAND_C60_MARK", ""),
                    "slow_s": float(os.environ.get("STAND_C60_L", str(DEFAULT_L_S))),
                },
            }
        ]
        cfg["config"] = inner
        super().__init__(name, shared_resources, cfg, *args, **kwargs)
