# -*- coding: utf-8 -*-
"""Тесты секции ``SystemConfig.telemetry`` (PC 1.3, план telemetry-publish-control.md).

Ключевой инвариант (заметка из PC 1.2): backward-compat завязан на ОТСУТСТВИЕ секции
``telemetry.publish`` — ``TelemetryGate`` в heartbeat строится только если она реально
задана. Поэтому дефолт ``SystemConfig().telemetry.publish`` ОБЯЗАН быть ``None``, а не
пустым ``TelemetryPublishConfig()`` — иначе гейт молча включился бы на всех процессах.

Ред. 2026-08-18 (исполнение флипа РТ-2, ADR-PM-040): инвариант выше про СХЕМНЫЙ дефолт
и остаётся в силе — ``SystemConfig().telemetry.publish`` по-прежнему ``None``. А вот
боевой ``system.yaml`` теперь секцию ЗАДАЁТ, со значением ``default_enabled: false``.
Это два разных факта, и путать их нельзя: «схема не включает гейт сама» (обратная
совместимость) против «владелец включил его явно и выключил в нём всё» (флип).
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
    """throttle: дефолт пустой dict — build_throttle_rules(sys_config) fallback на хардкод (PC 2.1)."""
    sc = SystemConfig()
    assert sc.telemetry.throttle == {}


def test_model_dump_publish_none_serializes_to_null() -> None:
    """model_dump() отдаёт publish: None (не {}) — так его читает launch.py."""
    dumped = SystemConfig().model_dump()
    assert dumped["telemetry"] == {"publish": None, "throttle": {}}


def test_yaml_activates_the_gate_with_default_enabled_false() -> None:
    """Реальный system.yaml прототипа ВКЛЮЧАЕТ telemetry.publish, и ровно с false.

    Контракт перевёрнут сознательно — исполнение флипа РТ-2 (2026-08-18, ADR-PM-040,
    plans/telemetry-stage6.md). До флипа тест назывался
    ``test_yaml_default_does_not_activate_gate`` и требовал ``publish is None``.

    Сторожевая роль при этом НЕ изменилась, изменилось охраняемое значение: раньше
    страховал от того, что гейт включится случайно, теперь — от того, что флип молча
    отвалится (секцию закомментируют обратно) или уползёт в ``true``. Второе опаснее
    первого: ``true`` вернёт публикацию всех уровней, ничего не сломав видимо, и
    заметить это можно будет только по трафику.

    Разделение с соседями по файлу тут существенное и оно же — причина держать тест
    именно здесь: ``test_default_publish_is_none`` про СХЕМНЫЙ дефолт (он остался
    ``None``, backward-compat не тронут), а этот — про БОЕВОЙ YAML. Совпадение по
    смыслу с ``multiprocess_prototype/backend/tests/test_rt2_config_flip_acceptance.py``
    (критерий A1) намеренное: приёмка задачи уедет в историю, а сторож конфига
    остаётся там, где его ищет читатель конфига.

    Как упадёт, если свойство исчезнет: закомментируют секцию — ``publish is None``,
    красный на первом ассерте; переставят на ``true`` — красный на втором.
    """
    sc = load_system_config()
    assert sc.telemetry.publish is not None, (
        "секция telemetry.publish в боевом system.yaml не действует — флип РТ-2 отвалился"
    )
    assert sc.telemetry.publish.default_enabled is False, (
        f"default_enabled={sc.telemetry.publish.default_enabled}, ожидался False — "
        "флип РТ-2 уполз в дефолт, публикация уровней снова идёт push'ем"
    )


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
