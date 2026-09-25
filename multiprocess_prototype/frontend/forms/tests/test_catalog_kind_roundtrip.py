# -*- coding: utf-8 -*-
"""_resolve_kind roundtrip через dict-кодек FieldInfo (Task 1b.2a, ревью 1 п.3).

Для каждого register-поля из ЛОКАЛЬНОГО ``discover(Plugins/ + Services/)`` —
``_resolve_kind(fi)`` ДО == ``_resolve_kind(FieldInfo.from_dict(json.loads(json.dumps(
fi.to_dict()))))`` ПОСЛЕ полного JSON round-trip. Ревью лида измерил это вручную (0/417
расхождений на Plugins+Services) — пин числом, чтобы регрессия дала падающий тест, а
не осталась устной памятью.

Живёт в ``multiprocess_prototype/`` (не ``multiprocess_framework/``): импортирует
``_resolve_kind`` из ``frontend/forms/factory/kinds.py`` — статический импорт
prototype-кода допустим только на prototype-стороне (Правило 9 CLAUDE.md, forward
direction framework -> prototype запрещён, обратное — нет).
"""

from __future__ import annotations

import json
from pathlib import Path

from multiprocess_framework.modules.app_module import discover as app_discover
from multiprocess_framework.modules.process_module.plugins.registry import PluginRegistry
from multiprocess_framework.modules.registers_module.core.field_info import FieldInfo, extract_fields
from multiprocess_prototype.frontend.forms.factory.kinds import _resolve_kind


def _repo_root() -> Path:
    # tests/ -> forms -> frontend -> multiprocess_prototype -> repo root
    return Path(__file__).resolve().parents[4]


def test_resolve_kind_stable_across_json_roundtrip_for_all_register_fields() -> None:
    """_resolve_kind не меняется после to_dict() -> JSON -> from_dict(), по ВСЕМ полям Plugins+Services.

    Без ``PluginRegistry.clear()`` намеренно (см. соседний feedback в
    ``test_field_info_codec_hazards.py``): ``app_discover()`` после ``clear()`` не
    переоткрывает уже импортированные модули (декоратор @register_plugin выполняется
    один раз при первом import) — если этот файл идёт не первым в сессии, clear() увёл
    бы регистрацию в ноль без возможности восстановить. discover() безопасно ДОБАВЛЯЕТ
    недостающее в уже населённый реестр (register() того же класса — no-op reload).
    """
    snapshot = PluginRegistry.snapshot()
    try:
        plugins_dir = _repo_root() / "Plugins"
        services_dir = _repo_root() / "Services"
        app_discover(plugin_paths=[str(plugins_dir), str(services_dir)], service_paths=[])
        entries = PluginRegistry.list()
        assert entries, "локальный discover(Plugins/+Services/) не нашёл ни одного плагина — фикстура сломана"

        checked = 0
        mismatches: list[str] = []
        for entry in entries:
            if not entry.register_classes:
                continue
            for fi in extract_fields(entry.name, entry.register_classes[0], entry.category):
                kind_before = _resolve_kind(fi)
                roundtripped = FieldInfo.from_dict(json.loads(json.dumps(fi.to_dict())))
                kind_after = _resolve_kind(roundtripped)
                checked += 1
                if kind_before != kind_after:
                    mismatches.append(f"{fi.plugin_name}.{fi.field_name}: {kind_before!r} -> {kind_after!r}")

        # Литерал, не "> 0" (ревью 2): "> 0" остаётся зелёным, даже если discover()
        # потеряет Services/ целиком (62 плагина -> меньше, но всё ещё > 0) — пин
        # РОВНО числа делает такую потерю видимой падением теста, а не тишиной.
        # Переустановить при изменении регистров Plugins/Services (новое/удалённое поле).
        assert checked == 417, (
            f"ожидали 417 register-полей (Plugins+Services), получили {checked} — "
            f"либо discover() что-то потерял (напр. Services/), либо регистры менялись "
            f"(тогда пере-пин числа осознанно)"
        )
        assert not mismatches, f"{len(mismatches)}/{checked} расхождений kind после round-trip: {mismatches}"
    finally:
        PluginRegistry.restore(snapshot)
