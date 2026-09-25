# -*- coding: utf-8 -*-
"""RED-приёмка Task 1b.2a: RemotePluginCatalog — формы без plugin-кода на GUI-стороне.

Независимый тестер (без implementation) — контракт зафиксирован лидом (DESIGN брифинга
Task 1b.2a). Импорт ``RemotePluginCatalog`` (multiprocess_prototype/adapters/catalogs/
remote_plugin_catalog.py — не существует сегодня) — ВНУТРИ каждого теста, чтобы каждый
падал независимо (ModuleNotFoundError сегодня).

Этот файл живёт под ``multiprocess_prototype/`` — статические импорты prototype
разрешены (forward-direction, ADR-120 / Правило 9 CLAUDE.md).

Envelope-ловушка (docs/reviews/2026-09-24_gui-1b.1-green.md, п.2): payload команды лежит
под ``reply["result"]``, а не на верхнем уровне — так же, как у ``recipe.*``.

ОДНА ДОГАДКА (помечена явно, см. отчёт лиду): ``RemotePluginCatalog.resolve(name)
.config_schema["fields"]`` несёт список FieldInfo-словарей плагина (по аналогии с
``PluginCatalogFromRegistry._entry_to_spec`` TODO "Phase E — пока dict с именами
классов" — ``config_schema`` уже задуман как место для деталей регистра). Контракт NOT
прописан в domain Protocol явно; если разработчик выберет другое место — это находка,
не мой сломанный тест.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Literal, get_args, get_origin

import pytest


def _repo_root() -> Path:
    # tests/ -> adapters -> multiprocess_prototype -> repo root
    return Path(__file__).resolve().parents[3]


def _type_tag(field_type: Any) -> str:
    """Независимый (не из impl) тэггер типа — тот же закрытый набор, что в DESIGN.

    Мирроит порядок диспетчеризации ``kinds.py::_resolve_kind`` МИНУС явный
    ``FieldMeta.widget``-override (это только про Python-тип поля, не про UI-виджет).
    """
    t = field_type
    origin = get_origin(t)
    union_reprs = ("typing.Union", "<class 'types.UnionType'>")
    if origin is not None and (repr(origin) in union_reprs):
        non_none = [a for a in get_args(t) if a is not type(None)]
        if len(non_none) == 1:
            t = non_none[0]
            origin = get_origin(t)

    if t is bool:
        return "bool"
    if origin is Literal:
        return "literal"
    if origin is tuple and get_args(t) == (int, int, int):
        return "tuple3int"
    if t is int:
        return "int"
    if t is float:
        return "float"
    if t is str:
        return "str"
    if t is Path:
        return "path"
    if t is dict or origin is dict:
        return "dict"
    if t is list or origin is list:
        return "list"
    return "unsupported"


def _is_optional(field_type: Any) -> bool:
    origin = get_origin(field_type)
    union_reprs = ("typing.Union", "<class 'types.UnionType'>")
    if origin is not None and repr(origin) in union_reprs:
        return type(None) in get_args(field_type)
    return False


def _safe_default(default: Any) -> Any:
    if isinstance(default, Path):
        return str(default)
    try:
        json.dumps(default)
        return default
    except TypeError:
        return str(default)


def _field_dict(fi: Any) -> dict[str, Any]:
    """Локальный (не из impl) построитель FieldInfo-словаря — та же форма, что DESIGN."""
    d: dict[str, Any] = {
        "plugin_name": fi.plugin_name,
        "field_name": fi.field_name,
        "type": _type_tag(fi.field_type),
        "optional": _is_optional(fi.field_type),
        "default": _safe_default(fi.default),
        "meta": fi.meta.to_dict() if fi.meta is not None else None,
        "category": fi.category,
    }
    if d["type"] == "literal":
        unwrapped = fi.field_type
        if get_origin(unwrapped) is not Literal:
            non_none = [a for a in get_args(unwrapped) if a is not type(None)]
            if len(non_none) == 1:
                unwrapped = non_none[0]
        d["choices"] = list(get_args(unwrapped))
    return d


def _port_dict(port: Any) -> dict[str, Any]:
    return {
        "name": port.name,
        "dtype": port.dtype,
        "optional": getattr(port, "optional", False),
        "shape": getattr(port, "shape", ""),
    }


def _local_entries() -> list[Any]:
    """Discover(Plugins/) в ЭТОМ процессе -> список PluginEntry (эталон для parity)."""
    from multiprocess_framework.modules.app_module import discover as app_discover
    from multiprocess_framework.modules.process_module.plugins.registry import (
        PluginRegistry,
    )

    plugins_dir = _repo_root() / "Plugins"
    app_discover(plugin_paths=[str(plugins_dir)], service_paths=[])
    return PluginRegistry.list()


def _build_catalog_payload(entries: list[Any]) -> dict[str, Any]:
    """Тестовая (не impl) сборка catalog.plugins-payload из PluginEntry — форма из DESIGN."""
    from multiprocess_framework.modules.registers_module.core.field_info import extract_fields

    plugins: list[dict[str, Any]] = []
    for e in entries:
        register: dict[str, Any] | None = None
        if e.register_classes:
            fields = [_field_dict(fi) for fi in extract_fields(e.name, e.register_classes[0], e.category)]
            register = {"fields": fields}
        plugins.append(
            {
                "name": e.name,
                "category": e.category,
                "description": e.description,
                "class_path": e.class_path,
                "version": e.version,
                "api_version": e.api_version,
                "requires": list(e.requires),
                "inputs": [_port_dict(p) for p in e.inputs],
                "outputs": [_port_dict(p) for p in e.outputs],
                "commands": list(getattr(e.plugin_class, "commands", {}) or {}),
                "register": register,
            }
        )
    payload_bytes = json.dumps(plugins, sort_keys=True, default=str).encode("utf-8")
    rev = hashlib.sha256(payload_bytes).hexdigest()
    return {"success": True, "rev": rev, "plugins": plugins, "failed_imports": {}}


def _envelope(result: dict[str, Any]) -> dict[str, Any]:
    """Обёртка транспорта: payload под reply['result'] (envelope-ловушка 1b.1)."""
    return {"success": True, "result": result}


def test_remote_catalog_parity_with_local() -> None:
    """Post: RemotePluginCatalog(request) даёт те же плагины/порты/поля, что локальный реестр."""
    from multiprocess_prototype.adapters.catalogs.remote_plugin_catalog import (
        RemotePluginCatalog,
    )

    entries = _local_entries()
    assert entries, "локальный discover(Plugins/) не нашёл ни одного плагина — фикстура сломана"
    payload = _build_catalog_payload(entries)

    def fake_request(command: str, args: dict) -> dict:
        assert command == "catalog.plugins"
        return _envelope(payload)

    catalog = RemotePluginCatalog(fake_request)
    by_name_local = {e.name: e for e in entries}
    by_name_wire = {p["name"]: p for p in payload["plugins"]}

    remote_specs = catalog.list_plugins()
    assert {s.name for s in remote_specs} == set(by_name_local)

    for spec in remote_specs:
        entry = by_name_local[spec.name]
        wire = by_name_wire[spec.name]

        assert spec.category == entry.category
        assert spec.class_path == entry.class_path
        assert spec.description == getattr(entry, "description", "")

        assert {(p.name, p.dtype) for p in spec.ports} == {
            (p["name"], p["dtype"]) for p in wire["inputs"] + wire["outputs"]
        }

        resolved = catalog.resolve(spec.name)
        assert resolved is not None
        wire_fields = (wire.get("register") or {}).get("fields") or []
        wire_field_set = {(f["field_name"], f["type"], tuple(f.get("choices") or ())) for f in wire_fields}
        local_field_set = {(f["field_name"], f["type"], tuple(f.get("choices") or ())) for f in wire_fields}
        # ОДНА ДОГАДКА: поля лежат в config_schema["fields"] тем же списком словарей.
        remote_fields = (resolved.config_schema or {}).get("fields") or []
        remote_field_set = {(f["field_name"], f["type"], tuple(f.get("choices") or ())) for f in remote_fields}
        assert remote_field_set == wire_field_set == local_field_set

    assert catalog.resolve("_no_such_plugin_") is None
    assert catalog.categories() == tuple(sorted({e.category for e in entries}))


def test_remote_catalog_fetches_once() -> None:
    """Post: снимок берётся РОВНО один раз при construction, а не на каждый вызов."""
    from multiprocess_prototype.adapters.catalogs.remote_plugin_catalog import (
        RemotePluginCatalog,
    )

    calls: list[tuple[str, dict]] = []
    empty_payload = {"success": True, "rev": "0" * 64, "plugins": [], "failed_imports": {}}

    def counting_request(command: str, args: dict) -> dict:
        calls.append((command, args))
        return _envelope(empty_payload)

    catalog = RemotePluginCatalog(counting_request)
    assert len(calls) == 1, f"construction должна сделать РОВНО 1 запрос, сделала {len(calls)}"

    for _ in range(3):
        catalog.list_plugins()
        catalog.resolve("anything")
        catalog.categories()

    assert len(calls) == 1, f"list/resolve/categories не должны дёргать request повторно, calls={calls}"


def test_remote_catalog_construction_fails_loud_on_error_reply_and_on_timeout_exception() -> None:
    """Post: сбой на construction -> исключение, НИКОГДА не тихий пустой каталог."""
    from multiprocess_prototype.adapters.catalogs.remote_plugin_catalog import (
        RemotePluginCatalog,
    )

    def error_reply_request(command: str, args: dict) -> dict:
        return {"success": False, "result": {"error": "boom"}}

    with pytest.raises(Exception):
        RemotePluginCatalog(error_reply_request)

    def timeout_request(command: str, args: dict) -> dict:
        raise TimeoutError("no reply from hub")

    with pytest.raises(Exception):
        RemotePluginCatalog(timeout_request)


def test_form_schema_without_plugin_code() -> None:
    """Post: RegistersManager.from_catalog + CommandCatalog.from_catalog без импорта Plugins/Services.

    Проверка — в ПОДПРОЦЕССЕ: только так честно проверяется "ни один Plugins.*/Services.*
    модуль не попал в sys.modules" — в текущем pytest-процессе они УЖЕ импортированы
    другими тестами файла (parity/discover), проверка была бы ложноположительной.
    """
    entries = _local_entries()
    assert entries, "локальный discover(Plugins/) не нашёл ни одного плагина — фикстура сломана"
    payload = _build_catalog_payload(entries)

    with tempfile.TemporaryDirectory() as tmp:
        catalog_path = Path(tmp) / "catalog.json"
        catalog_path.write_text(json.dumps(payload), encoding="utf-8")

        script = f"""
import json, sys
data = json.load(open({str(catalog_path)!r}, encoding="utf-8"))

from multiprocess_framework.modules.registers_module.core.manager import RegistersManager
from multiprocess_prototype.frontend.bridge.command_catalog import CommandCatalog


class _AllToProcessManager:
    def __init__(self, names):
        self._names = list(names)

    def get_process(self, name):
        return "ProcessManager"

    def plugins(self):
        return list(self._names)


names = [p["name"] for p in data["plugins"]]
rm = RegistersManager.from_catalog(data)
cc = CommandCatalog.from_catalog(data, _AllToProcessManager(names))

leaked = sorted(m for m in sys.modules if m.startswith("Plugins") or m.startswith("Services"))
assert not leaked, f"leaked plugin/service modules: {{leaked}}"
print("FORM_SCHEMA_OK", len(names), file=sys.stdout)
"""
        proc = subprocess.run(
            [sys.executable, "-c", script],
            cwd=str(_repo_root()),
            env={**os.environ, "PYTHONPATH": str(_repo_root())},
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert proc.returncode == 0, f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
        assert "FORM_SCHEMA_OK" in proc.stdout, f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
