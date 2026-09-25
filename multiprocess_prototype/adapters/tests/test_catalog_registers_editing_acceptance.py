# -*- coding: utf-8 -*-
"""RED-приёмка Task 1b.2b-pre: RegistersManager из ``catalog.plugins`` должен уметь РЕДАКТИРОВАНИЕ.

Независимый тестер (без implementation) — вход для 1b.2b, DESIGN зафиксирован лидом
(см. docs/reviews/2026-09-25_gui-1b.2a-lead.md §"Вход для 1b.2b"). Сегодня
``RegistersManager.from_catalog()`` (multiprocess_framework/modules/registers_module/
core/manager.py:297) заполняет ТОЛЬКО ``_fields_cache`` (для ``get_fields()``) — ни
одного экземпляра регистра не создаётся, поэтому ``register_names()``/``get_register()``/
``validate()``/``set_value()``/``set_field_value()``/``get_field_metadata()``/
``model_dump_all()`` у catalog-менеджера пустые/False. Этот файл фиксирует ЦЕЛЕВОЙ
контракт (paritet с ``from_registry``) — он ДОЛЖЕН быть красным сегодня по большинству
пунктов (см. итоговый отчёт тестера).

Импорт ``multiprocess_framework``/``multiprocess_prototype`` — на верхнем уровне модуля:
файл живёт под ``multiprocess_prototype/`` (forward-direction, ADR-120 / Правило 9
CLAUDE.md), а ``RegistersManager.from_catalog`` уже существует (Task 1b.2a) — падать
будут не импорты, а поведение методов.

ОДНА ДОГАДКА, помеченная явно (см. отчёт лиду): валидатор AC4 сравнивает ПАРИТЕТ между
catalog- и registry-менеджером, а не абсолютную корректность "invalid choice -> False".
Измерено эмпирически 2026-09-25: ``RegistersManager.validate()`` (через
``SchemaMixin.validate_field`` -> ``FieldMeta.validate_value``) проверяет ТОЛЬКО
access_level и числовой диапазон [min, max] — Literal-принадлежность НЕ проверяется
вообще, даже на живом ``from_registry``-менеджере (``rm.validate("center_crop",
"size_mode", "__not_a_choice__")`` -> ``(True, None)`` сегодня). Значит "invalid choice
-> False" — контракт, которого нет и у эталона; проверять его как абсолют было бы чужой
находкой не по адресу (Python-валидаторы явно вне контракта 1b.2b, см. DESIGN брифинга).
Вместо этого AC4 требует: catalog-менеджер после фикса ведёт себя ТОЧНО ТАК ЖЕ, как
from_registry, — включая унаследованную слабость. Если разработчик/лид сочтут иначе —
это решение по существу, не мой сломанный тест.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Literal, get_args, get_origin

import pytest

from multiprocess_framework.modules.app_module import discover as app_discover
from multiprocess_framework.modules.process_module.plugins.registry import PluginRegistry
from multiprocess_framework.modules.registers_module.core.field_info import extract_fields
from multiprocess_framework.modules.registers_module.core.manager import RegistersManager
from multiprocess_prototype.frontend.actions.handlers.field_set_handler import FieldSetHandler


def _repo_root() -> Path:
    # tests/ -> adapters -> multiprocess_prototype -> repo root
    return Path(__file__).resolve().parents[3]


def _local_entries() -> list[Any]:
    """Discover(Plugins/) в ЭТОМ процессе -> список PluginEntry (эталон для parity).

    Тот же паттерн, что ``test_remote_plugin_catalog_acceptance.py::_local_entries``.
    """
    plugins_dir = _repo_root() / "Plugins"
    app_discover(plugin_paths=[str(plugins_dir)], service_paths=[])
    return PluginRegistry.list()


def _build_catalog_payload(entries: list[Any]) -> dict[str, Any]:
    """Собрать ``catalog.plugins``-payload через РЕАЛЬНЫЙ ``FieldInfo.to_dict()``.

    Уже принятый кодек (Task 1b.2a) — не переизобретаем ``_type_tag`` вручную, как
    делал 1b.2a-файл (там кодека ещё не было). ``RegistersManager.from_catalog`` читает
    только ``name``/``category``/``register.fields`` — остальные ключи (``inputs``,
    ``commands`` и т.п.) ему не нужны.
    """
    plugins: list[dict[str, Any]] = []
    for e in entries:
        register: dict[str, Any] | None = None
        if e.register_classes:
            fields = [fi.to_dict() for fi in extract_fields(e.name, e.register_classes[0], e.category)]
            register = {"fields": fields}
        plugins.append(
            {
                "name": e.name,
                "category": e.category,
                "register": register,
            }
        )
    return {"success": True, "rev": "0" * 64, "plugins": plugins, "failed_imports": {}}


def _both_managers() -> tuple[RegistersManager, RegistersManager, list[Any]]:
    """(catalog_rm, registry_rm, entries) — единая фикстура-функция для parity-тестов."""
    entries = _local_entries()
    assert entries, "локальный discover(Plugins/) не нашёл ни одного плагина — фикстура сломана"
    payload = _build_catalog_payload(entries)
    catalog_rm = RegistersManager.from_catalog(payload)
    registry_rm = RegistersManager.from_registry(PluginRegistry)
    return catalog_rm, registry_rm, entries


def _entries_with_register(entries: list[Any]) -> list[Any]:
    return [e for e in entries if e.register_classes]


def _is_literal_of_enum(field_type: Any) -> bool:
    """True если Literal-поле содержит Enum-значения (исключено из AC2/AC4 — не наш кейс сегодня)."""
    import enum

    if get_origin(field_type) is not Literal:
        return False
    return any(isinstance(a, enum.Enum) for a in get_args(field_type))


def _is_json_safe(value: Any) -> bool:
    """True если значение — не сентинел ``PydanticUndefined`` (default_factory-поля)."""
    from pydantic_core import PydanticUndefined

    return value is not PydanticUndefined


def _type_tag_of(field_type: Any) -> str:
    """Локальный тег типа — тот же закрытый набор, что ``field_info.py::_type_tag``."""
    if field_type is bool:
        return "bool"
    if get_origin(field_type) is Literal:
        return "literal"
    return "other"


# ---------------------------------------------------------------------------
# AC1 — имена и наличие регистров
# ---------------------------------------------------------------------------


def test_ac1_names_and_registers_present() -> None:
    """Post: для каждого плагина с полями регистра catalog RM знает имя и даёт инстанс.

    Измерено 2026-09-25: 57 плагинов всего, 43 из них с ``register_classes``.
    """
    catalog_rm, registry_rm, entries = _both_managers()
    with_register = _entries_with_register(entries)
    expected_names = {e.name for e in with_register}

    assert len(expected_names) > 20, f"фикстура подозрительно мала: {len(expected_names)} плагинов с регистром"

    catalog_names = set(catalog_rm.register_names())
    registry_names = set(registry_rm.register_names())

    assert catalog_names == expected_names, (
        f"catalog RM register_names() разошёлся с ожиданием: "
        f"лишние={catalog_names - expected_names}, потеряны={expected_names - catalog_names}"
    )
    assert registry_names == expected_names, "фикстура сломана — from_registry сам не совпал с discover()"

    missing_instances = [name for name in expected_names if catalog_rm.get_register(name) is None]
    assert not missing_instances, (
        f"get_register(name) is None для: {missing_instances[:10]} (всего {len(missing_instances)})"
    )


# ---------------------------------------------------------------------------
# AC2 — паритет дефолтов (model_dump_all)
# ---------------------------------------------------------------------------


def test_ac2_defaults_parity_with_from_registry() -> None:
    """Post: catalog RM.model_dump_all() == from_registry RM.model_dump_all() (JSON mode).

    Разрешённые расхождения (СПИСОК, не молчаливый skip): поля с тегом типа
    "unsupported" и Literal-от-Enum. Измерено 2026-09-25: 0 таких полей в реальном
    наборе плагинов — список пуст сегодня, но код исключения оставлен для будущего.
    """
    catalog_rm, registry_rm, entries = _both_managers()
    with_register = _entries_with_register(entries)

    # Собираем поля-исключения: {(plugin, field_name)}
    excluded: set[tuple[str, str]] = set()
    for e in with_register:
        for fi in extract_fields(e.name, e.register_classes[0], e.category):
            tag = _type_tag_of(fi.field_type)
            if tag == "unsupported" or _is_literal_of_enum(fi.field_type):
                excluded.add((e.name, fi.field_name))

    assert excluded == set(), (
        f"ожидалось 0 исключений в реальном наборе плагинов (измерено 2026-09-25), "
        f"нашлось {len(excluded)}: {sorted(excluded)[:10]} — фикстура изменилась, пересчитать"
    )

    catalog_dump = json.loads(json.dumps(catalog_rm.model_dump_all(), default=str))
    registry_dump = json.loads(json.dumps(registry_rm.model_dump_all(), default=str))

    mismatches: list[tuple[str, str, Any, Any]] = []
    for e in with_register:
        name = e.name
        cat_fields = catalog_dump.get(name, {})
        reg_fields = registry_dump.get(name, {})
        field_names = set(reg_fields) | set(cat_fields)
        for field_name in field_names:
            if (name, field_name) in excluded:
                continue
            cat_val = cat_fields.get(field_name, "<ОТСУТСТВУЕТ>")
            reg_val = reg_fields.get(field_name, "<ОТСУТСТВУЕТ>")
            if cat_val != reg_val:
                mismatches.append((name, field_name, cat_val, reg_val))

    assert not mismatches, f"расхождения дефолтов catalog vs registry (первые 10): {mismatches[:10]}"


# ---------------------------------------------------------------------------
# AC3 — паритет min/max
# ---------------------------------------------------------------------------


def test_ac3_min_max_parity() -> None:
    """Post: validate(<min) -> False, validate(min) -> True (то же для max) на ОБОИХ менеджерах.

    Измерено 2026-09-25: 182 поля с FieldMeta.min или .max в реальном наборе плагинов.
    Литеральный нижний порог ниже измеренного значения — допускает небольшой дрейф
    фикстуры, но ловит грубую регрессию (например, если фикс перестанет строить meta).
    """
    catalog_rm, registry_rm, entries = _both_managers()
    with_register = _entries_with_register(entries)

    covered = 0
    failures: list[str] = []
    for e in with_register:
        for fi in extract_fields(e.name, e.register_classes[0], e.category):
            if fi.meta is None or (fi.meta.min is None and fi.meta.max is None):
                continue
            covered += 1
            plugin, field = e.name, fi.field_name
            if fi.meta.min is not None:
                below, at_min = fi.meta.min - 1, fi.meta.min
                for rm, label in ((catalog_rm, "catalog"), (registry_rm, "registry")):
                    ok_below, _ = rm.validate(plugin, field, below)
                    if ok_below is not False:
                        failures.append(
                            f"{label}:{plugin}.{field} validate(below_min={below!r}) -> {ok_below!r}, ожидалось False"
                        )
                    ok_at, _ = rm.validate(plugin, field, at_min)
                    if ok_at is not True:
                        failures.append(
                            f"{label}:{plugin}.{field} validate(min={at_min!r}) -> {ok_at!r}, ожидалось True"
                        )
            if fi.meta.max is not None:
                above, at_max = fi.meta.max + 1, fi.meta.max
                for rm, label in ((catalog_rm, "catalog"), (registry_rm, "registry")):
                    ok_above, _ = rm.validate(plugin, field, above)
                    if ok_above is not False:
                        failures.append(
                            f"{label}:{plugin}.{field} validate(above_max={above!r}) -> {ok_above!r}, ожидалось False"
                        )
                    ok_at, _ = rm.validate(plugin, field, at_max)
                    if ok_at is not True:
                        failures.append(
                            f"{label}:{plugin}.{field} validate(max={at_max!r}) -> {ok_at!r}, ожидалось True"
                        )

    assert covered > 150, f"измерено 182 поля с min/max 2026-09-25, сейчас {covered} — фикстура сильно изменилась"
    assert not failures, f"паритет min/max нарушен ({len(failures)} случаев), первые 10: {failures[:10]}"


# ---------------------------------------------------------------------------
# AC4 — паритет choices (Literal) — см. ОДНА ДОГАДКА в шапке файла
# ---------------------------------------------------------------------------


def test_ac4_choices_parity_with_from_registry() -> None:
    """Post: для Literal-полей catalog RM.validate(...) ДАЁТ ТОТ ЖЕ bool, что from_registry.

    Не абсолютная корректность (см. докстринг модуля — ``validate()`` не проверяет
    Literal-принадлежность даже у эталона), а паритет поведения, включая унаследованную
    слабость. Измерено 2026-09-25: 14 Literal-полей в реальном наборе плагинов, 0 из
    них — Literal-от-Enum (исключение из ТЗ сегодня не применяется, код оставлен).
    """
    catalog_rm, registry_rm, entries = _both_managers()
    with_register = _entries_with_register(entries)

    covered = 0
    mismatches: list[str] = []
    for e in with_register:
        for fi in extract_fields(e.name, e.register_classes[0], e.category):
            if get_origin(fi.field_type) is not Literal:
                continue
            if _is_literal_of_enum(fi.field_type):
                continue
            choices = get_args(fi.field_type)
            covered += 1
            plugin, field = e.name, fi.field_name
            values_to_check = list(choices) + ["__not_a_choice__"]
            for value in values_to_check:
                cat_ok, _ = catalog_rm.validate(plugin, field, value)
                reg_ok, _ = registry_rm.validate(plugin, field, value)
                if bool(cat_ok) != bool(reg_ok):
                    mismatches.append(f"{plugin}.{field} value={value!r}: catalog={cat_ok!r} vs registry={reg_ok!r}")

    assert covered > 5, f"измерено 14 Literal-полей 2026-09-25, сейчас {covered} — фикстура сильно изменилась"
    assert not mismatches, f"паритет choices нарушен ({len(mismatches)} случаев), первые 10: {mismatches[:10]}"


# ---------------------------------------------------------------------------
# AC5 — запись значения через set_value
# ---------------------------------------------------------------------------


def test_ac5_set_value_writes_and_notifies() -> None:
    """Post: set_value на catalog RM реально пишет значение и уведомляет подписчика."""
    entries = _local_entries()
    with_register = _entries_with_register(entries)
    target = next(e for e in with_register if e.name == "contour_draw")
    fields = extract_fields(target.name, target.register_classes[0], target.category)
    field = next(fi for fi in fields if fi.field_name == "color_b")
    plugin_name, field_name, value = target.name, field.field_name, 77

    payload = _build_catalog_payload(entries)
    catalog_rm = RegistersManager.from_catalog(payload)

    observed: list[tuple[str, str, Any]] = []
    catalog_rm.subscribe_all(lambda p, f, v: observed.append((p, f, v)))

    ok = catalog_rm.set_value(plugin_name, field_name, value)
    assert ok is True, f"set_value({plugin_name}, {field_name}, {value}) -> False, ожидалось True"

    reg = catalog_rm.get_register(plugin_name)
    assert reg is not None, f"get_register({plugin_name}) is None после set_value"
    assert getattr(reg, field_name) == value

    dump = catalog_rm.model_dump_all()
    assert dump.get(plugin_name, {}).get(field_name) == value

    assert observed == [(plugin_name, field_name, value)], f"subscribe_all вызван не так, как ожидалось: {observed}"


# ---------------------------------------------------------------------------
# AC6 — FieldSetHandler.apply доходит до TopologyBridge
# ---------------------------------------------------------------------------


class _RecordingBridge:
    """Локальная запись вызовов on_field_set — паттерн MockBridge из test_bridge_integration.py."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, Any]] = []

    def on_field_set(self, plugin_name: str, field_name: str, value: Any) -> bool:
        self.calls.append((plugin_name, field_name, value))
        return True


class _FieldSetAction:
    """Локальный минимальный Action — те же 4 атрибута, что читает FieldSetHandler.apply.

    Паттерн MockAction из test_bridge_integration.py (там тоже не настоящий pydantic
    Action, а лёгкий объект с нужными атрибутами) — FieldSetHandler не требует большего.
    """

    def __init__(self, register_name: str, field_name: str, value: Any) -> None:
        self.register_name = register_name
        self.field_name = field_name
        self.forward_patch = {"value": value}
        self.backward_patch = {"value": value}


def test_ac6_field_set_handler_reaches_topology_bridge() -> None:
    """Post: FieldSetHandler.apply(action, catalog_rm) -> bridge.on_field_set вызван РОВНО 1 раз."""
    entries = _local_entries()
    with_register = _entries_with_register(entries)
    target = next(e for e in with_register if e.name == "contour_draw")
    plugin_name, field_name, value = target.name, "color_b", 33

    payload = _build_catalog_payload(entries)
    catalog_rm = RegistersManager.from_catalog(payload)

    bridge = _RecordingBridge()
    handler = FieldSetHandler(topology_bridge=bridge)
    action = _FieldSetAction(plugin_name, field_name, value)

    handler.apply(action, catalog_rm)

    assert bridge.calls == [(plugin_name, field_name, value)], (
        f"bridge.on_field_set вызван {len(bridge.calls)} раз(а) с {bridge.calls}, "
        f"ожидался ровно 1 вызов с ({plugin_name!r}, {field_name!r}, {value!r})"
    )


# ---------------------------------------------------------------------------
# AC7 — паритет метаданных поля
# ---------------------------------------------------------------------------


def test_ac7_field_metadata_parity() -> None:
    """Post: get_field_metadata даёт те же min/max/unit/description на обоих менеджерах."""
    catalog_rm, registry_rm, entries = _both_managers()
    with_register = _entries_with_register(entries)

    covered = 0
    mismatches: list[str] = []
    for e in with_register:
        for fi in extract_fields(e.name, e.register_classes[0], e.category):
            if fi.meta is None:
                continue
            covered += 1
            plugin, field = e.name, fi.field_name
            cat_meta = catalog_rm.get_field_metadata(plugin, field)
            reg_meta = registry_rm.get_field_metadata(plugin, field)
            for key in ("min", "max", "unit", "description"):
                if cat_meta.get(key) != reg_meta.get(key):
                    mismatches.append(
                        f"{plugin}.{field}.{key}: catalog={cat_meta.get(key)!r} vs registry={reg_meta.get(key)!r}"
                    )

    assert covered > 100, f"фикстура с FieldMeta подозрительно мала: {covered} полей"
    assert not mismatches, f"расхождения метаданных (первые 10): {mismatches[:10]}"


# ---------------------------------------------------------------------------
# AC8 — устойчивость к повреждённому payload
# ---------------------------------------------------------------------------


def test_ac8_robustness_to_malformed_entry() -> None:
    """Post: from_catalog не падает на "unsupported"-поле и register=None; остальные — редактируемы."""
    entries = _local_entries()
    with_register = _entries_with_register(entries)
    assert len(with_register) >= 3, "нужно минимум 3 плагина с регистром для этого теста"

    payload = _build_catalog_payload(entries)
    plugins_by_name = {p["name"]: p for p in payload["plugins"]}

    broken_unsupported_name = with_register[0].name
    broken_none_name = with_register[1].name
    healthy_entry = with_register[2]
    healthy_name = healthy_entry.name
    healthy_fields = extract_fields(healthy_entry.name, healthy_entry.register_classes[0], healthy_entry.category)
    # Берём первое поле с JSON-safe дефолтом (default_factory-поля дают сентинел
    # PydanticUndefined — не годится как значение для set_value).
    healthy_field, healthy_default = next(
        (fi.field_name, fi.default) for fi in healthy_fields if _is_json_safe(fi.default)
    )

    # Малформация 1: поле с типом "unsupported" — добавлено к существующим полям плагина.
    plugins_by_name[broken_unsupported_name]["register"]["fields"].append(
        {
            "plugin_name": broken_unsupported_name,
            "field_name": "__broken_unsupported_field__",
            "type": "unsupported",
            "optional": False,
            "default": None,
            "meta": None,
            "category": with_register[0].category,
        }
    )
    # Малформация 2: register целиком None вместо {"fields": [...]}.
    plugins_by_name[broken_none_name]["register"] = None

    try:
        catalog_rm = RegistersManager.from_catalog(payload)
    except Exception as exc:  # noqa: BLE001 — фиксируем факт падения, а не тип
        pytest.fail(f"from_catalog упал на малформированном payload: {exc!r}")

    # Здоровый плагин остаётся редактируемым несмотря на соседей-калек.
    ok = catalog_rm.set_value(healthy_name, healthy_field, healthy_default)
    assert ok is True, f"set_value({healthy_name}, {healthy_field}, ...) -> False — сосед-калека сломал ДРУГОЙ плагин"


# ---------------------------------------------------------------------------
# AC9 — редактирование без plugin-кода в sys.modules
# ---------------------------------------------------------------------------


def test_ac9_editing_without_plugin_code_leak() -> None:
    """Post: from_catalog + set_value/validate в подпроцессе не тянут Plugins.*/Services.*.

    Проверка — в ПОДПРОЦЕССЕ (как в 1b.2a test_form_schema_without_plugin_code): в
    текущем pytest-процессе Plugins.* УЖЕ импортированы другими тестами файла.
    """
    entries = _local_entries()
    with_register = _entries_with_register(entries)
    target = next(e for e in with_register if e.name == "contour_draw")
    plugin_name, field_name, value = target.name, "color_b", 91

    payload = _build_catalog_payload(entries)

    with tempfile.TemporaryDirectory() as tmp:
        catalog_path = Path(tmp) / "catalog.json"
        catalog_path.write_text(json.dumps(payload), encoding="utf-8")

        script = f"""
import json, sys
data = json.load(open({str(catalog_path)!r}, encoding="utf-8"))

from multiprocess_framework.modules.registers_module.core.manager import RegistersManager

rm = RegistersManager.from_catalog(data)
ok = rm.set_value({plugin_name!r}, {field_name!r}, {value!r})
valid_ok, _ = rm.validate({plugin_name!r}, {field_name!r}, {value!r})

leaked = sorted(m for m in sys.modules if m.startswith("Plugins") or m.startswith("Services"))
assert not leaked, f"leaked plugin/service modules: {{leaked}}"
print("EDIT_WITHOUT_PLUGIN_CODE_OK", ok, valid_ok, file=sys.stdout)
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
        assert "EDIT_WITHOUT_PLUGIN_CODE_OK True True" in proc.stdout, f"stdout={proc.stdout!r} stderr={proc.stderr!r}"


# ---------------------------------------------------------------------------
# AC10 — get_fields() не сломан фиксом
# ---------------------------------------------------------------------------


def test_ac10_get_fields_unchanged() -> None:
    """Post: catalog RM.get_fields(p) == from_registry по (field_name, type-тег), для одного плагина."""
    catalog_rm, registry_rm, entries = _both_managers()
    plugin_name = "contour_draw"

    catalog_fields = catalog_rm.get_fields(plugin_name)
    registry_fields = registry_rm.get_fields(plugin_name)

    catalog_set = {(fi.field_name, _type_tag_of(fi.field_type)) for fi in catalog_fields}
    registry_set = {(fi.field_name, _type_tag_of(fi.field_type)) for fi in registry_fields}

    assert catalog_set == registry_set, f"get_fields() разошёлся: {catalog_set.symmetric_difference(registry_set)}"
