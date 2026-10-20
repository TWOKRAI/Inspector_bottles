# -*- coding: utf-8 -*-
"""Ребёнок-зависатель для live-тестов Task 0.2 (``system.shutdown mode=force``).

Зависает не на старте, а на ЗАКРЫТИИ: вызываемое в области ``work`` корня процесса выполняется на
потоке закрывающего (``lifetime.py``: «вызываемое не прерывается сроком») и держит выход ребёнка 8 с.
Для PM это ровно «ребёнок не уложился в срок»: ему положены terminate и строка
``Process '<имя>' did not stop in <N>s, terminating...``.

Класс указывается в ``process_class`` рецепта; плагины и остальное поведение — у ``GenericProcessApp``.
Модуль лежит в каталоге тестов, не в ``src`` (бриф Task 0.2).
"""

from __future__ import annotations

import time

from multiprocess_prototype.generic_process_app import GenericProcessApp

HANG_SECONDS = 8.0
HUNG_PROCESS_CLASS_PATH = "backend_ctl.tests._hung_child_plugin.HangOnCloseProcess"


def _hang_on_close() -> None:
    time.sleep(HANG_SECONDS)


class HangOnCloseProcess(GenericProcessApp):
    """``GenericProcessApp``, чей корень при закрытии спит ``HANG_SECONDS`` секунд."""

    def initialize(self) -> bool:
        ok = super().initialize()
        if ok:
            self.lifetime_segments["work"].own(_hang_on_close, name="hung_close", kind="callable")
        return ok
