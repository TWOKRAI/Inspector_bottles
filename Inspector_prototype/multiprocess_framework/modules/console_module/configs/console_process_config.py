"""
ConsoleProcessConfig — конфигурация God Mode процесса.

God Mode — отдельный процесс с интерактивной консолью:
  User → ConsoleManager → CommandManager → RouterManager → любой процесс

Использование:
    launcher = SystemLauncher()
    launcher.add_process(*process(ConsoleProcessConfig()))
    launcher.add_process(*process(MyWorkerConfig()))
    launcher.run()
"""
from typing import Dict, Any

from ...data_schema_module.core.schema_base import SchemaBase


class ConsoleProcessConfig(SchemaBase):
    """Конфиг для standalone консольного процесса (God Mode)."""

    process_name: str = "console_app"
    process_class: str = (
        "Inspector_prototype.multiprocess_framework.modules"
        ".process_module.core.process_module.ProcessModule"
    )
    managers: Dict[str, Any] = {
        "console": {
            "enabled": True,
            "interactive": True,
            "title": "Console — God Mode",
            "redirect_stdout": False,
        }
    }
