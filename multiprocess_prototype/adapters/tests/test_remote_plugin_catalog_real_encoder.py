# -*- coding: utf-8 -*-
"""Паритет на РЕАЛЬНОМ кодировщике (Task 1b.2a, находка break-injection лида I1).

Тестер (``test_remote_plugin_catalog_acceptance.py::test_remote_catalog_parity_with_local``)
строит wire-payload СВОЕЙ параллельной копией ``_field_dict``/``_build_catalog_payload``
(явно помечено как фикстура в его файле, не эталон второго уровня истины) — реальный
энкодер (``FieldInfo.to_dict()`` внутри ``_cmd_catalog_plugins``) ни разу не выполняется
внутри цикла сравнения. Инъекция I1 лида (``to_dict()`` эмитит ``choices: []`` всегда,
вместо реальных значений Literal) осталась GREEN там именно поэтому — обе стороны
сравнения (local и remote) строились одной и той же тестовой копией формулы.

Здесь — единственный тест, который зовёт РЕАЛЬНЫЙ ``BuiltinCommands._cmd_catalog_plugins``
(тот же путь, что живой хаб) и сверяет его выход с НЕЗАВИСИМЫМ от ``FieldInfo.to_dict()``
пересчётом тега типа и choices прямо из ``fi.field_type`` (get_origin/get_args) — если
бы локальный расчёт шёл через тот же ``to_dict()``, инъекция в ``to_dict()`` ломала бы
ОБЕ стороны одинаково и тест остался бы GREEN, как у тестера.
"""

from __future__ import annotations

import types as _types
from pathlib import Path
from typing import Any, Literal, get_args, get_origin


def _repo_root() -> Path:
    # tests/ -> adapters -> multiprocess_prototype -> repo root
    return Path(__file__).resolve().parents[3]


_UNION_REPRS = ("typing.Union", "<class 'types.UnionType'>")


def _independent_type_tag_and_choices(field_type: Any) -> tuple[str, tuple[Any, ...]]:
    """Пересчитать (тег, choices) ИЗ ПОЛЯ НАПРЯМУЮ — БЕЗ вызова FieldInfo.to_dict().

    Дублирует закрытый набор тегов DESIGN (bool|int|float|str|path|literal|tuple3int|
    list|dict|unsupported), но независимо от `field_info.py::_type_tag`/`_unwrap_optional` —
    если инъекция портит именно to_dict()/эти внутренние хелперы, эта функция её не
    унаследует, и паритет реально может разойтись.
    """
    t = field_type
    origin = get_origin(t)
    if origin is _types.UnionType or (origin is not None and repr(origin) in _UNION_REPRS):
        non_none = [a for a in get_args(t) if a is not type(None)]
        if len(non_none) == 1:
            t = non_none[0]
            origin = get_origin(t)

    if t is bool:
        return "bool", ()
    if origin is Literal:
        return "literal", tuple(get_args(t))
    if origin is tuple and get_args(t) == (int, int, int):
        return "tuple3int", ()
    if t is int:
        return "int", ()
    if t is float:
        return "float", ()
    if t is str:
        return "str", ()
    if t is Path:
        return "path", ()
    if t is dict or origin is dict:
        return "dict", ()
    if t is list or origin is list:
        return "list", ()
    return "unsupported", ()


def test_remote_catalog_matches_local_extract_fields_via_real_encoder() -> None:
    """Post: RemotePluginCatalog(real _cmd_catalog_plugins) паритетен НЕЗАВИСИМОМУ пересчёту полей/портов.

    В отличие от тестерского parity-теста, здесь payload строит РЕАЛЬНЫЙ хаб-хендлер
    (``_cmd_catalog_plugins``, тот же код, что уходит в прод), а не тестовая копия
    формулы — инъекция в ``FieldInfo.to_dict()``/хендлере обязана здесь проявиться.
    """
    from multiprocess_framework.modules.app_module import discover as app_discover
    from multiprocess_framework.modules.process_module.commands.builtin_commands import (
        BuiltinCommands,
    )
    from multiprocess_framework.modules.process_module.plugins.registry import PluginRegistry
    from multiprocess_framework.modules.process_module.plugins.testing import MockProcessServices
    from multiprocess_framework.modules.registers_module.core.field_info import extract_fields
    from multiprocess_prototype.adapters.catalogs.remote_plugin_catalog import RemotePluginCatalog

    plugins_dir = _repo_root() / "Plugins"
    app_discover(plugin_paths=[str(plugins_dir)], service_paths=[])
    entries = PluginRegistry.list()
    assert entries, "локальный discover(Plugins/) не нашёл ни одного плагина — фикстура сломана"

    # РЕАЛЬНЫЙ хендлер — не параллельная копия сборки payload.
    services = MockProcessServices(name="parity_real_encoder_test")
    cm = BuiltinCommands(services)
    real_payload = cm._cmd_catalog_plugins()
    assert real_payload["success"] is True

    def fake_request(command: str, args: dict) -> dict:
        assert command == "catalog.plugins"
        return {"success": True, "result": real_payload}

    catalog = RemotePluginCatalog(fake_request)

    by_name_local = {e.name: e for e in entries}
    assert {s.name for s in catalog.list_plugins()} == set(by_name_local)

    for spec in catalog.list_plugins():
        entry = by_name_local[spec.name]

        # --- поля: независимый пересчёт из ЖИВЫХ FieldInfo (extract_fields), не через to_dict() ---
        local_fields = (
            extract_fields(entry.name, entry.register_classes[0], entry.category) if entry.register_classes else []
        )
        local_field_set = set()
        for fi in local_fields:
            tag, choices = _independent_type_tag_and_choices(fi.field_type)
            local_field_set.add((fi.field_name, tag, choices))

        remote_fields = (spec.config_schema or {}).get("fields") or []
        remote_field_set = {(f["field_name"], f["type"], tuple(f.get("choices") or ())) for f in remote_fields}

        assert remote_field_set == local_field_set, (
            f"{entry.name}: паритет полей нарушен (реальный энкодер разошёлся с "
            f"независимым пересчётом типа/choices из field_type)"
        )

        # --- порты: сравнение напрямую с entry.inputs/entry.outputs (не с копией-фикстурой) ---
        local_ports = {(p.name, p.dtype, "input", bool(getattr(p, "optional", False))) for p in entry.inputs}
        local_ports |= {(p.name, p.dtype, "output", bool(getattr(p, "optional", False))) for p in entry.outputs}
        remote_ports = {(p.name, p.dtype, p.direction, p.optional) for p in spec.ports}
        assert remote_ports == local_ports, f"{entry.name}: паритет портов нарушен"
