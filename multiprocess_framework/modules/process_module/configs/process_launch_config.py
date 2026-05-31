"""ProcessLaunchConfig — base SchemaBase config for launcher processes.

Provides priority, queues, memory, managers overlay, and full build() -> (name, proc_dict).
"""

from __future__ import annotations

import os
from typing import Annotated, Any

from ...data_schema_module import FieldMeta, SchemaBase
from ..types import ProcessPriorityLevel

DEFAULT_QUEUES: dict[str, Any] = {
    "system": {"maxsize": 100},
    "data": {"maxsize": 50},
}


def class_path_from_type(cls: type) -> str:
    """Get full dotted class path from a type (safe for refactoring)."""
    return f"{cls.__module__}.{cls.__qualname__}"


class ProcessLaunchConfig(SchemaBase):
    """Base process launch config.

    Subclass, set process_name + process_class, override memory/managers_overlay as needed.
    build() returns (name, proc_dict) for SystemLauncher.add_process().
    """

    process_name: Annotated[
        str,
        FieldMeta("Process name", info="Key in launcher / shared registry."),
    ] = "process"

    process_class: Annotated[
        str,
        FieldMeta("Process class", info="Full dotted path to ProcessModule subclass."),
    ] = ""

    priority: str | ProcessPriorityLevel = ProcessPriorityLevel.NORMAL

    protected: Annotated[
        bool,
        FieldMeta(
            "Protected",
            info="always-on процесс: replace_blueprint/hot-apply его НЕ останавливает (gui и т.п.).",
        ),
    ] = False

    queues: dict[str, Any] | None = None

    log_dir: str | None = None

    workers: Annotated[
        dict[str, Any],
        FieldMeta(
            "Workers",
            info="Конфиг воркеров {name: {class, config, thread}} для спавна при старте.",
        ),
    ] = {}

    @property
    def memory(self) -> dict[str, Any] | None:
        """SharedMemory layout for proc_dict['memory']. Override in subclass."""
        return None

    def managers_overlay(self) -> dict[str, Any] | None:
        """Fragment to deep-merge over default managers config. Override in subclass."""
        return None

    def _resolve_log_dir(self) -> str:
        if self.log_dir:
            return self.log_dir
        return os.environ.get("INSPECTOR_LOG_DIR") or "logs"

    def build(self) -> tuple[str, dict[str, Any]]:
        from .managers_config import (
            ManagersConfig,
            managers_from_log_dir,
            managers_payload_for_proc,
            merge_managers,
        )

        payload = self.model_dump()
        name = str(payload.pop("process_name"))
        class_path = str(payload.pop("process_class"))
        payload.pop("priority", None)
        payload.pop("queues", None)
        payload.pop("log_dir", None)
        # protected выносим на верхний уровень proc_dict — его читает
        # ProcessManagerProcess._get_protected_names (cfg.get("protected")), а не config.
        protected = bool(payload.pop("protected", False))
        # workers выносим на верхний уровень proc_dict (читает ProcessModule), не в config.
        workers = payload.pop("workers", None) or {}

        queues = self.queues if self.queues is not None else DEFAULT_QUEUES
        priority = self.priority.value if hasattr(self.priority, "value") else self.priority

        log_dir = self._resolve_log_dir()
        base_managers = managers_payload_for_proc(managers_from_log_dir(log_dir, model_cls=ManagersConfig))
        managers = merge_managers(base_managers, self.managers_overlay())

        proc_dict: dict[str, Any] = {
            "class": class_path,
            "queues": queues,
            "priority": priority,
            "protected": protected,
            "workers": workers,
            "config": payload,
            "managers": managers,
        }
        if self.memory is not None:
            proc_dict["memory"] = self.memory
        return name, proc_dict
