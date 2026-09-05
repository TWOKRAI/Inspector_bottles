"""Приёмочные тесты регистров Plugins/io/otel_export/registers.py — секция C, Task 0.4.

НЕЗАВИСИМЫЙ тестер, ДО реализации. На момент написания каталога
``Plugins/io/otel_export`` не существует (проверено — только что созданный
``tests/`` пуст, ни один соседний файл предмета не читался).

Два имени в этом файле — ДОГАДКА по конвенции соседних плагинов, не факт из
кода: класс регистров назван ``OtelExportRegisters`` (по образцу
``Plugins/io/telemetry_sink/registers.py:TelemetrySinkRegisters`` — паттерн
"<PluginName>Registers"), метод чтения эффективных значений назван
``readback()`` (по образцу голого ``def readback(self)`` в
``multiprocess_framework/modules/logger_module/core/sampling.py:335`` — это и
есть общекодовая идиома этого проекта для "эффективные значения наружу").
Ни interfaces.py, ни registers.py не существуют, поэтому свериться с
формальным контрактом было не с чем — если исполнитель назовёт иначе, это
несовпадение имени, а не свойства, и должно быть исправлено ЗДЕСЬ, а не
тихо подстроено.

Импорт предмета — внутри тела тестов, не на уровне модуля.
"""

from __future__ import annotations

import pytest


class TestRegisterFieldParity:
    """C1, C2: набор полей регистров совпадает с набором полей OtelExportConfig."""

    def test_c1_and_c2_register_fields_equal_config_fields_as_sets(self) -> None:
        """C1+C2: {поля регистров} == {поля конфига} — сравниваются ДВА множества,
        полученные из самого предмета (model_fields), а не переписанные руками
        в тесте. Если завтра в конфиг добавят поле, а в регистры забудут (или
        наоборот) — это множество разойдётся, и тест покраснеет САМ, без
        правки теста.

        Как краснеет сейчас: ModuleNotFoundError (ни конфига, ни регистров нет).
        """
        from Plugins.io.otel_export.registers import OtelExportRegisters
        from Services.otel_export.config import OtelExportConfig

        config_fields = set(OtelExportConfig.model_fields.keys())
        register_fields = set(OtelExportRegisters.model_fields.keys())

        assert config_fields, "OtelExportConfig.model_fields пуст — подозрительно само по себе"
        only_in_config = config_fields - register_fields
        only_in_registers = register_fields - config_fields
        assert not only_in_config, f"Поля есть в конфиге, но нет в регистрах: {only_in_config}"
        assert not only_in_registers, f"Поля есть в регистрах, но нет в конфиге: {only_in_registers}"


class TestReadbackMasking:
    """C3, C4: readback() маскирует секреты headers и отдаёт эффективные значения."""

    def test_c3_readback_masks_header_secret_completely(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """C3: секрет из headers не виден в readback() ни целиком, ни частично.

        Реальный секрет кладётся в переменную окружения; конфигурируется
        только подстановка `${...}`. readback() обязан отдать '***', а не
        реальное значение и не его часть (проверено substring-поиском по
        сериализованному представлению целиком).
        """
        monkeypatch.setenv("OTEL_TEST_SECRET_TOKEN", "SuperSecretXYZ789")

        from Plugins.io.otel_export.registers import OtelExportRegisters

        reg = OtelExportRegisters(
            endpoint="http://collector.local:4318",
            headers={"authorization": "${OTEL_TEST_SECRET_TOKEN}"},
        )
        result = reg.readback()
        serialized = str(result)

        assert "SuperSecretXYZ789" not in serialized, "секрет утёк в readback целиком"
        assert "Super" not in serialized, "секрет утёк в readback частично"
        assert result["headers"]["authorization"] == "***"

    def test_c4_readback_differs_from_the_raw_configured_dump(self) -> None:
        """C4: readback() — не то же самое, что сырой model_dump() (сконфигурированное).

        `model_dump()` — гарантированный API pydantic, отдаёт то, что ЛЕЖИТ в
        полях (сконфигурированное: буквальная строка '${...}'). readback()
        обязан отдать ЭФФЕКТИВНОЕ представление (замаскированное '***' для
        headers) — то есть два вызова обязаны разойтись именно в этом поле.
        Если readback() окажется псевдонимом model_dump() (просто выводом того
        же самого), это НЕ эффективные значения, а эхо конфигурации — тест
        должен покраснеть на равенстве.
        """
        from Plugins.io.otel_export.registers import OtelExportRegisters

        reg = OtelExportRegisters(
            endpoint="http://collector.local:4318",
            headers={"authorization": "${OTEL_TEST_SECRET_TOKEN}"},
        )
        raw = reg.model_dump()
        effective = reg.readback()

        assert raw["headers"]["authorization"] == "${OTEL_TEST_SECRET_TOKEN}", (
            "сырой model_dump() должен нести буквальную подстановку, иначе сравнивать readback не с чем"
        )
        assert effective["headers"]["authorization"] == "***"
        assert raw != effective, "readback() ничем не отличается от сырого model_dump()"
