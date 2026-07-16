# -*- coding: utf-8 -*-
"""Тесты секции ``SystemConfig.telemetry`` (PC 1.3, план telemetry-publish-control.md).

Ключевой инвариант (заметка из PC 1.2): backward-compat завязан на ОТСУТСТВИЕ секции
``telemetry.publish`` — ``TelemetryGate`` в heartbeat строится только если она реально
задана. Поэтому дефолт ``SystemConfig().telemetry.publish`` ОБЯЗАН быть ``None``, а не
пустым ``TelemetryPublishConfig()`` — иначе гейт молча включился бы на всех процессах.
"""

from __future__ import annotations

from multiprocess_framework.modules.process_module.configs import (
    MetricRule,
    TelemetryPublishConfig,
)

from multiprocess_prototype.backend.config.schemas import (
    SystemConfig,
    TelemetrySection,
    load_system_config,
)


def test_schema_has_telemetry_section() -> None:
    """SystemConfig несёт секцию telemetry по умолчанию."""
    sc = SystemConfig()
    assert isinstance(sc.telemetry, TelemetrySection)


def test_default_publish_is_none() -> None:
    """Дефолт publish=None — секция «отсутствует», гейт неактивен (backward-compat)."""
    sc = SystemConfig()
    assert sc.telemetry.publish is None


def test_default_throttle_is_empty_dict() -> None:
    """throttle — задел Фазы 2, дефолт пустой dict (build_throttle_rules его не читает)."""
    sc = SystemConfig()
    assert sc.telemetry.throttle == {}


def test_model_dump_publish_none_serializes_to_null() -> None:
    """model_dump() отдаёт publish: None (не {}) — так его читает launch.py."""
    dumped = SystemConfig().model_dump()
    assert dumped["telemetry"] == {"publish": None, "throttle": {}}


def test_yaml_default_does_not_activate_gate() -> None:
    """Реальный system.yaml прототипа НЕ включает telemetry.publish по умолчанию."""
    sc = load_system_config()
    assert sc.telemetry.publish is None


def test_explicit_publish_validates_as_telemetry_publish_config() -> None:
    """Явно заданный publish валидируется как TelemetryPublishConfig (framework-контракт)."""
    sc = SystemConfig.model_validate(
        {
            "telemetry": {
                "publish": {
                    "default_interval_sec": 2.0,
                    "metrics": {"fps": {"enabled": True, "interval_sec": 1.0}},
                }
            }
        }
    )
    assert isinstance(sc.telemetry.publish, TelemetryPublishConfig)
    assert sc.telemetry.publish.default_interval_sec == 2.0
    assert isinstance(sc.telemetry.publish.metrics["fps"], MetricRule)
    assert sc.telemetry.publish.metrics["fps"].enabled is True


def test_explicit_empty_publish_is_not_none() -> None:
    """publish: {} — секция ЗАДАНА явно (даже пустая), отличается от отсутствия ключа."""
    sc = SystemConfig.model_validate({"telemetry": {"publish": {}}})
    assert sc.telemetry.publish is not None
    assert isinstance(sc.telemetry.publish, TelemetryPublishConfig)
