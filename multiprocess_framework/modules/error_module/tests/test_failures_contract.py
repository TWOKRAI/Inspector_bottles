# -*- coding: utf-8 -*-
"""Контракт классов отказа (`failures.py`, Task 1.3b).

Классы существуют ради ОДНОГО наблюдаемого свойства: ключ окна голоса — пара
``(имя класса, context)``, и разные роды отказа обязаны получать разные ключи.
Поэтому здесь сторожится не «класс объявлен», а то, ради чего он объявлен.
"""

from __future__ import annotations

from multiprocess_framework.modules.error_module import failures
from multiprocess_framework.modules.error_module.interfaces import (
    DeviceOpenFailed,
    FrameworkFailure,
    ObservabilityMisuse,
    ResourceUnavailable,
    SubsystemStartFailed,
)

_CLASSES = (ResourceUnavailable, SubsystemStartFailed, DeviceOpenFailed, ObservabilityMisuse)


class TestTaxonomy:
    def test_every_class_has_its_own_name_and_a_common_base(self) -> None:
        """Разные имена — разные ключи окна; общая база — один улов в широком except."""
        names = [cls.__name__ for cls in _CLASSES]
        assert len(set(names)) == len(names), f"имена классов совпали — ключи окна выродятся: {names}"
        for cls in _CLASSES:
            assert issubclass(cls, FrameworkFailure), f"{cls.__name__} мимо общей базы"
            assert issubclass(cls, Exception), f"{cls.__name__} не исключение — report_error его не примет"

    def test_the_public_road_is_interfaces_not_core(self) -> None:
        """Правило проекта: внешние модули импортируют из ``interfaces.py``."""
        from multiprocess_framework.modules.error_module import interfaces

        for cls in _CLASSES:
            assert cls.__name__ in interfaces.__all__, (
                f"{cls.__name__} не в публичном контракте — сайты потянут его из failures напрямую"
            )

    def test_the_set_stays_small_or_the_boundary_is_restated(self) -> None:
        """Ограда против дрейфа «набор для фабрикации» → «таксономия всего».

        Предсказание, записанное при заведении модуля: увидев фреймворковые
        классы, автор нового плагина начнёт сливать в них СВОЙ домен, у которого
        уже были различимые имена (``DeviceHubError``, ``ModbusDriverError``,
        ``SdkError``). Тогда таксономия станет вторым словарём поверх
        работающего первого.

        Тест не запрещает рост — он требует, чтобы рост был ОСОЗНАННЫМ: добавил
        класс, значит перечитал границу в докстринге модуля и поправил здесь
        число. Красный тест — это вопрос «а точно ли у этого отказа нет своего
        дома?», заданный в тот момент, когда на него ещё дёшево ответить.
        """
        assert len(failures.__all__) == 5, (
            f"состав failures.__all__ изменился: {failures.__all__}. Перечитай границу применения "
            f"в докстринге модуля (классы — ТОЛЬКО для сайтов, где объекта исключения нет) "
            f"и обнови число здесь, если рост осознан."
        )

    def test_domain_hierarchies_of_services_stay_independent(self) -> None:
        """Доменные иерархии сервисов НЕ наследуют базу фреймворка.

        Это и есть проверяемая форма границы: пока `DeviceHubError` и
        `ModbusDriverError` живут сами по себе, миграции «всех на общую базу»
        не случилось. Сервис, которого нет в сборке, пропускается — контроль
        ниже гарантирует, что тест не выродился в проверку нуля импортов.
        """
        checked = 0
        for module_name, attr in (
            ("Services.device_hub.errors", "DeviceHubError"),
            ("Services.modbus.sdk.errors", "ModbusDriverError"),
        ):
            try:
                module = __import__(module_name, fromlist=[attr])
            except Exception:  # noqa: BLE001 — сервис может отсутствовать в сборке
                continue
            cls = getattr(module, attr, None)
            if cls is None:
                continue
            checked += 1
            assert not issubclass(cls, FrameworkFailure), (
                f"{attr} унаследовал FrameworkFailure — доменная иерархия слилась с фреймворковой, "
                f"это тот самый второй словарь"
            )
        assert checked > 0, (
            "ни одна доменная иерархия не проверена — тест выродился в подтверждающий ноль "
            "(см. правило «неподключённый драйвер читается как ровный ноль»)"
        )
