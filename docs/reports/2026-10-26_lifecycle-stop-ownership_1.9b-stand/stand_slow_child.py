# -*- coding: utf-8 -*-
"""Дети стенда T1.9b: тонкие обёртки над тестовым классом ``LifecycleChild`` (production-код не тронут).

Зачем обёртка. ``topology.apply`` собирает процесс из чертежа (``ProcessConfig``), а лишние ключи чертежа
(``stop_delay_s``) до ребёнка не доезжают (``blueprint.py``, комментарий про ``extras``: «до GenericProcess доезжает
только будучи названным»). Поэтому задержка стопа зашита в класс: ``SlowChild`` — ``stop_delay_s`` = 3,0 с,
``FastChild`` — 0,0 с. Остальное поведение — ``LifecycleChild`` без правок (хук ``stop()`` спит ``stop_delay_s``).

Модуль импортируется детьми по dotted-пути ``stand_slow_child.SlowChild``; для этого каталог стенда стоит в
``PYTHONPATH`` бэкенда (его ставит ``stand_l9.py``).
"""

from __future__ import annotations

import os
from typing import Any

from multiprocess_framework.modules.process_manager_module.tests._lifecycle_fifo_helpers import LifecycleChild

SLOW_STOP_DELAY_S = 3.0


class SlowChild(LifecycleChild):
    """Медленный ребёнок: стоп 3,0 с."""

    def __init__(self, name: str, shared_resources: Any, config: Any) -> None:
        cfg = dict(config) if isinstance(config, dict) else {}
        cfg["stop_delay_s"] = SLOW_STOP_DELAY_S
        super().__init__(name, shared_resources, cfg)


class S6SlowChild(LifecycleChild):
    """Медленный ребёнок S6: стоп ``STAND_S6_SLOW_STOP_S`` с (по умолчанию 6,0 > окна 5,0).

    Значение берётся из окружения бэкенда (стенд ставит его в env; spawn-дети наследуют env). S2 (``SlowChild``, 3,0 с)
    не затронут.
    """

    def __init__(self, name: str, shared_resources: Any, config: Any) -> None:
        cfg = dict(config) if isinstance(config, dict) else {}
        cfg["stop_delay_s"] = float(os.environ.get("STAND_S6_SLOW_STOP_S", "6.0"))
        super().__init__(name, shared_resources, cfg)


class FastChild(LifecycleChild):
    """Быстрый ребёнок: стоп без задержки (цель очереди ``process.restart`` в S4)."""

    def __init__(self, name: str, shared_resources: Any, config: Any) -> None:
        cfg = dict(config) if isinstance(config, dict) else {}
        cfg["stop_delay_s"] = 0.0
        super().__init__(name, shared_resources, cfg)
