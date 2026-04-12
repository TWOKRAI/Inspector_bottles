# multiprocess_prototype_v3/backend/configs/launch_specs.py
"""Сборка процессов для SystemLauncher (сохраняет main.py коротким)."""

from __future__ import annotations

import os
from typing import List, Tuple

from multiprocess_framework.modules.data_schema_module import process

from multiprocess_prototype_v3.backend.processes.aggregator.config import AggregatorConfig
from multiprocess_prototype_v3.backend.processes.camera_sim.config import CameraSimConfig
from multiprocess_prototype_v3.backend.processes.consumer.config import ConsumerConfig
from multiprocess_prototype_v3.backend.processes.gui.config import GuiConfig
from multiprocess_prototype_v3.backend.processes.processor.config import ProcessorConfig
from multiprocess_prototype_v3.backend.processes.producer.config import ProducerConfig


def build_default_launch_tuples() -> List[Tuple[str, dict]]:
    """
    MULTIPROCESS_V3_PROFILE:
      minimal — producer+consumer (M1).
      pipeline — camera_sim, processor, aggregator (M2); + GUI если MULTIPROCESS_V3_WITH_GUI=1.
    """
    profile = (os.environ.get("MULTIPROCESS_V3_PROFILE") or "pipeline").strip().lower()
    if profile == "minimal":
        return [
            process(ProducerConfig(managers_preset="minimal")),
            process(ConsumerConfig(managers_preset="minimal")),
        ]
    out: List[Tuple[str, dict]] = [
        process(CameraSimConfig()),
        process(ProcessorConfig()),
        process(AggregatorConfig()),
    ]
    if os.environ.get("MULTIPROCESS_V3_WITH_GUI", "").lower() in ("1", "true", "yes"):
        out.append(process(GuiConfig()))
    return out
