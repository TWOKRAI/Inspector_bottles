# multiprocess_prototype/frontend/launcher/register_binder.py
"""Привязка регистров к StateStore: RegistersStateAdapter + CameraStateAdapter."""
from typing import Any

from multiprocess_prototype.state_store.adapters.camera_state_adapter import CameraStateAdapter
from multiprocess_prototype.state_store.adapters.registers_adapter import RegistersStateAdapter


def setup_state_adapters(
    process: Any,
    regs: Any,
    state_proxy: Any,
    config: dict[str, Any],
) -> CameraStateAdapter:
    """Подключить RegistersStateAdapter и CameraStateAdapter.

    Сохраняет адаптеры в process для lifecycle-управления.
    Возвращает camera_registry для передачи в build_domain_context.
    """
    if state_proxy is not None and regs is not None:
        path_mapping = build_path_mapping(regs, config)
        registers_adapter = RegistersStateAdapter(
            registers_manager=regs,
            state_proxy=state_proxy,
            path_mapping=path_mapping,
        )
        registers_adapter.connect()
        process._registers_adapter = registers_adapter

    camera_configs = config.get("camera_configs") or []
    num_cameras = len(camera_configs) if camera_configs else 1
    camera_registry = CameraStateAdapter(
        state_proxy=state_proxy,
        num_cameras=num_cameras,
    )
    if state_proxy is not None:
        camera_registry.connect()
        process._camera_state_adapter = camera_registry

    return camera_registry


def build_path_mapping(
    regs: Any,
    config: dict[str, Any],
) -> dict[tuple[str, str], str]:
    """Построить маппинг (register_name, field_name) -> state_path по конвенции именования."""
    mapping: dict[tuple[str, str], str] = {}
    camera_id = config.get("camera_id", 0)

    PREFIX_MAP = {
        "camera": f"cameras.{camera_id}.config",
        "processor": f"processor.{camera_id}.config",
        "renderer": "renderer.config",
        "robot": "robot.config",
        "database": "database.config",
    }

    for reg_name in regs.register_names():
        prefix = PREFIX_MAP.get(reg_name)
        if prefix is None:
            continue
        reg = regs.get_register(reg_name)
        if reg is None:
            continue
        if hasattr(reg, "model_fields"):
            fields = reg.model_fields.keys()
        elif hasattr(reg, "__fields__"):
            fields = reg.__fields__.keys()
        else:
            continue
        for field in fields:
            mapping[(reg_name, field)] = f"{prefix}.{field}"

    return mapping
