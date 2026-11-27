"""Зеркало ``system.progress.<id>`` из стора PM в UDP-посылки заставке.

Грузится только в процессе PM (там фреймворк уже импортирован); процесс заставки этот модуль не берёт.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Mapping

from multiprocess_framework.modules.process_module.progress import PROGRESS_ROOT
from multiprocess_framework.modules.state_store_module.core.delta import Delta
from multiprocess_framework.modules.state_store_module.middleware.base import StateMiddleware

from multiprocess_prototype.splash.interface import LeafSender
from multiprocess_prototype.splash.protocol import SPLASH_PORT_ENV, parse_port, send_leaf

_PREFIX = f"{PROGRESS_ROOT}."


class ProgressMirror(StateMiddleware):
    """После записи целого листа ``system.progress.<id>`` отдать его ``send(id, leaf)``.

    Состояние — только флаг «об ошибке уже сказано» (гонка за него даёт лишнюю строку, не больше):
    ``after_set`` зовут два потока PM.
    """

    def __init__(self, send: LeafSender) -> None:
        self._send = send
        self._complained = False

    @property
    def name(self) -> str:
        return "progress_mirror"

    def after_set(self, delta: Delta, context: dict) -> None:
        """Не бросает: исключение отсюда сорвало бы рассылку дельты подписчикам."""
        try:
            path = delta.path
            if not path.startswith(_PREFIX):
                return
            progress_id = path[len(_PREFIX) :]
            if not progress_id or "." in progress_id or not isinstance(delta.new_value, dict):
                return
            self._send(progress_id, delta.new_value)
        except Exception as exc:  # noqa: BLE001
            if not self._complained:
                self._complained = True
                print(f"[splash] зеркало прогресса не отправило лист: {exc}", file=sys.stderr)


def install_if_enabled(store_manager: object, environ: Mapping[str, str] = os.environ) -> bool:
    """Поставить зеркало, если задан порт заставки. Не бросает (зовётся внутри ``initialize()`` PM).

    Порт читается один раз здесь. Нет стора или порта — ``False`` и ни одного middleware.
    """
    try:
        port = parse_port(environ.get(SPLASH_PORT_ENV))
        if store_manager is None or port is None:
            return False
        target = {SPLASH_PORT_ENV: str(port)}
        store_manager.use(ProgressMirror(lambda progress_id, leaf: send_leaf(progress_id, leaf, environ=target)))
    except Exception as exc:  # noqa: BLE001
        print(f"[splash] зеркало прогресса не поставлено: {exc}", file=sys.stderr)
        return False
    return True
