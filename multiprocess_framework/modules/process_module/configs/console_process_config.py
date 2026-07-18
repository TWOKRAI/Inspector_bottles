# -*- coding: utf-8 -*-
"""
God Mode: отдельный процесс с консолью. Пример: launcher.add_process(*process(ConsoleProcessConfig())).
"""

from __future__ import annotations

from typing import Annotated

from pydantic import Field

from ...console_module.configs.console_config import ConsoleConfig
from ...data_schema_module import FieldMeta, register_schema
from .managers_config import ManagersConfig
from .process_launch_config import ProcessLaunchConfig


def _god_managers() -> ManagersConfig:
    """Интерактивная консоль; прочие секции — дефолты :class:`ManagersConfig`."""
    return ManagersConfig(
        console=ConsoleConfig(
            enabled=True,
            interactive=True,
            title="Console — God Mode",
            redirect_stdout=False,
        ),
    )


@register_schema("ConsoleProcessConfig")
class ConsoleProcessConfig(ProcessLaunchConfig):
    """Standalone консольный процесс (God Mode). ``build()`` — у :class:`ProcessLaunchConfig`."""

    process_name: Annotated[
        str,
        FieldMeta("Имя процесса", info="Ключ процесса в launcher / shared registry."),
    ] = "console_app"

    managers: Annotated[
        ManagersConfig,
        FieldMeta("Секции менеджеров процесса (канон: config.managers в ProcessModule)."),
    ] = Field(default_factory=_god_managers)
