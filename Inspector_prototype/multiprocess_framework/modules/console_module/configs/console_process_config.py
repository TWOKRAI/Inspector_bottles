"""
God Mode: отдельный процесс с консолью. Пример: launcher.add_process(*process(ConsoleProcessConfig())).
"""
from __future__ import annotations

from typing import Annotated, Any, Dict, Tuple

from pydantic import Field

from ...data_schema_module import FieldMeta, register_schema, SchemaBase
from ...process_module.configs.managers_config import ManagersConfig
from .console_config import ConsoleConfig

_DEFAULT_PROCESS_CLASS = (
    "Inspector_prototype.multiprocess_framework.modules"
    ".process_module.core.process_module.ProcessModule"
)


def _god_managers() -> ManagersConfig:
    """God Mode: консоль интерактивна, остальные секции — дефолты ManagersConfig."""
    return ManagersConfig(
        console=ConsoleConfig(
            enabled=True,
            interactive=True,
            title="Console — God Mode",
            redirect_stdout=False,
        ),
    )


@register_schema("ConsoleProcessConfig")
class ConsoleProcessConfig(SchemaBase):
    """Standalone консольный процесс (God Mode)."""

    process_name: Annotated[
        str,
        FieldMeta("Имя процесса", info="Ключ процесса в launcher / shared registry."),
    ] = "console_app"

    process_class: Annotated[
        str,
        FieldMeta("Класс процесса", info="Полный путь к классу ProcessModule."),
    ] = _DEFAULT_PROCESS_CLASS

    managers: Annotated[
        ManagersConfig,
        FieldMeta("Секции менеджеров процесса (канон: config.managers в ProcessModule)."),
    ] = Field(default_factory=_god_managers)

    def build(self) -> Tuple[str, Dict[str, Any]]:
        """Как :class:`ProcessLaunchConfig`: ``(process_name, {class, config})``."""
        payload = self.model_dump()
        name = str(payload.pop("process_name"))
        class_path = str(payload.pop("process_class"))
        return name, {"class": class_path, "config": payload}
