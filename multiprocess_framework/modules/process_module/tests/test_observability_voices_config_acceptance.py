# -*- coding: utf-8 -*-
"""Приёмочный тест (независимый tester, RED-до-реализации): окно из политики, не из литерала.

Критерий приёмки (дан планом, план и implementation мне не показаны):

    «Окно берётся из политики, а не из литерала. Значение приходит из конфига
    наблюдаемости (observability.voices.default_window_sec). Тест обязан
    краснеть, если механизм зашит константой в коде. Значение в тесте —
    литерал, не вычисленное из кода.»

Сегодня (2026-08-31, до реализации) секции ``voices`` в ``ObservabilityConfig``
НЕТ вовсе (сверено чтением всего класса и grep'ом ``voices`` по дереву — ни
одного совпадения). Рядом уже есть пять похожих под-секций той же формы
(``documents``/``events``/``flight``/``observation``/``commands``) — каждая со
своим Pydantic-классом и полем в ``ObservabilityConfig`` — поэтому ожидаю
``voices`` той же формы: ``ObservabilityVoicesConfig`` с полем
``default_window_sec``.

Значение теста — 17.25 (литерал БЕЗ смысла в проекте: не совпадает ни с одним
уже существующим окном — 5.0 (``_SEND_ERROR_LOG_INTERVAL_SEC``,
``_NEVER_DROP_LOSS_LOG_INTERVAL_SEC``, ``_system_evict_log_window`` и т.д.), ни
с 10.0 (``flush_interval`` по умолчанию)) — если бы механизм тихо игнорировал
конфиг и возвращал захардкоженное число, совпадение с 17.25 было бы
статистически невероятным, а НЕсовпадение — прямой уликой зашитого литерала.
"""

from __future__ import annotations

import pytest

from multiprocess_framework.modules.process_module.configs import ObservabilityConfig

#: Литерал, специально выбранный НЕ совпадающим ни с одним известным дефолтом
#: окна в проекте (см. докстринг модуля).
_DISTINCT_WINDOW_SEC = 17.25


class TestVoicesWindowIsAConfigField:
    def test_default_window_sec_field_exists_and_round_trips(self) -> None:
        """Секция voices.default_window_sec должна существовать и не глотаться молча.

        Pydantic v2 по умолчанию ``extra='ignore'`` — переданный, но необъявленный
        ключ НЕ бросает исключения, а просто пропадает. Поэтому проверка — прямое
        чтение атрибута, а не факт того, что конструктор не бросил (см. память
        проекта "Pydantic extra=ignore hides RED").
        """
        cfg = ObservabilityConfig.model_validate({"voices": {"default_window_sec": _DISTINCT_WINDOW_SEC}})

        assert hasattr(cfg, "voices"), (
            "у ObservabilityConfig нет секции 'voices' — механизм ещё не выставил окно как поле конфига"
        )
        assert cfg.voices.default_window_sec == pytest.approx(_DISTINCT_WINDOW_SEC), (
            "кастомное значение окна не дошло до атрибута — либо секции нет, либо "
            "значение зашито литералом в коде, а не читается из конфига"
        )

    def test_default_window_sec_has_a_sane_builtin_default(self) -> None:
        """Без явного значения секция обязана существовать со своим дефолтом (не 0, не отсутствует)."""
        cfg = ObservabilityConfig()

        assert hasattr(cfg, "voices"), (
            "voices обязана существовать даже без явной настройки (как documents/events/flight)"
        )
        assert cfg.voices.default_window_sec > 0, (
            f"дефолт окна обязан быть положительным (0 читался бы как 'механизм выключен'), "
            f"получено {getattr(cfg.voices, 'default_window_sec', None)!r}"
        )
