# -*- coding: utf-8 -*-
"""hikvision_embed — фабрика встраиваемых контролов камеры Hikvision (F.6).

Дублирует Services-секцию «Hikvision Camera» прямо в карточке ноды инспектора
(поиск/захват/параметры/SDK App). Требует command_sender/topology_bridge (через
set_services из RuntimeDeps); без них кнопки дадут понятный статус «нет процесса камеры».

Импорты ленивые (внутри функции) — избегаем циклов при загрузке модуля инспектора.
"""

from __future__ import annotations

from typing import Any


def create_hikvision_widget(
    services: Any,
    command_sender: Any,
    topology_bridge: Any,
) -> tuple[Any, Any, Any]:
    """Собрать виджет контролов Hikvision.

    Returns:
        (widget, controller, runner) — вызывающая сторона держит ссылки на controller
        и runner (иначе GC), widget вставляется в форму параметров.
    """
    from types import SimpleNamespace

    from multiprocess_prototype.frontend.bridge.request_runner import RequestRunner
    from multiprocess_prototype.frontend.widgets.tabs.services.hikvision.controller import (
        build_hikvision_controls,
    )

    runtime = SimpleNamespace(command_sender=command_sender, topology_bridge=topology_bridge)
    runner = RequestRunner()
    widget, controller = build_hikvision_controls(
        services=services,
        runtime=runtime,
        request_runner=runner,
    )
    runner.setParent(widget)
    return widget, controller, runner
