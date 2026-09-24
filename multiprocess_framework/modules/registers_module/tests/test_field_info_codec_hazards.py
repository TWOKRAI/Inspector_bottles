# -*- coding: utf-8 -*-
"""Hazard-тесты автора (Task 1b.2a): границы dict-кодека FieldInfo/FieldMeta.

Правило проекта (.claude/CLAUDE.md, «Test authorship»): автор пишет тесты на ВНУТРЕННИЕ
опасности механизма — то, что видно только из его собственной реализации, а не из
acceptance-контракта. Независимый RED-набор (см. соседний
``test_field_info_codec_acceptance.py``) проверяет контракт с чистого листа; здесь —
что именно может сломаться в закрытом наборе тегов и в rev-хэше хаб-команды.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal, Optional

from multiprocess_framework.modules.registers_module.core.field_info import FieldInfo


def test_optional_literal_roundtrip_keeps_both_optional_and_choices() -> None:
    """Optional[Literal[...]] — снятие Optional и восстановление choices не должны терять друг друга.

    Опасность механизма: _unwrap_optional снимает Optional ДО вычисления tag, поэтому
    легко перепутать порядок и потерять либо optional=True, либо сам Literal.
    """
    fi = FieldInfo(
        plugin_name="p",
        field_name="f",
        field_type=Optional[Literal["a", "b", "c"]],
        default="a",
        meta=None,
        category="c",
    )
    d = fi.to_dict()
    assert d["type"] == "literal"
    assert d["optional"] is True
    assert d["choices"] == ["a", "b", "c"]

    restored = FieldInfo.from_dict(d)
    assert restored.field_type == Optional[Literal["a", "b", "c"]]

    d_again = restored.to_dict()
    assert d_again["type"] == "literal"
    assert d_again["optional"] is True
    assert d_again["choices"] == ["a", "b", "c"]


def test_tuple3int_default_survives_json_as_list_and_returns_as_tuple() -> None:
    """default=(255, 0, 0) -> JSON list на границе -> tuple снова после from_dict.

    Опасность механизма: json.dumps/json.loads не различает list/tuple — если to_dict()
    не конвертирует явно, roundtripped-словарь (после json round-trip) разойдётся с
    оригинальным d (list != tuple), а from_dict() без явной конвертации вернёт список
    там, где вызывающий код (CardsFieldFactory) ждёт tuple[int, int, int].
    """
    fi = FieldInfo(
        plugin_name="p",
        field_name="f",
        field_type=tuple[int, int, int],
        default=(255, 0, 0),
        meta=None,
        category="c",
    )
    d = fi.to_dict()
    assert d["type"] == "tuple3int"
    assert d["default"] == [255, 0, 0]
    assert isinstance(d["default"], list)

    # JSON-safety: сериализация -> десериализация не меняет значение.
    assert json.loads(json.dumps(d)) == d

    restored = FieldInfo.from_dict(d)
    assert restored.default == (255, 0, 0)
    assert isinstance(restored.default, tuple)


def _hazard_plugin(name: str, register_cls: type) -> type:
    """Собрать минимальный ProcessModulePlugin-класс с заданным register_class.

    ``type()``, а не class-тело: нужны РАЗНЫЕ объекты-классы между вызовами
    ``_build_real_payload`` (PluginRegistry.register() бросает ValueError на
    перерегистрацию того же имени ДРУГИМ классом без предварительного clear()).
    """
    from multiprocess_framework.modules.process_module.plugins.base import ProcessModulePlugin

    return type(
        f"_HazardPlugin_{name}",
        (ProcessModulePlugin,),
        {
            "name": name,
            "category": "processing",
            "commands": {},
            "register_class": register_cls,
            "configure": lambda self, ctx: None,
        },
    )


def _build_real_payload(plugins: list[tuple[str, type]]) -> dict:
    """Зарегистрировать плагины и вызвать РЕАЛЬНЫЙ _cmd_catalog_plugins (не копию формулы).

    Находка break-injection лида (I9, ``rev = uuid4().hex``): предыдущая версия этого
    теста пересчитывала sha256 своей собственной копией формулы и ни разу не звала
    хендлер — инъекция в хендлер оставалась GREEN. Здесь — только реальный
    ``BuiltinCommands._cmd_catalog_plugins``.
    """
    from multiprocess_framework.modules.process_module.commands.builtin_commands import BuiltinCommands
    from multiprocess_framework.modules.process_module.plugins.registry import PluginRegistry
    from multiprocess_framework.modules.process_module.plugins.testing import MockProcessServices

    PluginRegistry.clear()
    for name, register_cls in plugins:
        PluginRegistry.register(name, _hazard_plugin(name, register_cls), category="processing")

    services = MockProcessServices(name="hazard_rev_test")
    cm = BuiltinCommands(services)
    return cm._cmd_catalog_plugins()


def test_rev_stable_across_two_calls_and_changes_on_field_default_change() -> None:
    """rev РЕАЛЬНОГО хендлера — не зависит от порядка регистрации, чувствителен к default.

    Опасность механизма: rev строится как sha256(json.dumps(payload, sort_keys=True))
    из PluginRegistry.list() СОРТИРОВАННОГО по имени в хендлере — если сортировка списка
    ИЛИ ``sort_keys=True`` пропадёт, rev станет зависеть от порядка РЕГИСТРАЦИИ плагинов
    (PluginRegistry — обычный dict, сохраняет insertion order), хотя семантическое
    содержимое каталога не менялось. Поэтому здесь варьируется именно порядок
    регистрации (alpha,beta vs beta,alpha) — не порядок ключей внутри одного dict,
    который у ``FieldInfo.to_dict()`` всегда фиксирован построением, а порядок ЭЛЕМЕНТОВ
    списка ``plugins``, который зависит от PluginRegistry и от того, сортирует ли его
    хендлер перед сериализацией.
    """
    from typing import Annotated

    from multiprocess_framework.modules.data_schema_module import FieldMeta, SchemaBase
    from multiprocess_framework.modules.process_module.plugins.registry import PluginRegistry

    class _RegAlphaLow(SchemaBase):
        threshold: Annotated[int, FieldMeta("Порог")] = 1

    class _RegAlphaHigh(SchemaBase):
        threshold: Annotated[int, FieldMeta("Порог")] = 2

    class _RegBeta(SchemaBase):
        level: Annotated[int, FieldMeta("Уровень")] = 5

    # snapshot()/restore() (не clear()) — _build_real_payload делает PluginRegistry.clear()
    # внутри, а простой clear() без восстановления калечит соседние тесты этого файла:
    # app_discover() после clear() НЕ переоткрывает уже импортированные Plugins/-модули
    # (декоратор @register_plugin выполняется один раз при первом import, повторный import
    # из sys.modules — no-op), поэтому test_all_62_plugins_... следом получил бы 0 плагинов.
    snapshot = PluginRegistry.snapshot()
    try:
        payload_ab = _build_real_payload([("hazard_alpha", _RegAlphaLow), ("hazard_beta", _RegBeta)])
        payload_ba = _build_real_payload([("hazard_beta", _RegBeta), ("hazard_alpha", _RegAlphaLow)])
        assert payload_ab["rev"] == payload_ba["rev"], (
            "rev реального хендлера зависит от ПОРЯДКА РЕГИСТРАЦИИ плагинов "
            "при неизменном семантическом содержимом каталога"
        )

        payload_changed = _build_real_payload([("hazard_alpha", _RegAlphaHigh), ("hazard_beta", _RegBeta)])
        assert payload_changed["rev"] != payload_ab["rev"], (
            "изменение default одного register-поля НЕ изменило rev реального хендлера"
        )
    finally:
        PluginRegistry.restore(snapshot)


def test_all_62_plugins_catalog_payload_is_json_serializable() -> None:
    """catalog.plugins payload для ВСЕХ реальных плагинов — json.dumps без default=.

    Опасность механизма: to_dict() опирается на _safe_default() для КАЖДОГО поля;
    если хотя бы один реальный register-класс несёт default, который проскальзывает
    мимо _safe_default (например кастомный объект без repr-фоллбэка), json.dumps
    payload'а целиком упадёт TypeError на хаб-стороне — граница IPC не терпит
    ни одного non-JSON-safe значения.
    """
    from multiprocess_framework.modules.app_module import discover as app_discover
    from multiprocess_framework.modules.process_module.plugins.registry import PluginRegistry
    from multiprocess_framework.modules.registers_module.core.field_info import extract_fields

    plugins_dir = Path(__file__).resolve().parents[4] / "Plugins"
    app_discover(plugin_paths=[str(plugins_dir)], service_paths=[])
    entries = PluginRegistry.list()
    assert entries, "локальный discover(Plugins/) не нашёл ни одного плагина — фикстура сломана"

    plugins: list = []
    for entry in entries:
        register = None
        if entry.register_classes:
            fields = [fi.to_dict() for fi in extract_fields(entry.name, entry.register_classes[0], entry.category)]
            register = {"fields": fields}
        plugins.append({"name": entry.name, "category": entry.category, "register": register})

    payload = {"success": True, "plugins": plugins, "failed_imports": {}}
    # Ключевая проверка: БЕЗ default=str — если хоть одно значение не JSON-safe, здесь TypeError.
    dumped = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    assert json.loads(dumped) == payload
