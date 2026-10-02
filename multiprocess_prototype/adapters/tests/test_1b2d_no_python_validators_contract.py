# -*- coding: utf-8 -*-
"""RED-приёмка Task 1b.2d, AC4 — контракт «у register-классов нет python-валидаторов».

Независимый тестер, без реализации. Идея: копия регистра на GUI-стороне строится из
``FieldInfo`` + ``FieldMeta`` и python-код класса (``field_validator`` /
``model_validator``) туда не доезжает. Значит правило такое: любое правило проверки
значения, которое у реального register-класса живёт в python-валидаторе, ДОЛЖНО быть
выражено данными (иначе копия расходится с оригиналом). Этот файл проверяет КЛАССЫ, а не
исходный текст: обходит реальные register-классы каталога ``Plugins/`` (``discover`` в
этом процессе), смотрит ``__pydantic_decorators__`` каждого класса по MRO (включая
унаследованные — ``OtelExportRegisters`` не объявляет валидаторов сам, они приходят от
``OtelExportConfig`` из ``Services/``), и падает на любом ``field_validator`` /
``model_validator``.

ПРОГНОЗ ДО ЗАПУСКА (записан до первого прогона): валидаторы несут РОВНО 2 register-класса —
``line_filter`` (1 model_validator: ``_check_hysteresis``) и ``otel_export`` (унаследованные
от ``OtelExportConfig``: 4 field_validator — ``_endpoint_not_blank``,
``_endpoint_carries_signal_path``, ``_level_is_known``, ``_headers_only_env_placeholders`` —
и 1 model_validator ``_batch_fits_queue``). Итого 6 деклараций в 2 регистрах.
``blur`` (``register_classes == []``) вне проверки намеренно.

Что считается нарушением: объявление валидатора, найденное у класса или у любого предка по
MRO, дедуплицированное по (класс-владелец, имя метода) — иначе наследование считалось бы
дважды (pydantic копирует декораторы родителя в ``__pydantic_decorators__`` потомка).

ЧТО НЕ ЯВЛЯЕТСЯ НАРУШЕНИЕМ (измерено при первом прогоне — прогноз выше оказался неполным):
у самого ``SchemaBase`` есть собственный ``model_validator`` ``_check_field_constraints``
(данные-ориентированный: применяет ``FieldMeta``-ограничения). Он есть у КАЖДОГО регистра, и
копия строится на ``SchemaBase`` (``create_model(__base__=SchemaBase)``) — то есть он у копии
тоже есть. Поэтому валидаторы, объявленные на ``SchemaBase`` и его предках, вычитаются:
контракт говорит про python-код, который несёт ТОЛЬКО исходный класс плагина.
Ровно это вычитание — ИНТЕРПРЕТАЦИЯ тестера, а не данное; см. отчёт.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, field_validator, model_validator

from multiprocess_framework.modules.data_schema_module import SchemaBase
from multiprocess_framework.modules.app_module import discover as app_discover
from multiprocess_framework.modules.process_module.plugins.registry import PluginRegistry


def _repo_root() -> Path:
    # tests/ -> adapters -> multiprocess_prototype -> repo root
    return Path(__file__).resolve().parents[3]


def _validators_of(cls: type) -> set[tuple[str, str, str]]:
    """{(kind, класс-владелец, имя метода)} по всей MRO класса, дедуплицировано.

    ``kind`` — ``"field_validator"`` | ``"model_validator"``. Владелец — тот класс MRO, в
    ``vars()`` которого метод ДЕЙСТВИТЕЛЬНО объявлен. ``Decorator.cls_ref`` для этого не
    годится (измерено: pydantic перепривязывает его к потомку, и унаследованный валидатор
    выглядит объявленным в каждом подклассе — счёт 98 вместо реального).
    """
    found: set[tuple[str, str, str]] = set()
    for klass in cls.__mro__:
        decorators = getattr(klass, "__pydantic_decorators__", None)
        if decorators is None:
            continue
        for kind, bucket in (
            ("field_validator", decorators.field_validators),
            ("model_validator", decorators.model_validators),
        ):
            for name in bucket:
                if name in vars(klass):
                    found.add((kind, f"{klass.__module__}.{klass.__qualname__}", name))
    return found


def _register_classes_of_catalog() -> list[tuple[str, type]]:
    """[(имя плагина, register-класс)] по discover(Plugins/) — тот же паттерн, что в 1b.2b-pre."""
    app_discover(plugin_paths=[str(_repo_root() / "Plugins")], service_paths=[])
    return [(e.name, e.register_classes[0]) for e in PluginRegistry.list() if e.register_classes]


# ---------------------------------------------------------------------------
# Контроль детектора: без него «ни одного валидатора» могло бы значить «обходчик слеп»
# ---------------------------------------------------------------------------


def test_walker_sees_inherited_validators_positive_control() -> None:
    """Обходчик находит и собственные, и УНАСЛЕДОВАННЫЕ field/model-валидаторы (синтетика).

    Ожидание литералом: родитель объявляет 1 field_validator + 1 model_validator, потомок —
    ни одного; обходчик обязан вернуть оба для потомка (ровно 2 записи, владелец — родитель).
    """

    class _Parent(BaseModel):
        x: int = 1

        @field_validator("x")
        @classmethod
        def _x_ok(cls, v: int) -> int:
            return v

        @model_validator(mode="after")
        def _whole_ok(self) -> "_Parent":
            return self

    class _Child(_Parent):
        y: int = 2

    found = _validators_of(_Child)
    kinds_and_names = {(kind, name) for kind, _owner, name in found}
    assert kinds_and_names == {("field_validator", "_x_ok"), ("model_validator", "_whole_ok")}
    assert len(found) == 2, f"наследование посчитано дважды или потеряно: {sorted(found)}"


def test_walker_covers_real_catalog_not_an_empty_walk() -> None:
    """Обход не пуст: 43 плагина с register-классом на этом дереве (измерено 2026-10-02, 58 всего).

    Нижняя граница, а не равенство: новый плагин не должен валить контракт, но обход,
    сократившийся до пары классов, обязан.
    """
    classes = _register_classes_of_catalog()
    names = {n for n, _ in classes}
    assert len(classes) >= 43, f"обошли только {len(classes)} register-классов, измерено 43"
    assert {"line_filter", "otel_export", "center_crop"} <= names
    assert "blur" not in names, "blur (register_classes == []) вне контракта 1b.2d — не должен попадать в обход"


# ---------------------------------------------------------------------------
# AC4 — сам контракт
# ---------------------------------------------------------------------------


def test_register_classes_have_no_python_validators() -> None:
    """Post: ни у одного register-класса каталога (включая MRO) нет field/model-валидатора.

    Прогноз до запуска: 6 деклараций в 2 регистрах (line_filter, otel_export) — см. шапку.
    """
    violations: dict[str, list[str]] = {}
    for plugin_name, cls in _register_classes_of_catalog():
        found = _validators_of(cls) - _validators_of(SchemaBase)
        if found:
            violations[plugin_name] = sorted(f"{kind}:{owner.rsplit('.', 1)[-1]}.{name}" for kind, owner, name in found)

    total = sum(len(v) for v in violations.values())
    assert not violations, (
        f"python-валидаторы у register-классов: {total} деклараций в {len(violations)} регистрах "
        f"(прогноз: 6 в 2 — line_filter, otel_export): {violations}"
    )
