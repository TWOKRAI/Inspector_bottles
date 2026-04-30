"""Конвертер SourceTopology → конфиги процессов и команды для ProcessManager.

Три основные функции:
  topology_to_process_configs — из topology генерирует list[ProcessLaunchConfig]
  diff_topologies             — вычисляет diff между текущей и желаемой topology
  diff_to_commands            — из diff генерирует последовательность PM команд
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

from multiprocess_framework.modules.data_schema_module import SchemaBase, register_schema

from .schemas import CameraSourceConfig, SourceTopology


# ---------------------------------------------------------------------------
# TopologyDiff — результат сравнения двух топологий
# ---------------------------------------------------------------------------


@register_schema("TopologyDiffV3")
class TopologyDiff(SchemaBase):
    """Разница между текущей и желаемой топологией.

    Все поля — списки ключей камер (camera_0, camera_1...).
    """

    to_create: List[str] = []
    """Новые камеры → нужно создать процессы, SHM, каналы."""

    to_stop: List[str] = []
    """Удалённые камеры → остановить процессы, освободить SHM."""

    to_restart: List[str] = []
    """Камеры с изменениями, требующими перезапуска процесса
    (тип камеры, разрешение, execution_mode, region_processing)."""

    to_reconfigure: List[str] = []
    """Камеры с изменениями, не требующими перезапуска
    (fps, process_name alias — через register_update)."""

    regions_added: List[str] = []
    """Новые регионы (ключи регионов)."""

    regions_removed: List[str] = []
    """Удалённые регионы."""

    regions_changed: List[str] = []
    """Изменённые регионы (rect, enabled, ...)."""

    @property
    def has_changes(self) -> bool:
        return bool(
            self.to_create or self.to_stop or self.to_restart
            or self.to_reconfigure or self.regions_added
            or self.regions_removed or self.regions_changed
        )


# Поля CameraSourceConfig, изменение которых требует перезапуска процесса
_RESTART_FIELDS = {
    "camera_type",
    "execution_mode",
    "region_processing",
}

# Поля ShmSlotConfig, изменение которых требует перезапуска (пересоздание SHM)
_SHM_RESTART_FIELDS = {"width", "height", "channels", "ring_slots", "dtype"}


# ---------------------------------------------------------------------------
# diff_topologies — вычисляет разницу
# ---------------------------------------------------------------------------


def diff_topologies(
    current: SourceTopology | None,
    desired: SourceTopology,
) -> TopologyDiff:
    """Вычислить diff между текущей и желаемой топологией.

    Args:
        current: Текущая топология (None = пустая, первый запуск).
        desired: Желаемая топология.

    Returns:
        TopologyDiff с классификацией изменений.
    """
    if current is None:
        current = SourceTopology()

    cur_cams = set(current.cameras.keys())
    des_cams = set(desired.cameras.keys())

    to_create = sorted(des_cams - cur_cams)
    to_stop = sorted(cur_cams - des_cams)
    to_restart: list[str] = []
    to_reconfigure: list[str] = []

    # Камеры, существующие в обоих
    for cam_key in sorted(cur_cams & des_cams):
        cur_cam = current.cameras[cam_key]
        des_cam = desired.cameras[cam_key]
        needs_restart = False

        # Проверить поля, требующие перезапуска
        for f in _RESTART_FIELDS:
            if getattr(cur_cam, f, None) != getattr(des_cam, f, None):
                needs_restart = True
                break

        # Проверить SHM config
        if not needs_restart:
            cur_shm = cur_cam.shm_config
            des_shm = des_cam.shm_config
            for f in _SHM_RESTART_FIELDS:
                if getattr(cur_shm, f, None) != getattr(des_shm, f, None):
                    needs_restart = True
                    break

        if needs_restart:
            to_restart.append(cam_key)
        elif cur_cam.model_dump() != des_cam.model_dump():
            to_reconfigure.append(cam_key)

    # Регионы
    cur_regs = set(current.regions.keys())
    des_regs = set(desired.regions.keys())

    regions_added = sorted(des_regs - cur_regs)
    regions_removed = sorted(cur_regs - des_regs)
    regions_changed: list[str] = []

    for reg_key in sorted(cur_regs & des_regs):
        if current.regions[reg_key].model_dump() != desired.regions[reg_key].model_dump():
            regions_changed.append(reg_key)

    return TopologyDiff(
        to_create=to_create,
        to_stop=to_stop,
        to_restart=to_restart,
        to_reconfigure=to_reconfigure,
        regions_added=regions_added,
        regions_removed=regions_removed,
        regions_changed=regions_changed,
    )


# ---------------------------------------------------------------------------
# topology_to_process_configs — из topology генерирует конфиги процессов
# ---------------------------------------------------------------------------


def _cam_to_launch_dict(cam: CameraSourceConfig) -> Dict[str, Any]:
    """Сконвертировать CameraSourceConfig → proc_dict для ProcessManager.

    Формат совместим с CameraConfig.build() / SystemLauncher.add_process().
    """
    regs = cam.registers
    shm = cam.shm_config

    return {
        "class": "multiprocess_prototype.backend.processes.camera.process.CameraProcess",
        "config": {
            "camera_id": cam.camera_id,
            "camera_type": cam.camera_type,
            "process_name": cam.process_name,
            "fps": getattr(regs, "fps", 25),
            "resolution_width": shm.width,
            "resolution_height": shm.height,
            "ring_buffer_size": shm.ring_slots,
            "device_id": getattr(regs, "device_id", 0),
            "camera_index": getattr(regs, "camera_index", 0),
            "use_simulator": cam.camera_type == "simulator",
        },
        "memory": {
            shm.name: (shm.height, shm.width, shm.channels),
            "coll": shm.ring_slots,
        },
        "queues": {
            "system": {"maxsize": 100},
            "data": {"maxsize": 50},
        },
        "priority": "high",
    }


def _processor_for_cam(cam: CameraSourceConfig) -> Dict[str, Any]:
    """Сгенерировать proc_dict для ProcessorProcess, привязанного к камере."""
    shm = cam.shm_config

    return {
        "class": "multiprocess_prototype.backend.processes.processor.process.ProcessorProcess",
        "config": {
            "camera_id": cam.camera_id,
            "process_name": cam.region_processor_name,
            "resolution_width": shm.width,
            "resolution_height": shm.height,
        },
        "memory": {
            f"processor_{cam.camera_id}_mask": (shm.height, shm.width, 3),
            "coll": 2,
        },
        "queues": {
            "system": {"maxsize": 100},
            "data": {"maxsize": 50},
        },
        "priority": "high",
    }


def topology_to_process_configs(
    topology: SourceTopology,
) -> List[Dict[str, Any]]:
    """Из SourceTopology → список proc_dict для ProcessManager.

    Для каждой камеры генерирует:
    1. CameraProcess config
    2. ProcessorProcess config (если region_processing == dedicated_processor)

    Returns:
        [{name: str, proc_dict: dict}, ...]
    """
    configs: list[dict[str, Any]] = []

    for cam_key, cam in topology.cameras.items():
        configs.append({
            "name": cam.process_name,
            "proc_dict": _cam_to_launch_dict(cam),
        })

        if cam.region_processing == "dedicated_processor":
            configs.append({
                "name": cam.region_processor_name,
                "proc_dict": _processor_for_cam(cam),
            })

    return configs


# ---------------------------------------------------------------------------
# diff_to_commands — из diff генерирует последовательность PM команд
# ---------------------------------------------------------------------------


def diff_to_commands(
    diff: TopologyDiff,
    desired: SourceTopology,
) -> List[Dict[str, Any]]:
    """Превратить TopologyDiff в последовательность команд для ProcessManager.

    Порядок выполнения:
    1. process.stop для удалённых камер (и их процессоров)
    2. process.stop для камер, требующих перезапуска
    3. process.create для новых камер (и их процессоров)
    4. process.create для перезапускаемых камер (с новыми параметрами)
    5. register_update для камер, не требующих перезапуска

    Args:
        diff: Результат diff_topologies().
        desired: Желаемая топология (для извлечения конфигов новых камер).

    Returns:
        Список команд: [{"cmd": "process.stop", "process_name": "..."}, ...]
    """
    commands: list[dict[str, Any]] = []

    # 1. Stop удалённых
    for cam_key in diff.to_stop:
        commands.append({
            "cmd": "process.stop",
            "process_name": f"camera_{cam_key.split('_')[-1]}",
        })
        # Если был dedicated processor — остановить тоже
        commands.append({
            "cmd": "process.stop",
            "process_name": f"processor_{cam_key.split('_')[-1]}",
        })

    # 2. Stop перезапускаемых
    for cam_key in diff.to_restart:
        cam = desired.cameras.get(cam_key)
        if cam is None:
            continue
        commands.append({"cmd": "process.stop", "process_name": cam.process_name})
        if cam.region_processing == "dedicated_processor":
            commands.append({"cmd": "process.stop", "process_name": cam.region_processor_name})

    # 3. Create новых
    for cam_key in diff.to_create:
        cam = desired.cameras.get(cam_key)
        if cam is None:
            continue
        commands.append({
            "cmd": "process.create",
            "process_name": cam.process_name,
            "proc_dict": _cam_to_launch_dict(cam),
        })
        if cam.region_processing == "dedicated_processor":
            commands.append({
                "cmd": "process.create",
                "process_name": cam.region_processor_name,
                "proc_dict": _processor_for_cam(cam),
            })

    # 4. Recreate перезапускаемых (с новыми параметрами)
    for cam_key in diff.to_restart:
        cam = desired.cameras.get(cam_key)
        if cam is None:
            continue
        commands.append({
            "cmd": "process.create",
            "process_name": cam.process_name,
            "proc_dict": _cam_to_launch_dict(cam),
        })
        if cam.region_processing == "dedicated_processor":
            commands.append({
                "cmd": "process.create",
                "process_name": cam.region_processor_name,
                "proc_dict": _processor_for_cam(cam),
            })

    # 5. Reconfigure (без перезапуска) — через register_update
    for cam_key in diff.to_reconfigure:
        cam = desired.cameras.get(cam_key)
        if cam is None:
            continue
        commands.append({
            "cmd": "register_update",
            "process_name": cam.process_name,
            "camera_config": cam.model_dump(mode="python"),
        })

    return commands


__all__ = [
    "TopologyDiff",
    "diff_topologies",
    "topology_to_process_configs",
    "diff_to_commands",
]
