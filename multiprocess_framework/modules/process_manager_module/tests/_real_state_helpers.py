# -*- coding: utf-8 -*-
"""Task 1.8b (L4): обвязка тестов супервизора с НАСТОЯЩИМ реестром состояний процессов.

Почему отдельный модуль: в общем ``conftest.py`` ``MockSharedResources.process_state_registry`` — ``MagicMock``.
Статус процесса «по имени» (дефект 1.8b: новое воплощение наследует ``crashed`` / ``unresponsive``) на моке не виден —
``get_all_process_data()`` мока пуст, монитор каждый такт «снимает» процесс. Тест супервизора, у которого путь
«рестарт -> реестр -> такт монитора» должен быть настоящим, подменяет ``pm.shared_resources`` через эту функцию.
Общий ``conftest`` не меняется: остальные тесты PM продолжают жить на моке.
"""

from __future__ import annotations

from typing import Any

from ...shared_resources_module.core.shared_resources_manager import SharedResourcesManager


def attach_real_srm(pm: Any, configs: dict[str, dict]) -> SharedResourcesManager:
    """Подменить ``pm.shared_resources`` настоящим ``SharedResourcesManager`` (настоящие PSR, очереди, события).

    Каждый процесс из ``configs`` зарегистрирован так же, как при boot (``register_process`` -> запись PSR со статусом
    ``initializing``). Возвращает SRM: тест читает ``srm.process_state_registry``.
    """
    srm = SharedResourcesManager(manager_name="supervisor_test_srm")
    assert srm.initialize() is True
    for name, cfg in configs.items():
        assert srm.register_process(name, dict(cfg)) is True
    pm.shared_resources = srm
    return srm
