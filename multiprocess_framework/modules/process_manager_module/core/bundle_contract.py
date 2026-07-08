"""
Bundle Contract — pickle-safe dict, передаваемый в дочерний процесс через Process(args=...).

Создаётся в ProcessRegistry._create_process (через build_bundle).
Распаковывается в runner/bundle_builder._build_shared_resources_from_bundle.
"""

from typing import Any, Dict, Optional

# Документация ключей (runtime-валидация — validate_bundle)
BUNDLE_KEYS = ("queues", "config", "custom", "routing_map", "routing_meta")


def validate_bundle(bundle: Dict[str, Any]) -> bool:
    """Проверить, что bundle содержит обязательные ключи."""
    return isinstance(bundle, dict) and "queues" in bundle and "config" in bundle


def build_bundle(
    queues: Dict[str, Any],
    config: Dict[str, Any],
    custom: Optional[Dict[str, Any]] = None,
    routing_map: Optional[Dict[str, Any]] = None,
    routing_meta: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Единая точка сборки bundle для spawn.

    ``routing_meta`` (Ф3.1, routing-epoch) — аддитивный ключ ``{"epoch": N,
    "incarnations": {имя: incarnation}}``. Новый ребёнок рождается с актуальными
    epoch/incarnation'ами соседей, поэтому корректно сверяет их с последующими
    ``routing.refresh``. Отсутствие ключа = дефолт ``{}`` (epoch 0, incarnations
    пусты) — обратная совместимость.
    """
    return {
        "queues": queues,
        "config": config,
        "custom": custom or {},
        "routing_map": routing_map or {},
        "routing_meta": routing_meta or {},
    }
