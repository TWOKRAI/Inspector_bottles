# -*- coding: utf-8 -*-
"""Дети с управляемым временем выхода для приёмки C-88 («у каждого ребёнка честный итог стопа»).

Как у ``backend_ctl.tests._hung_child_plugin``: вызываемое в области ``work`` корня процесса исполняется на
потоке закрывающего и держит выход ребёнка ``SLEEP_ON_CLOSE_S`` секунд. Класс указывается в ``process_class``
рецепта; всё остальное поведение — у ``GenericProcessApp``.

  * ``Sleep05Process``    — выход ~0.5 с после команды стопа (медленнее соседей, но в окне стопа);
  * ``Sleep30Process``    — 30 с на закрытии: окно стопа кончится раньше, SIGTERM его убьёт (-> ``terminated``);
  * ``IgnoreTermProcess`` — то же, но SIGTERM игнорируется: уйдёт только от kill (-> ``killed``).
"""

from __future__ import annotations

import signal
import time

from multiprocess_prototype.generic_process_app import GenericProcessApp

_PKG = "backend_ctl.tests.fixtures.c88.slow_exit_children"
SLEEP05_CLASS_PATH = f"{_PKG}.Sleep05Process"
SLEEP30_CLASS_PATH = f"{_PKG}.Sleep30Process"
IGNORE_TERM_CLASS_PATH = f"{_PKG}.IgnoreTermProcess"


class _SleepOnCloseProcess(GenericProcessApp):
    SLEEP_ON_CLOSE_S = 0.0
    IGNORE_SIGTERM = False

    def initialize(self) -> bool:
        ok = super().initialize()
        if ok:
            if self.IGNORE_SIGTERM:
                signal.signal(signal.SIGTERM, signal.SIG_IGN)
            seconds = float(self.SLEEP_ON_CLOSE_S)
            self.lifetime_segments["work"].own(lambda: time.sleep(seconds), name="c88_close_sleep", kind="callable")
        return ok


class Sleep05Process(_SleepOnCloseProcess):
    SLEEP_ON_CLOSE_S = 0.5


class Sleep30Process(_SleepOnCloseProcess):
    SLEEP_ON_CLOSE_S = 30.0


class IgnoreTermProcess(_SleepOnCloseProcess):
    SLEEP_ON_CLOSE_S = 30.0
    IGNORE_SIGTERM = True
