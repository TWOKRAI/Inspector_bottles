"""Построение SharedResourcesManager из connection bundle + нормализация memory."""

import warnings
from typing import Any, Dict, Optional, Tuple

from multiprocess_framework.modules.shared_resources_module import SharedResourcesManager
from multiprocess_framework.modules.process_module.configs.managers_normalize import (
    normalize_managers_view,
)

from ..core.bundle_contract import validate_bundle


def _normalize_memory_spec(spec: Any) -> Optional[tuple]:
    """
    Нормализует спецификацию памяти к (num_images, image_shape, dtype).
    Короткий формат: (h, w, c) → (1, (h,w,c), "uint8")
    """
    if not isinstance(spec, tuple):
        return None
    if len(spec) == 3:
        if isinstance(spec[1], tuple):
            return spec
        if all(isinstance(x, (int, float)) for x in spec):
            return (1, spec, "uint8")
    return spec


def _normalize_memory_config(mem_cfg: Dict[str, Any]) -> Tuple[Dict[str, tuple], int]:
    """Нормализует config["memory"] к (names, coll)."""
    coll = mem_cfg.get("coll", 2)
    names_raw = mem_cfg.get("names")
    if names_raw is None:
        names_raw = {k: v for k, v in mem_cfg.items() if k != "coll" and isinstance(v, tuple)}
    normalized: Dict[str, tuple] = {}
    for name, spec in (names_raw or {}).items():
        ns = _normalize_memory_spec(spec)
        if ns:
            normalized[name] = ns
    return normalized, coll


def _build_shared_resources_from_bundle(
    process_name: str,
    bundle: Dict[str, Any],
) -> SharedResourcesManager:
    """
    Построить SharedResourcesManager из bundle внутри дочернего процесса.
    """
    if not validate_bundle(bundle):
        raise ValueError("Invalid bundle: missing required keys (queues, config)")

    shared_resources = SharedResourcesManager()
    queues = bundle.get("queues", {})
    process_config = bundle.get("config", {})
    custom = dict(bundle.get("custom", {}))
    custom.setdefault("process_config", process_config)

    # Ф3.1 (routing-epoch): epoch + incarnation'ы соседей на момент спавна.
    routing_meta = bundle.get("routing_meta", {}) or {}
    _epoch = int(routing_meta.get("epoch", 0) or 0)
    _incarnations = routing_meta.get("incarnations", {}) or {}

    shared_resources.process_state_registry.register_process(
        process_name,
        initial_state={
            "custom": custom,
            # last_seen epoch собственной записи + своя incarnation (ребёнок
            # рождён «видевшим» текущий epoch → refresh, породивший его, игнор).
            "metadata": {
                "routing_epoch": _epoch,
                "routing_incarnation": int(_incarnations.get(process_name, 0) or 0),
            },
        },
    )
    _pc = process_config if isinstance(process_config, dict) else {}
    shared_resources.config_store.store(
        process_name,
        {
            "process": _pc,
            "managers": normalize_managers_view(_pc) if isinstance(_pc, dict) else {},
        },
    )

    all_process_memory = custom.pop("_all_process_memory", {})

    has_mem_names = bool(custom.get("memory_names"))
    has_mem_cfg = bool(process_config.get("memory"))
    if not has_mem_names and has_mem_cfg:
        mem_cfg = process_config["memory"]
        if isinstance(mem_cfg, dict):
            names, coll = _normalize_memory_config(mem_cfg)
            if names:
                ok = shared_resources.memory_manager.create_memory_dict(process_name, names, coll)
                pd = shared_resources.get_process_data(process_name)
                mm = shared_resources.memory_manager
                if ok and pd and mm and hasattr(mm, "_local_handles"):
                    for shm_base_name, shm_list in mm._local_handles.get(process_name, {}).items():
                        if shm_list and shm_base_name in names:
                            pd.custom.setdefault("memory_names", {})[shm_base_name] = [s.name for s in shm_list]
                            pd.custom.setdefault("memory_params", {})[shm_base_name] = names[shm_base_name]
                            # Ф7 G.H: memory_index_usage снят (мёртвый учёт; free-list у FramePool).
                            pd.custom.setdefault("memory_coll", {})[shm_base_name] = coll
                    custom.update(pd.custom)
    for qtype, q in queues.items():
        shared_resources.process_state_registry.add_queue(process_name, qtype, q)

    routing_map = bundle.get("routing_map", {})
    for target_name, target_queues in routing_map.items():
        if target_name == process_name:
            continue
        # Ф3.1: incarnation соседа посевом в metadata — база для сверки refresh'ем.
        shared_resources.process_state_registry.register_process(
            target_name,
            initial_state={
                "metadata": {
                    "routing_epoch": _epoch,
                    "routing_incarnation": int(_incarnations.get(target_name, 0) or 0),
                }
            },
        )
        shared_resources.config_store.store(target_name, {"process": {}, "managers": {}})
        for qtype, q in (target_queues or {}).items():
            shared_resources.process_state_registry.add_queue(target_name, qtype, q)

    for other_name, mem_data in all_process_memory.items():
        if other_name == process_name:
            continue
        pd = shared_resources.get_process_data(other_name)
        if pd:
            for k, v in mem_data.items():
                pd.custom[k] = v

    try:
        shared_resources.initialize()
        shared_resources.reinitialize_in_child()
    except Exception as e:
        warnings.warn(f"SRM.initialize() failed: {e}", UserWarning)

    return shared_resources
