# -*- coding: utf-8 -*-
"""RED-приёмка Task 1b.2a: dict-кодек FieldInfo/FieldMeta для передачи по IPC-границе.

Независимый тестер (без implementation) — контракт зафиксирован лидом (см. брифинг
Task 1b.2a, DESIGN). Проверяем ``FieldInfo.to_dict()``/``FieldInfo.from_dict()`` и
``FieldMeta.from_dict()``, которых сегодня нет в коде (импорт — ВНУТРИ каждого теста,
чтобы каждый падал независимо).

Framework-граница (Правило 9 CLAUDE.md): этот файл живёт под
``multiprocess_framework/`` и НЕ импортирует ``multiprocess_prototype`` статически —
``test_fieldinfo_roundtrip_same_kind_all_registers`` и
``test_fieldinfo_dict_is_json_safe`` сканируют ``Plugins/`` (framework-safe уровень)
через ``PluginRegistry.discover()`` динамически (по строковому пути, не import).

Type-tag набор (из DESIGN, зеркало ``kinds.py::_resolve_kind`` без учёта
``FieldMeta.widget``): bool|int|float|str|path|literal|tuple3int|list|dict|unsupported.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal, get_args, get_origin

from multiprocess_framework.modules.registers_module.core.field_info import (
    FieldInfo,
    extract_fields,
)


def _plugins_dir() -> Path:
    # tests/ -> registers_module -> modules -> multiprocess_framework -> repo root
    return Path(__file__).resolve().parents[4] / "Plugins"


def _discovered_field_infos() -> list[FieldInfo]:
    """Собрать FieldInfo по всем регистрам всех плагинов из локального discover(Plugins/).

    Framework-safe: только динамический ``PluginRegistry.discover(<str path>)`` —
    никакого статического ``import multiprocess_prototype``/``import Plugins``.
    """
    from multiprocess_framework.modules.app_module import discover as app_discover
    from multiprocess_framework.modules.process_module.plugins.registry import (
        PluginRegistry,
    )

    app_discover(plugin_paths=[str(_plugins_dir())], service_paths=[])

    infos: list[FieldInfo] = []
    for entry in PluginRegistry.list():
        if not entry.register_classes:
            continue
        infos.extend(extract_fields(entry.name, entry.register_classes[0], entry.category))
    return infos


class _Unsupported:
    """Тип, которого нет в закрытом наборе тегов — для unsupported-ветки кодека."""

    def __repr__(self) -> str:  # noqa: D105
        return "<_Unsupported sentinel>"


def test_fieldinfo_roundtrip_same_kind_all_registers() -> None:
    """Post: to_dict()/from_dict() сохраняет kind (= to_dict()['type']) для КАЖДОГО реального поля.

    Framework-граница: не зовём ``multiprocess_prototype.frontend.forms.factory.kinds
    ._resolve_kind`` напрямую (это статический import framework -> prototype, запрещён
    ``.sentrux/rules.toml`` даже вложенным внутрь функции — AST-guard, не top-level-only,
    см. ``docs/claude/memory/feedback_framework_tests_cannot_import_prototype.md``).
    Вместо этого сравниваем ``to_dict()['type']`` ДО и ПОСЛЕ round-trip — это framework-side
    эквивалент того же контракта («kind survives round-trip»), т.к. по DESIGN 'type' —
    закрытый набор тегов, зеркалящий _resolve_kind.
    """
    infos = _discovered_field_infos()
    assert infos, "локальный discover(Plugins/) не нашёл ни одного регистра — фикстура сломана"

    for fi in infos:
        d = fi.to_dict()
        restored = FieldInfo.from_dict(d)
        d_after = restored.to_dict()

        assert d_after["type"] == d["type"], (
            f"{fi.plugin_name}.{fi.field_name}: type-tag разошёлся после round-trip "
            f"({d['type']!r} -> {d_after['type']!r})"
        )

        origin = get_origin(fi.field_type)
        if origin is Literal:
            assert get_args(restored.field_type) == get_args(fi.field_type), (
                f"{fi.plugin_name}.{fi.field_name}: choices разошлись после round-trip"
            )


def test_fieldinfo_dict_is_json_safe() -> None:
    """Post: to_dict() — валидный JSON для каждого реального поля (граница IPC — dict)."""
    infos = _discovered_field_infos()
    assert infos, "локальный discover(Plugins/) не нашёл ни одного регистра — фикстура сломана"

    for fi in infos:
        d = fi.to_dict()
        roundtripped = json.loads(json.dumps(d))
        assert roundtripped == d, f"{fi.plugin_name}.{fi.field_name}: to_dict() не JSON-safe: {d!r}"


def test_fieldinfo_path_default_goes_as_str() -> None:
    """Post: Path default сериализуется как str на границе (никаких Path-объектов в dict)."""
    fi = FieldInfo(
        plugin_name="p",
        field_name="f",
        field_type=Path,
        default=Path("/tmp/x"),
        meta=None,
        category="c",
    )
    d = fi.to_dict()
    assert d == {
        "plugin_name": "p",
        "field_name": "f",
        "type": "path",
        "optional": False,
        "default": "/tmp/x",
        "meta": None,
        "category": "c",
    }


def test_fieldinfo_unknown_type_is_unsupported_not_exception() -> None:
    """Post: неизвестный тип поля -> tag 'unsupported', default=str(x), БЕЗ исключения."""
    sentinel = _Unsupported()
    fi = FieldInfo(
        plugin_name="p",
        field_name="f",
        field_type=_Unsupported,
        default=sentinel,
        meta=None,
        category="c",
    )
    d = fi.to_dict()  # не должно бросать
    assert d == {
        "plugin_name": "p",
        "field_name": "f",
        "type": "unsupported",
        "optional": False,
        "default": str(sentinel),
        "meta": None,
        "category": "c",
    }


def test_fieldmeta_from_dict_roundtrip_keeps_routing() -> None:
    """Post: FieldMeta.from_dict(to_dict()) сохраняет routing (CommandCatalog его читает)."""
    from multiprocess_framework.modules.data_schema_module import FieldMeta

    meta = FieldMeta(
        "Описание поля",
        info="подробности",
        unit="px",
        min=0.0,
        max=10.0,
        routing={"channel": "control_draw", "process_targets": ["preprocessor", "gui"]},
        access_level=1,
    )
    d = meta.to_dict()
    restored = FieldMeta.from_dict(d)

    assert restored.routing == {"channel": "control_draw", "process_targets": ["preprocessor", "gui"]}
    assert restored.description == "Описание поля"
    assert restored.min == 0.0
    assert restored.max == 10.0
    assert restored.access_level == 1
