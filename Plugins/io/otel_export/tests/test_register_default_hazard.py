"""Сторожа дефолта регистра — по находке инъекционной матрицы ведущего (Task 0.5).

Задача 0.5 ввела свойство «регистр строится БЕЗ аргументов, а его дефолт не тихий»,
и матрица показала, что **ни один из 53 тестов его не сторожил**: заплаты J-3
(снять дефолт `""`) и J-4 (подставить рабочий адрес вместо пустого) не убили
ничего. Свойство было исполнено верно и не защищено — ровно тот случай, ради
которого инъекции и гоняются.

Почему это свойство вообще есть — вердикт CTO 2026-09-05, вариант (а):
`plugin_orchestrator._collect_register_schemas` (`plugin_orchestrator.py:325`)
строит managed-регистр строкой `instance = reg_item()` — **всегда без аргументов**,
а исключение глотает `except Exception`. Обязательное поле в регистре означало бы,
что регистра у `otel_export` не будет никогда: ни GUI-двери, ни `register_update`,
и одна строка `log_error` на буте вместо диагностики.

Импорт предмета — внутри тела тестов, чтобы `--collect-only` показывал их списком
даже при сломанном предмете: набор, который не собирается, неотличим от отсутствующего.
"""

from __future__ import annotations

import pytest


class TestRegisterBuildsWithoutArguments:
    """Пара свойств, которые обязаны держаться вместе: регистр строится — и молчит не тихо."""

    def test_registers_build_with_no_arguments_at_all(self):
        """`OtelExportRegisters()` без единого аргумента обязан построиться.

        Это дословная имитация `instance = reg_item()` из оркестратора. Покраснеет,
        если кто-то вернёт `endpoint` в обязательные на уровне регистра: тогда
        managed-регистр не создастся, а система об этом скажет только одной
        проглоченной строкой `log_error`.
        """
        from Plugins.io.otel_export.registers import OtelExportRegisters

        reg = OtelExportRegisters()

        assert reg.endpoint == "", (
            "дефолт регистра обязан быть пустой строкой: любое другое значение либо "
            "ломает построение без аргументов, либо становится тихим дефолтом"
        )

    def test_the_register_default_is_refused_by_the_service_schema(self):
        """Дефолт регистра обязан НЕ пройти схему сервиса — иначе он тихий.

        Механизм двери конфига: плагин в `configure()` строит
        `OtelExportConfig(**reg.model_dump())`. Пустой `endpoint` обязан там упасть
        с адресом ключа — это и есть требуемое Task 3.1 «плагин в `error`, а не
        тихий дефолт».

        Покраснеет в обе стороны: если дефолт регистра станет рабочим адресом
        (`http://127.0.0.1:4318/v1/logs`) — исключения не будет; если у схемы сервиса снимут
        валидатор пустоты — тоже. Обе поломки прошли бы мимо остальных 53 тестов.
        """
        from Services.otel_export.config import OtelExportConfig
        from Plugins.io.otel_export.registers import OtelExportRegisters

        default_register = OtelExportRegisters()

        with pytest.raises(Exception) as excinfo:
            OtelExportConfig(**default_register.model_dump())

        text = str(excinfo.value)
        assert "endpoint" in text, (
            "отказ обязан называть КЛЮЧ: без адреса поля оператор не узнает, "
            f"чего не хватает во фрагменте топологии. Получено: {text!r}"
        )

    def test_a_filled_register_does_pass_the_service_schema(self):
        """Пара к предыдущему: заполненный регистр проезжает.

        Без этого теста предыдущий согласился бы с валидатором, отвергающим ВСЁ
        подряд, — и «дверь конфига» оказалась бы заперта с обеих сторон.
        """
        from Services.otel_export.config import OtelExportConfig
        from Plugins.io.otel_export.registers import OtelExportRegisters

        filled = OtelExportRegisters(endpoint="http://collector.local:4318/v1/logs")
        cfg = OtelExportConfig(**filled.model_dump())

        assert cfg.endpoint == "http://collector.local:4318/v1/logs"
