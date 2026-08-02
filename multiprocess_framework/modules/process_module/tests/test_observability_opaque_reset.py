# -*- coding: utf-8 -*-
"""A-A1-2 (ревью Ф5): сброс РОДИТЕЛЯ не пробивает непрозрачный лист + страж R3b.

Непрозрачный лист ``telemetry.throttle`` (Task 5.10.g) хранит правила плоским
словарём, где имена-паттерны содержат точки. Opaque-защита стояла только на ТОЧНОМ
пути: ``_reset_keys_unrecorded("telemetry.throttle")`` возвращал лист атомарно, но
сброс РОДИТЕЛЯ (``config.reload {"observability_reset": ["telemetry"]}`` →
``session_reset_keys("telemetry")``) спускался внутрь и резал паттерны с точками на
ключи, которых в namespace НЕ существует.

Плюс страж R3b: ``session_set`` дотированного пути ВНУТРЬ листа мутировал его
изнутри (production-вызывающих нет, но латентно) → теперь громкий отказ.

Внутренняя механика слоёв — hazard-тесты автора; tester не звался.
"""

from __future__ import annotations

import pytest

from multiprocess_framework.modules.process_module.configs.observability_audit import (
    ACTION_RESET,
)
from multiprocess_framework.modules.process_module.configs.observability_layers import (
    TELEMETRY_THROTTLE_PATH,
    ObservabilityLayers,
)

THROTTLE_LEAF = {"processes.**.state.fps": 2.0, "keep": 5.0}


def _with_throttle_leaf() -> ObservabilityLayers:
    layers = ObservabilityLayers()
    layers.session_set(TELEMETRY_THROTTLE_PATH, dict(THROTTLE_LEAF), 0, origin="op")
    return layers


class TestResetOfParentDoesNotPierceOpaque:
    def test_reset_parent_reports_opaque_leaf_atomically(self) -> None:
        """Сброс родителя ``telemetry`` называет лист ОДНИМ ключом, а не его точками."""
        layers = _with_throttle_leaf()
        removed = layers.session_reset_keys("telemetry", origin="op")
        assert removed == (TELEMETRY_THROTTLE_PATH,), f"пробит opaque-лист: {removed}"

    def test_no_phantom_keys_in_removed(self) -> None:
        """В отчёте нет ключей, которых в namespace не существует (паттерны с точками)."""
        layers = _with_throttle_leaf()
        removed = layers.session_reset_keys("telemetry", origin="op")
        for key in removed:
            assert "processes.**" not in key, f"паттерн-с-точками просочился как ключ: {key}"

    def test_audit_record_names_the_opaque_leaf_not_its_internals(self) -> None:
        """Аудит фиксирует атомарный лист — иначе оператор ищет несуществующий ключ."""
        layers = _with_throttle_leaf()
        layers.session_reset_keys("telemetry", origin="op")
        entry = layers.audit.entries(action=ACTION_RESET)[-1]
        assert entry["keys"] == [TELEMETRY_THROTTLE_PATH]

    def test_reset_actually_removes_the_leaf(self) -> None:
        """Отчёт атомарен, но лист действительно снят (не только переименован в отчёте)."""
        layers = _with_throttle_leaf()
        layers.session_reset_keys("telemetry", origin="op")
        assert layers.session == {}

    def test_direct_reset_of_the_leaf_still_atomic(self) -> None:
        """Регресс: сброс самого листа по точному пути по-прежнему атомарен."""
        layers = _with_throttle_leaf()
        removed = layers.session_reset_keys(TELEMETRY_THROTTLE_PATH, origin="op")
        assert removed == (TELEMETRY_THROTTLE_PATH,)


class TestMixedBranchEnumeratesLegitLeavesButNotOpaque:
    def test_reset_parent_enumerates_publish_but_keeps_throttle_atomic(self) -> None:
        """Сброс родителя с ОБЕИМИ под-плоскостями: publish по листьям, throttle — целиком.

        Сильнейший страж: одна операция, два правила. publish живёт в namespace с
        честными точками (перечисляется), throttle — непрозрачен (атомарен).
        """
        layers = ObservabilityLayers()
        layers.session_set("telemetry.publish.metrics.fps.interval_sec", 0.5, 0, origin="op")
        layers.session_set(TELEMETRY_THROTTLE_PATH, {"a.b": 2.0}, 0, origin="op")
        removed = set(layers.session_reset_keys("telemetry", origin="op"))
        assert removed == {"telemetry.publish.metrics.fps.interval_sec", TELEMETRY_THROTTLE_PATH}

    def test_normal_branch_reset_still_enumerates_leaves(self) -> None:
        """Регресс: обычная (не-opaque) ветка сбрасывается по листьям, как раньше."""
        layers = ObservabilityLayers()
        layers.session_set("channels.a.enabled", False, 0, origin="op")
        layers.session_set("channels.b.enabled", False, 0, origin="op")
        removed = set(layers.session_reset_keys("channels", origin="op"))
        assert removed == {"channels.a.enabled", "channels.b.enabled"}


class TestExpiryOfParentAlsoAtomic:
    def test_expire_due_of_the_opaque_leaf_is_atomic(self) -> None:
        """Возврат по сроку тоже не режет лист (тот же _reset_keys_unrecorded)."""
        clock = [0.0]
        layers = ObservabilityLayers(clock=lambda: clock[0])
        layers.session_set(TELEMETRY_THROTTLE_PATH, dict(THROTTLE_LEAF), 10, origin="op")
        clock[0] = 11.0
        removed = layers.expire_due()
        assert removed == (TELEMETRY_THROTTLE_PATH,)


class TestGuardAgainstDottedPathIntoOpaque:
    def test_session_set_into_opaque_leaf_is_refused(self) -> None:
        """R3b: дотированный путь ВНУТРЬ листа — громкий ValueError, не тихая порча."""
        layers = ObservabilityLayers()
        with pytest.raises(ValueError, match="непрозрачн"):
            layers.session_set("telemetry.throttle.processes.**.state.fps", 5.0, 0, origin="op")

    def test_owning_the_whole_leaf_is_allowed(self) -> None:
        """Контраст: владеть листом ЦЕЛИКОМ по-прежнему можно."""
        layers = ObservabilityLayers()
        layers.session_set(TELEMETRY_THROTTLE_PATH, {"processes.**.state.fps": 2.0}, 0, origin="op")
        assert layers.session["telemetry"]["throttle"] == {"processes.**.state.fps": 2.0}

    def test_guard_does_not_corrupt_the_leaf(self) -> None:
        """После отказа лист остаётся плоским словарём, без вложенного дерева-двойника."""
        layers = ObservabilityLayers()
        layers.session_set(TELEMETRY_THROTTLE_PATH, {"processes.**.state.fps": 2.0}, 0, origin="op")
        with pytest.raises(ValueError):
            layers.session_set("telemetry.throttle.processes.**.state.fps", 5.0, 0, origin="op")
        assert layers.session["telemetry"]["throttle"] == {"processes.**.state.fps": 2.0}


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__, "-v"])
