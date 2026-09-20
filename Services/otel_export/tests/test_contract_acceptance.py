"""Приёмочные тесты контракта Services/otel_export — Task 0.4 плана otel-export.md.

НЕЗАВИСИМЫЙ тестер, ДО реализации. Источник критериев — акты приёмки Task 0.4
(секции A: стандарт слоя Services/, B: конфиг-схема OtelExportConfig, D: Protocol-
контракты interfaces.py). Ничего из будущей реализации не читалось: на момент
написания каталога ``Services/otel_export`` не существует вовсе (проверено —
``ls`` даёт ``No such file or directory``).

Импорт предмета — ВНУТРИ каждого теста (не на уровне модуля), чтобы
``pytest --collect-only`` видел полный список тестов даже когда пакета ещё нет
(инъекционная матрица считает СОБРАННЫЕ тесты числом, а не оставшиеся зелёными).

Сейчас все тесты обязаны быть КРАСНЫМИ: ``ModuleNotFoundError`` на
``Services.otel_export`` (пакета нет) — это ожидаемый и единственно верный вид
падения, не поломанная настройка теста.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

# Services/otel_export/tests/test_contract_acceptance.py -> repo root
REPO_ROOT = Path(__file__).resolve().parents[3]
SERVICE_DIR = REPO_ROOT / "Services" / "otel_export"


# ---------------------------------------------------------------------------
# A. Стандарт слоя Services/
# ---------------------------------------------------------------------------


class TestLayerStandard:
    """A1-A4: у Services/otel_export должен быть тот же скелет, что у sql/hikvision_camera."""

    def test_a1_required_artifacts_exist_on_disk(self) -> None:
        """A1: обязательные файлы слоя присутствуют физически.

        Как краснеет: сейчас каталога Services/otel_export нет вовсе — любой
        путь ниже не существует, тест падает на первом же assert.
        Как позеленеет: teamlead создаёт __init__.py, interfaces.py, STATUS.md,
        README.md и каталог tests/ внутри Services/otel_export.
        """
        required = ["__init__.py", "interfaces.py", "STATUS.md", "README.md"]
        missing = [name for name in required if not (SERVICE_DIR / name).is_file()]
        assert not missing, f"Отсутствуют файлы стандарта слоя: {missing} в {SERVICE_DIR}"
        assert (SERVICE_DIR / "tests").is_dir(), "Отсутствует Services/otel_export/tests/"

    def test_a1_validate_script_checks_and_passes_the_new_service(self) -> None:
        """A1: `python scripts/validate.py` зелёный ПРИ наличии сервиса.

        Ловушка: validate.py проверяет структуру Services/ только для сервисов,
        перечисленных в его собственном списке SERVICES — otel_export туда пока
        не попал, поэтому "просто запустить и проверить exit code" сегодня
        тривиально зелено (сервис никто не смотрит) и остался бы зелёным даже
        без единого файла. Поэтому тест ДОПОЛНИТЕЛЬНО требует, чтобы
        otel_export был зарегистрирован в SERVICES (и в
        SERVICES_REQUIRED_INTERFACES — интерфейсы обязательны по контракту) —
        иначе зелёный exit code ничего не доказывает.

        Как краснеет сейчас: 'otel_export' отсутствует в scripts.validate.SERVICES
        -> AssertionError на первой проверке, до вызова subprocess.
        Как позеленеет: сервис зарегистрирован в обоих списках validate.py И
        `python scripts/validate.py` реально завершается кодом 0.
        """
        import scripts.validate as validate_module

        assert "otel_export" in validate_module.SERVICES, (
            "otel_export не зарегистрирован в scripts.validate.SERVICES — иначе структура сервиса вообще не проверяется"
        )
        assert "otel_export" in validate_module.SERVICES_REQUIRED_INTERFACES, (
            "otel_export не зарегистрирован в SERVICES_REQUIRED_INTERFACES — "
            "иначе отсутствие interfaces.py будет только предупреждением, не ошибкой"
        )

        # Кодировка задана ЯВНО с обеих сторон трубы (правка исполнителя Task 0.4,
        # причина названа в отчёте). `text=True` без `encoding` брал локаль
        # родителя — cp1251 на этой машине, — а дочерний validate.py печатает
        # по-русски и при PYTHONIOENCODING=utf-8 в окружении писал UTF-8. Поток
        # чтения падал UnicodeDecodeError, `result.stdout` приходил `None`, и
        # тест валился `TypeError: argument of type 'NoneType' is not iterable`
        # — при зелёном validate.py. То есть исход теста зависел от переменной
        # окружения запускающего, а не от предмета. Проверяемое свойство
        # (validate зелёный И упомянул otel_export) не изменилось.
        result = subprocess.run(
            [sys.executable, "scripts/validate.py"],
            cwd=str(REPO_ROOT),
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
            timeout=180,
        )
        assert result.returncode == 0, (
            f"scripts/validate.py упал (exit={result.returncode}).\n"
            f"stdout(хвост):\n{result.stdout[-3000:]}\nstderr:\n{result.stderr[-2000:]}"
        )
        assert "otel_export" in result.stdout, (
            "validate.py не упомянул otel_export в выводе — проверка структуры сервиса не выполнялась фактически"
        )

    def test_a2_readme_has_required_sections(self) -> None:
        """A2: README содержит разделы Purpose / Public API / Usage / Boundaries / Stability.

        Заголовки названы в акте приёмки по-английски (шаблон skill'а
        module-contract) — это расходится с общеязыковой политикой проекта
        "документация по-русски", но здесь это ЯВНО заданный литерал критерия,
        не моя интерпретация; см. открытый вопрос в отчёте тестера.
        Проверка требует настоящего markdown-заголовка (строка начинается с
        `#`), а не любого упоминания слова в тексте — иначе раздел "Usage"
        засчитался бы по одному случайному слову в описании.
        Как краснеет: README.md не существует (FileNotFoundError) или,
        когда появится без одного из разделов-заголовков — AssertionError
        с именем недостающего раздела.
        """
        import re

        readme = SERVICE_DIR / "README.md"
        text = readme.read_text(encoding="utf-8")
        required_sections = ["Purpose", "Public API", "Usage", "Boundaries", "Stability"]
        missing = [
            s for s in required_sections if not re.search(rf"^#{{1,6}}\s*{re.escape(s)}\b", text, flags=re.MULTILINE)
        ]
        assert not missing, f"В README.md нет заголовков-разделов: {missing}"

    def test_a3_dunder_all_matches_interfaces_reexport(self) -> None:
        """A3: __init__.__all__ совпадает МНОЖЕСТВОМ с тем, что реэкспортируется из interfaces.py.

        Значение берётся из предмета (interfaces.__all__), а не переписывается
        руками в тесте — иначе тест сторожит собственную копию списка, а не
        реальное соответствие.
        Как краснеет: пакета Services.otel_export нет -> ModuleNotFoundError.
        Как позеленеет: __init__.py делает `from .interfaces import *`
        (или явный список), и оба __all__ содержат ОДНО и то же множество имён.
        """
        import Services.otel_export as pkg
        import Services.otel_export.interfaces as iface

        pkg_all = set(getattr(pkg, "__all__", []))
        iface_all = set(getattr(iface, "__all__", []))

        assert pkg_all, "Services.otel_export.__all__ пуст или не объявлен"
        assert iface_all, "Services.otel_export.interfaces.__all__ пуст или не объявлен"
        assert pkg_all == iface_all, f"__init__.__all__ ({pkg_all}) расходится с interfaces.__all__ ({iface_all})"
        # Каждое реэкспортированное имя обязано реально резолвиться из пакета,
        # иначе __all__ — просто список строк, ничему не соответствующий.
        for name in pkg_all:
            assert hasattr(pkg, name), f"{name} есть в __all__, но не является атрибутом пакета"

    def test_a4_status_declares_contract_state(self) -> None:
        """A4: STATUS.md сервиса в состоянии `contract`.

        Открытый момент (см. отчёт тестера): проект не использует единое имя
        поля состояния (встречались "Готовность:", "Текущий статус:",
        "Состояние:") — поэтому тест ищет литерал "contract" где-либо в тексте
        файла, не привязываясь к конкретному заголовку поля.
        Как краснеет: файла нет -> FileNotFoundError.
        """
        status = SERVICE_DIR / "STATUS.md"
        text = status.read_text(encoding="utf-8").lower()
        assert "contract" in text, "STATUS.md не называет состояние 'contract'"


# ---------------------------------------------------------------------------
# B. Конфиг-схема Services/otel_export/config.py — OtelExportConfig(SchemaBase)
# ---------------------------------------------------------------------------


class TestConfigSchema:
    """B1-B6: контракт полей OtelExportConfig, независимый от реализации валидатора."""

    def test_b1_endpoint_is_required_and_named_in_the_error(self) -> None:
        """B1: endpoint обязателен, без дефолта; ValidationError называет поле `endpoint`.

        Тест пишет ожидание литералом ("endpoint"), а не берёт его из кода.
        Как краснеет: ModuleNotFoundError (пакета нет) сегодня; после появления
        конфига с дефолтным/опциональным endpoint — тест не поднимет
        ValidationError вовсе (pytest.raises провалится сам).
        """
        from pydantic import ValidationError

        from Services.otel_export.config import OtelExportConfig

        with pytest.raises(ValidationError) as exc_info:
            OtelExportConfig()

        errors = exc_info.value.errors()
        locs = [".".join(str(p) for p in err["loc"]) for err in errors]
        assert "endpoint" in locs, f"endpoint не назван в ValidationError.errors(): {locs}"
        assert "endpoint" in str(exc_info.value), "'endpoint' не упомянут в тексте ошибки"

    def test_b2_documented_defaults(self) -> None:
        """B2: level="INFO", compression="gzip", headers={}, service_namespace — поле есть.

        Значения — литералы из акта приёмки B2, не производные от кода.
        """
        from Services.otel_export.config import OtelExportConfig

        cfg = OtelExportConfig(endpoint="http://collector.local:4318/v1/logs")
        assert cfg.level == "INFO"
        assert cfg.compression == "gzip"
        assert cfg.headers == {}
        assert "service_namespace" in type(cfg).model_fields, "нет поля service_namespace"

    def test_b3_batcher_defaults_match_installed_sdk_1_44_0(self) -> None:
        """B3: дефолты батчера равны дефолтам УСТАНОВЛЕННОГО opentelemetry-sdk 1.44.0.

        Литералы (2048 / 1000 / 512 / 30000) сверены НЕ с кодом сервиса, а
        напрямую с исходником установленного пакета:
        opentelemetry/sdk/_logs/_internal/export/__init__.py -
        _DEFAULT_MAX_QUEUE_SIZE=2048, _DEFAULT_SCHEDULE_DELAY_MILLIS=1000,
        _DEFAULT_MAX_EXPORT_BATCH_SIZE=512, _DEFAULT_EXPORT_TIMEOUT_MILLIS=30000
        (прочитано из файла напрямую 2026-09-05, тестер).
        """
        from Services.otel_export.config import OtelExportConfig

        cfg = OtelExportConfig(endpoint="http://collector.local:4318/v1/logs")
        assert cfg.max_queue_size == 2048
        assert cfg.schedule_delay_ms == 1000
        assert cfg.max_export_batch_size == 512
        assert cfg.export_timeout_ms == 30000

    def test_b4_resource_pool_size_has_positive_default(self) -> None:
        """B4: resource_pool_size — поле есть, дефолт положительный."""
        from Services.otel_export.config import OtelExportConfig

        cfg = OtelExportConfig(endpoint="http://collector.local:4318/v1/logs")
        assert "resource_pool_size" in type(cfg).model_fields
        assert cfg.resource_pool_size > 0

    def test_b5_headers_reject_literal_secret_value(self) -> None:
        """B5: литеральное значение заголовка (не ${ENV}) отвергается ValidationError.

        Как краснеет: сейчас ModuleNotFoundError; после реализации без этой
        валидации — pytest.raises не поднимется, тест провалится штатно.
        """
        from pydantic import ValidationError

        from Services.otel_export.config import OtelExportConfig

        with pytest.raises(ValidationError):
            OtelExportConfig(
                endpoint="http://collector.local:4318/v1/logs",
                headers={"authorization": "Bearer secret123"},
            )

    def test_b5_headers_accept_env_placeholder(self) -> None:
        """B5 (парная): значение вида ${ENV_VAR} принимается без ошибки."""
        from Services.otel_export.config import OtelExportConfig

        cfg = OtelExportConfig(
            endpoint="http://collector.local:4318/v1/logs",
            headers={"authorization": "${OTEL_AUTH_TOKEN}"},
        )
        assert cfg.headers["authorization"] == "${OTEL_AUTH_TOKEN}"

    def test_b6_to_dict_from_dict_round_trip(self) -> None:
        """B6: Dict at Boundary — from_dict(to_dict()) даёт равный объект."""
        from Services.otel_export.config import OtelExportConfig

        cfg = OtelExportConfig(endpoint="http://collector.local:4318/v1/logs", level="DEBUG")
        as_dict = cfg.to_dict()
        assert isinstance(as_dict, dict)
        restored = OtelExportConfig.from_dict(as_dict)
        assert restored == cfg


# ---------------------------------------------------------------------------
# D. Protocol-контракты Services/otel_export/interfaces.py
# ---------------------------------------------------------------------------


def _params_excluding_self(func) -> list[str]:
    import inspect

    sig = inspect.signature(func)
    return [name for name in sig.parameters if name != "self"]


def _return_annotation_text(func) -> str:
    """Строковое представление аннотации возврата — без get_type_hints().

    get_type_hints() падает NameError, если контракт легитимно прячет тип OTel
    (напр. Resource) под `if TYPE_CHECKING:` — а именно так и надо делать по
    критерию E1 (ни одного `import opentelemetry` на уровне модуля).
    inspect.signature() читает аннотацию из живого объекта функции без
    попытки её резолвить, поэтому работает и со строковой (PEP 563), и с
    настоящей аннотацией.
    """
    import inspect

    sig = inspect.signature(func)
    return str(sig.return_annotation)


class TestProtocolContracts:
    """D1-D6: пять Protocol-контрактов interfaces.py — по сигнатуре, не по тексту файла."""

    def test_d1_record_mapper_to_otlp_signature(self) -> None:
        """D1: RecordMapper.to_otlp(display_record) -> MappedRecord | None."""
        from Services.otel_export.interfaces import RecordMapper

        assert _params_excluding_self(RecordMapper.to_otlp) == ["display_record"]
        ret = _return_annotation_text(RecordMapper.to_otlp)
        assert "MappedRecord" in ret, f"возврат не упоминает MappedRecord: {ret!r}"
        assert "None" in ret, f"возврат не допускает None (отказ маппинга): {ret!r}"

    def test_d2_resource_resolver_resolve_signature(self) -> None:
        """D2: ResourceResolver.resolve(context) -> Resource."""
        from Services.otel_export.interfaces import ResourceResolver

        assert _params_excluding_self(ResourceResolver.resolve) == ["context"]
        ret = _return_annotation_text(ResourceResolver.resolve)
        assert "Resource" in ret, f"возврат не упоминает Resource: {ret!r}"

    def test_d3_log_exporter_export_signature_and_outcome_fields(self) -> None:
        """D3: LogExporter.export(records) -> ExportOutcome(accepted, failed, reason)."""
        from Services.otel_export.interfaces import ExportOutcome, LogExporter

        assert _params_excluding_self(LogExporter.export) == ["records"]
        ret = _return_annotation_text(LogExporter.export)
        assert "ExportOutcome" in ret, f"возврат не упоминает ExportOutcome: {ret!r}"

        outcome = ExportOutcome(accepted=3, failed=1, reason="батч частично отклонён")
        assert outcome.accepted == 3
        assert outcome.failed == 1
        assert outcome.reason == "батч частично отклонён"

    def test_d4_log_exporter_force_flush_signature_and_outcome_fields(self) -> None:
        """D4: LogExporter.force_flush(timeout) -> FlushOutcome(flushed, lost)."""
        from Services.otel_export.interfaces import FlushOutcome, LogExporter

        assert _params_excluding_self(LogExporter.force_flush) == ["timeout"]
        ret = _return_annotation_text(LogExporter.force_flush)
        assert "FlushOutcome" in ret, f"возврат не упоминает FlushOutcome: {ret!r}"

        outcome = FlushOutcome(flushed=10, lost=0)
        assert outcome.flushed == 10
        assert outcome.lost == 0

    def test_d5_observability_port_accepts_full_implementation(self) -> None:
        """D5: ObservabilityPort — структурное соответствие по isinstance (runtime_checkable).

        Положительный случай: объект с пятью нужными методами проходит
        isinstance. Отрицательный (test_d5_observability_port_rejects_partial_*)
        — объект без report_error не проходит.
        """
        from Services.otel_export.interfaces import ObservabilityPort

        class FullObservability:
            def log_info(self, message, **kw): ...
            def log_warning(self, message, **kw): ...
            def log_error(self, message, **kw): ...
            def record_metric(self, name, value, **kw): ...
            def report_error(self, error, **kw): ...

        assert isinstance(FullObservability(), ObservabilityPort)

    def test_d5_observability_port_rejects_partial_implementation(self) -> None:
        """D5 (парная): без report_error объект НЕ проходит структурную проверку."""
        from Services.otel_export.interfaces import ObservabilityPort

        class MissingReportError:
            def log_info(self, message, **kw): ...
            def log_warning(self, message, **kw): ...
            def log_error(self, message, **kw): ...
            def record_metric(self, name, value, **kw): ...

        assert not isinstance(MissingReportError(), ObservabilityPort)

    def test_d6_all_five_are_runtime_checkable_protocols(self) -> None:
        """D6: RecordMapper, ResourceResolver, LogExporter, ObservabilityPort — typing.Protocol,
        помеченные @runtime_checkable (не ABC, не голый класс).

        Проверка двойная: `_is_protocol` (объявлен как Protocol) И то, что
        isinstance() вообще не бросает TypeError (доказательство
        @runtime_checkable — без декоратора isinstance() на Protocol-классе
        поднимает "Instance and class checks can only be used with
        @runtime_checkable protocols").
        """
        from Services.otel_export.interfaces import (
            LogExporter,
            ObservabilityPort,
            RecordMapper,
            ResourceResolver,
        )

        for cls in (RecordMapper, ResourceResolver, LogExporter, ObservabilityPort):
            assert getattr(cls, "_is_protocol", False) is True, f"{cls.__name__} не объявлен как typing.Protocol"
            try:
                isinstance(object(), cls)
            except TypeError as exc:
                pytest.fail(f"{cls.__name__} не @runtime_checkable: {exc}")
