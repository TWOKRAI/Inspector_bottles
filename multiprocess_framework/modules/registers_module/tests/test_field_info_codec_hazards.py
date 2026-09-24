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


def test_rev_stable_across_two_calls_and_changes_on_field_default_change() -> None:
    """rev = sha256(payload без rev) — детерминирован, чувствителен к любой правке поля.

    Опасность механизма: sha256 payload'а формируется из dict с рекурсивной
    сериализацией FieldInfo — недетерминированный порядок ключей (без sort_keys) или
    забытое поле в payload сделал бы rev либо нестабильным между вызовами, либо слепым
    к реальным изменениям каталога.
    """

    def _payload(default_a: int) -> dict:
        fields = [
            FieldInfo(
                plugin_name="p", field_name="a", field_type=int, default=default_a, meta=None, category="c"
            ).to_dict(),
            FieldInfo(plugin_name="p", field_name="b", field_type=str, default="x", meta=None, category="c").to_dict(),
        ]
        return {"success": True, "plugins": [{"name": "p", "register": {"fields": fields}}], "failed_imports": {}}

    def _rev(payload: dict) -> str:
        import hashlib

        return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()

    payload_1 = _payload(default_a=1)
    rev_1a = _rev(payload_1)
    rev_1b = _rev(_payload(default_a=1))
    assert rev_1a == rev_1b, "два вызова с одинаковыми данными дали разный rev"

    rev_2 = _rev(_payload(default_a=2))
    assert rev_2 != rev_1a, "изменение одного default не изменило rev"


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
