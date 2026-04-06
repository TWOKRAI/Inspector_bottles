# framework_minimal_prototype\backend\configs\proc_assembly.py
"""Сборка proc_dict для SystemLauncher.add_process (Dict at Boundary)."""

from __future__ import annotations

from typing import Any, Dict

from .managers_schema_lite import get_default_managers_config, merge_managers

DEFAULT_QUEUES: Dict[str, Any] = {
    "system": {"maxsize": 100},
    "data": {"maxsize": 50},
}


def _priority_str(priority: Any) -> str:
    return priority.value if hasattr(priority, "value") else priority


def build_proc_dict(cfg: Any) -> dict:
    overlay = cfg.managers_overlay()
    base_m = get_default_managers_config()
    queues = cfg.queues if cfg.queues is not None else DEFAULT_QUEUES
    proc_dict: dict = {
        "class": cfg.class_path,
        "queues": queues,
        "priority": _priority_str(cfg.priority),
        "workers": {},
        "config": cfg.model_dump(),
        "managers": merge_managers(base_m, overlay),
    }
    memory = cfg.memory if hasattr(cfg, "memory") else None
    if memory is not None:
        proc_dict["memory"] = memory
    return proc_dict


def build_launch_tuple(cfg: Any) -> tuple[str, dict]:
    return cfg.process_name, build_proc_dict(cfg)
