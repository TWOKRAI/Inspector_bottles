"""Реестр активных SHM-сегментов.

Re-export из multiprocess_framework.modules.shared_resources_module (Phase 2.4).
Дефолтный путь — data/.shm_registry.json в корне прототипа.
"""
from pathlib import Path

from multiprocess_framework.modules.shared_resources_module.buffers.registry import (
    ShmRegistry as _ShmRegistry,
)

_DEFAULT_REGISTRY_PATH = Path(__file__).resolve().parent.parent.parent / "data" / ".shm_registry.json"


class ShmRegistry(_ShmRegistry):
    """ShmRegistry с дефолтным путём к data/ прототипа."""

    def __init__(self, path: Path | str | None = None) -> None:
        super().__init__(path if path is not None else _DEFAULT_REGISTRY_PATH)


__all__ = ["ShmRegistry"]
