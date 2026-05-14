"""
Цепочка обработки — последовательность (процессор, параметры).

Каждая область имеет свою цепочку. Цепочку можно копировать между областями.
"""

from typing import List, Dict, Type
import numpy as np

from .base import BaseProcessor
from .registry import REGISTRY


def run_chain(image: np.ndarray, chain: List[Dict], registry: Dict[str, Type[BaseProcessor]] = None) -> np.ndarray:
    """
    Выполнить цепочку над изображением.
    chain: [{"processor_id": "grayscale", "params": {...}}, ...]
    """
    registry = registry or REGISTRY
    result = image.copy()
    for step in chain:
        proc_id = step.get("processor_id")
        params = step.get("params", {})
        if proc_id not in registry:
            continue
        proc_class = registry[proc_id]
        proc = proc_class()
        result = proc.process(result, params)
    return result


def copy_chain(source_chain: List[Dict]) -> List[Dict]:
    """Глубокая копия цепочки (для копирования между областями)."""
    import copy

    return copy.deepcopy(source_chain)
