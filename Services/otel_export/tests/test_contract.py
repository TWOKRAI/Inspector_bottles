# -*- coding: utf-8 -*-
"""Авторские тесты опасных мест контракта — Task 0.4 плана otel-export.md.

Это НЕ дубль приёмочного набора независимого тестера
(`test_contract_acceptance.py`, `test_lazy_sdk_acceptance.py`,
`Plugins/io/otel_export/tests/test_registers_acceptance.py`). Тестер писал по
критериям приёмки, не видя реализации; здесь — то, что видно только автору:
границы валидатора, утечка секрета через текст ошибки, разрыв между нашим
`ObservabilityPort` и настоящим `PluginContext`.

Читается как документация контракта: каждый тест отвечает на вопрос «что
сломается, если сделать наоборот».
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from pydantic import ValidationError

REPO_ROOT = Path(__file__).resolve().parents[3]
SUBJECT_DIRS = (
    REPO_ROOT / "Services" / "otel_export",
    REPO_ROOT / "Plugins" / "io" / "otel_export",
)

ENDPOINT = "http://127.0.0.1:4318/v1/logs"


# ---------------------------------------------------------------------------
# Валидация границы конфига
# ---------------------------------------------------------------------------


class TestHeadersEnvOnly:
    """Дверь для секретов: значение заголовка — только подстановка окружения."""

    @pytest.mark.parametrize(
        "bad_value",
        [
            "Bearer secret123",  # чистый литерал
            "$OTEL_TOKEN",  # без фигурных скобок — форма shell, не наша
            "prefix ${OTEL_TOKEN}",  # подстановка НЕ целиком: хвост поедет литералом
            "${OTEL_TOKEN} suffix",
            "${}",  # пустое имя переменной
            "${9TOKEN}",  # имя не может начинаться с цифры
            "",  # пустая строка — не «нет заголовка», а заголовок без значения
        ],
    )
    def test_only_full_env_placeholder_is_accepted(self, bad_value: str) -> None:
        """Всё, кроме `${ИМЯ}` целиком, отвергается.

        Наоборот (принять `prefix ${TOKEN}`) означало бы, что часть значения
        живёт литералом в YAML — то есть в git-истории рецепта.
        """
        from Services.otel_export.config import OtelExportConfig

        with pytest.raises(ValidationError):
            OtelExportConfig(endpoint=ENDPOINT, headers={"authorization": bad_value})

    @pytest.mark.parametrize("good_value", ["${OTEL_TOKEN}", "${_x}", "${A1_B2}"])
    def test_env_placeholder_shapes_that_must_pass(self, good_value: str) -> None:
        """Парная проверка: законные формы не отвергаются.

        Без неё валидатор, отвергающий ВСЁ, был бы неотличим от правильного.
        """
        from Services.otel_export.config import OtelExportConfig

        cfg = OtelExportConfig(endpoint=ENDPOINT, headers={"authorization": good_value})
        assert cfg.headers["authorization"] == good_value

    def test_safe_formatter_names_the_key_but_never_the_value(self) -> None:
        """`format_validation_error` называет ключ и не печатает значение.

        Сообщение об отвергнутом конфиге уезжает в журнал процесса. Напечатай
        оно значение — и валидатор, поставленный ради «секреты в env», сам стал
        бы утечкой: отвергнутый (то есть чаще всего настоящий) токен лёг бы в
        system.log.
        """
        from Services.otel_export.config import OtelExportConfig, format_validation_error

        secret = "Bearer VerySecretValue999"
        with pytest.raises(ValidationError) as exc_info:
            OtelExportConfig(endpoint=ENDPOINT, headers={"authorization": secret})

        text = format_validation_error(exc_info.value)
        assert "authorization" in text, "ключ заголовка обязан быть назван — иначе не найти"
        assert "headers" in text, "адрес поля обязан быть назван"
        assert "VerySecretValue999" not in text, "значение утекло в текст ошибки целиком"
        assert "VerySecret" not in text, "значение утекло в текст ошибки частично"

    def test_secret_is_absent_from_str_of_the_error_on_all_three_roads(self) -> None:
        """Предохранитель `hide_input_in_errors` закрывает утечку секрета на ТРЁХ дорогах.

        До этого теста здесь стоял пин факта «`str(ValidationError)` у pydantic
        2.13 печатает вход целиком» — он сторожил ОПАСНОСТЬ, а не защиту
        (см. git-историю файла). Вердикт CTO по Task 0.5: предохранитель —
        не `format_validation_error` (он не дотягивается до `from_plugins`,
        строящего схему как `reg_cls(**reg_fields)` БЕЗ `try`), а
        `model_config = ConfigDict(hide_input_in_errors=True)` на самой схеме
        (ADR-OTEL-005). Этот тест сторожит именно его — на всех трёх дорогах,
        которыми схема вообще строится или меняется.

        Имя ключа `headers` в тексте ОБЯЗАНО остаться: если защита скроет и
        его, диагностировать отказ станет нечем — это была бы немота, а не
        безопасность.

        Как краснеет (доказано прогоном при написании — см. отчёт Task 0.5):
        убрать `hide_input_in_errors=True` из `OtelExportConfig.model_config` —
        секрет возвращается в текст всех трёх исключений ниже.
        """
        from Services.otel_export.config import OtelExportConfig

        secret = "Bearer VerySecretValue999"
        bad_headers = {"authorization": secret}

        with pytest.raises(ValidationError) as exc_ctor:
            OtelExportConfig(endpoint=ENDPOINT, headers=bad_headers)

        with pytest.raises(ValidationError) as exc_validate:
            OtelExportConfig.model_validate({"endpoint": ENDPOINT, "headers": bad_headers})

        # Присваивание: validate_assignment=True унаследован от SchemaBase —
        # дорога поддержана, третий вариант не нужен.
        cfg = OtelExportConfig(endpoint=ENDPOINT)
        with pytest.raises(ValidationError) as exc_assign:
            cfg.headers = bad_headers

        for road, exc_info in (
            ("конструктор", exc_ctor),
            ("model_validate", exc_validate),
            ("присваивание", exc_assign),
        ):
            text = str(exc_info.value)
            assert secret not in text, f"{road}: секрет утёк в str(exc) целиком"
            assert "VerySecret" not in text, f"{road}: секрет утёк в str(exc) частично"
            assert "headers" in text, f"{road}: адрес поля пропал из текста — диагностировать отказ стало нечем"


class TestConfigBoundary:
    """Прочие отказы границы: пустой endpoint, чужой уровень, батч больше очереди."""

    @pytest.mark.parametrize("blank", ["", "   ", "\t"])
    def test_blank_endpoint_is_refused(self, blank: str) -> None:
        """Ключ, присутствующий в YAML пустым, — не «дефолт», а незаполненный ключ."""
        from Services.otel_export.config import OtelExportConfig

        with pytest.raises(ValidationError):
            OtelExportConfig(endpoint=blank)

    def test_level_alias_is_normalized_and_unknown_is_refused(self) -> None:
        """Шкала уровней — фреймворка, а не своя: WARN раскрывается, TRACE отвергается.

        Свой список имён здесь был бы вторым владельцем шкалы
        (`channel_routing_module/levels.py`), а мягкий дефолт на незнакомом
        имени превратил бы опечатку в тихую подписку не на тот уровень.
        """
        from Services.otel_export.config import OtelExportConfig

        assert OtelExportConfig(endpoint=ENDPOINT, level="warn").level == "WARNING"
        assert OtelExportConfig(endpoint=ENDPOINT, level="fatal").level == "CRITICAL"
        with pytest.raises(ValidationError):
            OtelExportConfig(endpoint=ENDPOINT, level="TRACE")

    def test_batch_larger_than_queue_is_refused_here_not_inside_the_sdk(self) -> None:
        """Правило SDK (`_validate_arguments`), пойманное на нашей границе.

        Иначе ValueError всплыл бы из чужого конструктора внутри `configure()`,
        уже без адреса нашего ключа.
        """
        from Services.otel_export.config import OtelExportConfig

        with pytest.raises(ValidationError):
            OtelExportConfig(endpoint=ENDPOINT, max_queue_size=100, max_export_batch_size=101)
        # Парная: равенство законно — граница включающая.
        assert (
            OtelExportConfig(endpoint=ENDPOINT, max_queue_size=100, max_export_batch_size=100).max_export_batch_size
            == 100
        )


# ---------------------------------------------------------------------------
# readback — эффективные значения
# ---------------------------------------------------------------------------


class TestReadback:
    """Что именно делает readback эффективным, а не эхом конфигурации."""

    def test_every_header_is_masked_not_only_the_first(self) -> None:
        """Маскируются ВСЕ заголовки.

        Приёмочный тест C3 кладёт один заголовок — реализация «замаскировать
        первый» прошла бы его. Развилка «этот заголовок безопасный» и есть
        место, где утекают токены, поэтому её нет вовсе.
        """
        from Services.otel_export.config import OtelExportConfig

        cfg = OtelExportConfig(
            endpoint=ENDPOINT,
            headers={
                "authorization": "${OTEL_TOKEN}",
                "x-api-key": "${OTEL_API_KEY}",
                "x-tenant": "${OTEL_TENANT}",
            },
        )
        masked = cfg.readback()["headers"]
        assert masked == {"authorization": "***", "x-api-key": "***", "x-tenant": "***"}

    def test_export_timeout_sec_is_derived_not_hardcoded(self) -> None:
        """`export_timeout_sec` считается от поля, а не написан числом 30.0.

        Он существует ровно потому, что `export_timeout_ms` у батчера SDK не
        действует (`# Not used. No way currently to pass timeout to export.`);
        константа вместо производной вернула бы ту же ложь, только красивее.
        """
        from Services.otel_export.config import OtelExportConfig

        assert OtelExportConfig(endpoint=ENDPOINT).readback()["export_timeout_sec"] == 30.0
        assert OtelExportConfig(endpoint=ENDPOINT, export_timeout_ms=4500).readback()["export_timeout_sec"] == 4.5

    def test_readback_without_headers_is_still_not_an_echo(self) -> None:
        """Без заголовков readback всё равно отличается от `model_dump()`.

        Если бы отличие давала ТОЛЬКО маскировка, то на конфиге без секретов
        readback вырождался бы в эхо — и никакой тест этого не заметил бы.
        """
        from Services.otel_export.config import OtelExportConfig

        cfg = OtelExportConfig(endpoint=ENDPOINT)
        assert cfg.readback() != cfg.model_dump()
        assert "export_timeout_sec" in cfg.readback()


class TestRegistersInheritTheContract:
    """Регистры — производная: валидация и readback обязаны работать и на них."""

    def test_registers_refuse_literal_header_too(self) -> None:
        """Правило секретов действует и на двери плагина.

        Наоборот — «регистры валидируют иначе, чем конфиг» — и есть та вторая
        таблица полей, ради отсутствия которой регистры сделаны подклассом.
        """
        from Plugins.io.otel_export.registers import OtelExportRegisters

        with pytest.raises(ValidationError):
            OtelExportRegisters(endpoint=ENDPOINT, headers={"authorization": "Bearer x"})

    def test_round_trip_through_dict_keeps_non_default_values(self) -> None:
        """Dict at Boundary: значения переживают рейс через `dict` и класс регистров."""
        from Plugins.io.otel_export.registers import OtelExportRegisters

        reg = OtelExportRegisters(
            endpoint=ENDPOINT,
            level="ERROR",
            compression="none",
            headers={"authorization": "${OTEL_TOKEN}"},
            max_queue_size=4096,
            schedule_delay_ms=250,
            resource_pool_size=8,
        )
        restored = OtelExportRegisters.from_dict(reg.to_dict())
        assert restored == reg
        assert restored.headers == {"authorization": "${OTEL_TOKEN}"}
        assert restored.compression == "none"


# ---------------------------------------------------------------------------
# Разрыв контракта с фреймворком и правила слоя
# ---------------------------------------------------------------------------


class TestObservabilityPortGap:
    """ADR-OTEL-004: порт из пяти методов против настоящего `PluginContext`."""

    def test_port_declares_exactly_the_five_methods(self) -> None:
        """Состав порта — литералом. Тихо выросший порт перестаёт быть минимальным."""
        from Services.otel_export.interfaces import ObservabilityPort

        assert set(ObservabilityPort.__protocol_attrs__) == {
            "log_info",
            "log_warning",
            "log_error",
            "record_metric",
            "report_error",
        }

    def test_plugin_context_still_lacks_report_error(self) -> None:
        """Сторож ADR-OTEL-004: сегодня `report_error` живёт на `ctx.health`, не на `ctx`.

        Тест краснеет в ОБЕ стороны и обе полезны: если фреймворк добавит
        `PluginContext.report_error` (кандидат-долг closure), адаптер Ф2.1
        станет лишним и ADR надо переписать; если `health` перестанет быть
        свойством — адаптер сломается молча.
        """
        from multiprocess_framework.modules.process_module.plugins import PluginContext

        assert not hasattr(PluginContext, "report_error"), (
            "PluginContext обзавёлся report_error — ADR-OTEL-004 устарел, адаптер в Ф2.1 может оказаться не нужен"
        )
        assert isinstance(PluginContext.health, property), (
            "report_error достижим только через свойство ctx.health — если это "
            "изменилось, адаптер порта надо переписать"
        )


class TestLayerRules:
    """Правила плана, зелёные уже сегодня — стражи на будущее, не доказательства."""

    def test_no_platform_branches_in_the_subject(self) -> None:
        """`if sys.platform` в сервисе и плагине — признак не той задачи (правило 9 плана).

        **Честно: зелен по построению сегодня** — платформенных веток никто не
        писал. Ценность в том, что первая же попытка их завести станет красной.
        """
        offenders: list[str] = []
        for directory in SUBJECT_DIRS:
            for py_file in directory.rglob("*.py"):
                if "tests" in py_file.relative_to(directory).parts:
                    continue
                text = py_file.read_text(encoding="utf-8")
                if "sys.platform" in text or "platform.system()" in text:
                    offenders.append(str(py_file.relative_to(REPO_ROOT)))
        assert not offenders, f"платформенная ветка в предмете: {offenders}"

    def test_service_does_not_import_plugins_or_prototype(self) -> None:
        """Слой `Services` не смотрит вверх: ни `Plugins.*`, ни `multiprocess_prototype.*`.

        Разбор AST, а не grep: упоминание слоя в докстринге (а их здесь много)
        импортом не является.
        """
        service_dir = SUBJECT_DIRS[0]
        offenders: list[str] = []
        for py_file in service_dir.rglob("*.py"):
            if "tests" in py_file.relative_to(service_dir).parts:
                continue
            tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
            for node in ast.walk(tree):
                names: list[str] = []
                if isinstance(node, ast.Import):
                    names = [a.name for a in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module:
                    names = [node.module]
                for name in names:
                    if name.startswith(("Plugins", "multiprocess_prototype")):
                        offenders.append(f"{py_file.relative_to(REPO_ROOT)}: {name}")
        assert not offenders, f"обратный импорт слоя: {offenders}"


class TestInstallHint:
    """Текст отказа — то, что оператор увидит в readback."""

    def test_hint_carries_the_inexact_flag(self) -> None:
        """`--inexact` в команде обязателен: без него `uv sync` сносит необъявленное.

        Флаг стоит здесь литералом, потому что теряется он молча — команда без
        него выглядит правильной и ломает окружение уже после установки.
        """
        from Services.otel_export.exporter import INSTALL_HINT

        assert "--inexact" in INSTALL_HINT
        assert "'.[otel]'" in INSTALL_HINT
