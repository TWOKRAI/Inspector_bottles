"""
Конфигурация GUI-процесса (GuiProcess).

ProcessConfigBase + FieldMeta для валидации параметров.
build() — HasBuild для process() / add_process().
"""

from typing import Annotated

from multiprocess_framework.refactored.modules.data_schema_module import (
    FieldMeta,
    register_schema,
)

from multiprocess_prototype.configs.base_config import ProcessConfigBase


@register_schema("GuiConfig")
class GuiConfig(ProcessConfigBase):
    """Конфигурация GUI-процесса."""

    process_name: str = "gui"
    window_title: str = "Inspector Prototype"
    window_width: Annotated[
        int, FieldMeta("Ширина окна", min=400, max=1920)
    ] = 1024
    window_height: Annotated[
        int, FieldMeta("Высота окна", min=300, max=1080)
    ] = 768
    poll_interval_ms: Annotated[
        int, FieldMeta("Интервал опроса сообщений, мс", min=5, max=100)
    ] = 16

    def build(self) -> tuple[str, dict]:
        """HasBuild: (name, proc_dict) для launcher.add_process(*process(GuiConfig()))."""
        proc_dict = self._build_proc_dict(
            "multiprocess_prototype.processes.gui_process.GuiProcess",
        )
        return (self.process_name, proc_dict)
