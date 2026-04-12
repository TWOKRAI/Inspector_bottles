# multiprocess_prototype_v3/registers/factory.py
"""RegistersManager + connection_map; опциональная загрузка/сохранение JSON."""

from __future__ import annotations

import json
from typing import Any, Callable, Dict, Optional, Tuple

from multiprocess_framework.modules.registers_module import (
    RegistersManager,
    build_connection_map_from_registers,
)

from multiprocess_prototype_v3.persistence.paths import config_json_path

from .aggregator import AggregatorRegisters
from .camera_sim import CameraSimRegisters
from .names import AGGREGATOR_REGISTER, CAMERA_SIM_REGISTER, PROCESSOR_REGISTER, PRODUCER_REGISTER
from .processor_registers import ProcessorRegisters
from .producer import ProducerRegisters


def load_register_snapshot(
    registers: Dict[str, Any],
    path: Optional[Any] = None,
) -> None:
    """Подмешать сохранённый JSON в экземпляры регистров (in-place)."""
    p = path or config_json_path()
    if not p.exists():
        return
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    for name, inst in registers.items():
        if name not in data or not hasattr(inst, "model_dump"):
            continue
        patch = data[name]
        if not isinstance(patch, dict):
            continue
        try:
            merged = {**inst.model_dump(), **patch}
            new_inst = type(inst).model_validate(merged)
            registers[name] = new_inst
        except Exception:
            continue


def save_register_snapshot(
    registers_manager: RegistersManager,
    path: Optional[Any] = None,
) -> None:
    p = path or config_json_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps(registers_manager.model_dump_all(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def create_registers(
    *,
    send_callback: Optional[Callable[[str, str, str, Any, Dict[str, Any]], None]] = None,
    load_persisted: bool = True,
    connection_map: Optional[Dict[str, str]] = None,
) -> Tuple[RegistersManager, Dict[str, str]]:
    """
    Экземпляры регистров пайплайна + producer; connection_map из register_dispatch / FieldRouting.
    """
    reg_instances: Dict[str, Any] = {
        PRODUCER_REGISTER: ProducerRegisters(),
        CAMERA_SIM_REGISTER: CameraSimRegisters(),
        PROCESSOR_REGISTER: ProcessorRegisters(),
        AGGREGATOR_REGISTER: AggregatorRegisters(),
    }
    if load_persisted:
        load_register_snapshot(reg_instances)
    cm = build_connection_map_from_registers(reg_instances)
    if connection_map:
        cm = {**cm, **connection_map}
    rm = RegistersManager(
        registers=reg_instances,
        connection_map=cm,
        send_callback=send_callback,
    )
    return rm, cm
