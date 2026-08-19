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


def test_dashboard_metrics_are_explicitly_whitelisted_in_boot_config() -> None:
    """Метрики «Дашборда телеметрии» обязаны быть РАЗРЕШЕНЫ явным правилом, не дефолтом.

    Сторожит ровно тот путь данных, который описан в критерии приёмки: гейт закрыт
    (``default_enabled=False``) → метрика не публикуется → в GUI не доезжает поток
    дельт → кольцо read-model не наполняется → график дашборда пуст. Метрики
    дашборда — единственное объявленное исключение из этого флипа, и исключение
    обязано быть явным правилом в ``metrics``, а не побочным следствием ослабленного
    гейта.

    Оракул списка метрик — ``_DASHBOARD_METRICS`` из самого виджета
    (``_system_dashboard.py``), НЕ ``system.yaml``: список, вычитанный из проверяемого
    файла, соглашается с любым его состоянием, включая пустое. Проверяемая сторона —
    реально загруженный боевой конфиг (``load_system_config()``), как это уже делает
    сосед ``test_yaml_activates_the_gate_with_default_enabled_false``.

    Ассерты по конструкции разнесены так, что ослабление гейта их не удовлетворяет
    одновременно: первый требует ``default_enabled is False`` (гейт закрыт), второй —
    ``enabled is True`` через ``resolve()`` для каждой метрики дашборда (публикация
    разрешена). Если бы гейт был открыт (``default_enabled=True``), первый ассерт
    упал бы раньше, чем второй успел бы "случайно" сойтись за счёт дефолта.

    Как упадёт, если кто-то «почистит» конфиг: удалят строку ``fps:``/``latency_ms:``
    из ``metrics`` — ``resolve()`` откатится к ``default_enabled=False`` и вернёт
    ``enabled=False`` — красный на втором ассерте, до GUI трафик не доедет молча.
    """
    # Локальный импорт — оракул целиком из виджета, не из yaml, который проверяем.
    from multiprocess_prototype.frontend.widgets.tabs.processes._system_dashboard import (
        _DASHBOARD_METRICS,
    )

    sc = load_system_config()
    publish = sc.telemetry.publish
    assert publish is not None, (
        "секция telemetry.publish в боевом system.yaml не действует — белый список метрик дашборда проверять не на чем"
    )
    assert publish.default_enabled is False, (
        f"default_enabled={publish.default_enabled}, ожидался False — гейт публикации "
        "обязан быть закрыт по умолчанию, метрики дашборда разрешены отдельным правилом"
    )

    dashboard_metric_keys = [key for key, _label in _DASHBOARD_METRICS]
    assert dashboard_metric_keys, "у виджета дашборда пуст список метрик — оракул сломан"

    for metric_key in dashboard_metric_keys:
        # Правило обязано существовать явно в metrics — не молчаливым default_enabled.
        assert metric_key in publish.metrics, (
            f"метрика '{metric_key}' рисуется на «Дашборде телеметрии», но для неё нет "
            "явного правила в telemetry.publish.metrics боевого system.yaml — при закрытом "
            "гейте она резолвится в enabled=False, график останется пустым"
        )
        enabled, _interval = publish.resolve(metric_key)
        assert enabled is True, (
            f"telemetry.publish.resolve('{metric_key}') вернул enabled={enabled} — метрика "
            "дашборда должна быть явно разрешена независимо от закрытого default_enabled"
        )


def test_metric_absent_from_dashboard_and_whitelist_stays_forbidden() -> None:
    """Метрика ВНЕ дашборда и ВНЕ белого списка обязана оставаться запрещённой.

    Контрольная пара к :func:`test_dashboard_metrics_are_explicitly_whitelisted_in_boot_config`:
    подтверждающий ноль (``enabled=False``) засчитывается только вместе с соседом,
    который на тех же данных даёт ненулевое (``enabled=True`` для метрик дашборда
    выше). Без этой пары тест мог бы молча пройти и при полностью открытом гейте,
    и при полностью закрытом — не будучи привязан к КОНКРЕТНОМУ белому списку.

    ``shm`` выбран намеренно: это существующая в каталоге метрика (счётчики
    транспорта кадров, см. docstring ``TelemetryPublishConfig``), которую дашборд
    не рисует и явного правила для неё в боевом ``system.yaml`` нет.

    Как упадёт: если кто-то по ошибке добавит ``shm`` в белый список «за компанию»
    с fps/latency_ms — красный здесь, симметрично основному тесту.
    """
    from multiprocess_prototype.frontend.widgets.tabs.processes._system_dashboard import (
        _DASHBOARD_METRICS,
    )

    sc = load_system_config()
    publish = sc.telemetry.publish
    assert publish is not None

    dashboard_metric_keys = {key for key, _label in _DASHBOARD_METRICS}
    control_metric = "shm"
    assert control_metric not in dashboard_metric_keys, (
        "контрольная метрика оказалась в списке дашборда — выбери другую, "
        "иначе проверка ничего не отличает от основного теста"
    )

    enabled, _interval = publish.resolve(control_metric)
    assert enabled is False, (
        f"telemetry.publish.resolve('{control_metric}') вернул enabled={enabled} — метрика "
        "вне дашборда и вне белого списка обязана оставаться запрещённой закрытым гейтом"
    )
