# -*- coding: utf-8 -*-
"""A-A1-1 (ревью Ф5): ``publish: null`` на слоистом пути различим от «ключа нет».

Дефект: ``_apply_telemetry_from_layers`` брал под-секцию через ``.get("publish")``
и не отличал «ключа нет» (наследую boot) от «явный ``publish: null``» (выключить
gate). Прямой путь ``telemetry.reconfigure`` при ``publish=None`` честно шлёт
``(None, "replace")`` (снимает gate) — слоистый же делал ``deep_merge(boot, None)
== boot``, то есть пересобирал к загрузочному ВМЕСТО выключения.

Здесь механика проверяется НАПРЯМУЮ (фейковый heartbeat ловит ``reconfigure_telemetry``),
как в репро ревьюера: контракт наружу тут не читается без кода, поэтому это
hazard-тесты автора, а не независимого tester'а.
"""

from __future__ import annotations

from typing import Any, List, Optional, Tuple

import pytest

from multiprocess_framework.modules.process_module.configs.observability_layers import (
    TELEMETRY_KEY,
    ObservabilityLayers,
)
from multiprocess_framework.modules.process_module.managers.observability_reload import (
    apply_telemetry_layers,
)
from multiprocess_framework.modules.process_module.managers.telemetry_reload import (
    apply_telemetry_reconfigure,
)

BOOT = {"metrics": {"fps": {"interval_sec": 1.0}}}


class _CaptureHeartbeat:
    """Ловит вызовы ``reconfigure_telemetry(section, mode=...)`` — что уехало получателю."""

    def __init__(self) -> None:
        self.calls: List[Tuple[Any, Optional[str]]] = []

    def reconfigure_telemetry(self, section: Any, mode: Optional[str] = None) -> None:
        self.calls.append((section, mode))


def _apply(layers: ObservabilityLayers, hb: _CaptureHeartbeat, boot: Any = None) -> Any:
    return apply_telemetry_layers(
        layers,
        heartbeat=hb,
        telemetry_boot={"publish": boot} if boot is not None else None,
        origin="test",
    )


def _publish_call(hb: _CaptureHeartbeat) -> Any:
    """Значение publish, ушедшее получателю (``reconfigure_telemetry`` берёт его напрямую)."""
    assert hb.calls, "получатель не был вызван вовсе"
    section, _mode = hb.calls[-1]
    return section


class TestExplicitNullDisables:
    def test_explicit_null_over_boot_gate_disables_not_rebuilds(self) -> None:
        """Главная пара A-A1-1: ``publish: null`` поверх boot-гейта СНИМАЕТ гейт.

        До фикса уезжало ``boot`` (пересборка к загрузочному); теперь — ``None``,
        совпадая с прямым путём.
        """
        layers = ObservabilityLayers()
        layers.telemetry_owned = True
        layers.session[TELEMETRY_KEY] = {"publish": None}
        hb = _CaptureHeartbeat()
        _apply(layers, hb, boot=BOOT)
        assert _publish_call(hb) is None, "явный publish:null не снял гейт (уехал boot?)"

    def test_layered_null_matches_the_direct_path(self) -> None:
        """Слоистый и прямой путь на ``publish=None`` шлют получателю ОДНО и то же."""
        layers = ObservabilityLayers()
        layers.telemetry_owned = True
        layers.session[TELEMETRY_KEY] = {"publish": None}
        hb_layered = _CaptureHeartbeat()
        _apply(layers, hb_layered, boot=BOOT)

        hb_direct = _CaptureHeartbeat()
        apply_telemetry_reconfigure({"publish": None}, mode="replace", heartbeat=hb_direct)

        assert _publish_call(hb_layered) == _publish_call(hb_direct) is None

    def test_explicit_null_claims_ownership(self) -> None:
        """Присутствие ключа (даже со значением null) = слои владеют плоскостью."""
        layers = ObservabilityLayers()  # НЕ owned заранее
        layers.session[TELEMETRY_KEY] = {"publish": None}
        hb = _CaptureHeartbeat()
        _apply(layers, hb, boot=BOOT)
        assert layers.telemetry_owned is True
        assert _publish_call(hb) is None


class TestAbsentInheritsBoot:
    def test_absent_key_while_owned_returns_to_boot(self) -> None:
        """Ключа НЕТ, но плоскость owned (истекла правка) → возврат к загрузочному boot.

        Это второй исход, который ``.get`` сливал с явным null: «оператор снял
        ключ» (вернись к boot) ≠ «оператор выключил» (сними гейт).
        """
        layers = ObservabilityLayers()
        layers.telemetry_owned = True  # владели раньше, ключ истёк
        # session БЕЗ telemetry.publish
        hb = _CaptureHeartbeat()
        _apply(layers, hb, boot=BOOT)
        assert _publish_call(hb) == BOOT, "возврат не к загрузочной секции"

    def test_never_owned_and_absent_is_a_no_op(self) -> None:
        """Плоскости никто не касался — пересборка её не трогает вовсе."""
        layers = ObservabilityLayers()
        hb = _CaptureHeartbeat()
        out = _apply(layers, hb, boot=BOOT)
        assert hb.calls == [], "гейт тронут без единого слова слоёв"
        assert out is None or "publish" not in (out or {})


class TestNonEmptyLayersOverBoot:
    def test_non_empty_publish_merges_over_boot(self) -> None:
        """Непустой словарь publish ложится слоем ПОВЕРХ boot (метрики boot выживают)."""
        layers = ObservabilityLayers()
        layers.session[TELEMETRY_KEY] = {"publish": {"metrics": {"latency_ms": {"interval_sec": 0.2}}}}
        hb = _CaptureHeartbeat()
        _apply(layers, hb, boot=BOOT)
        got = _publish_call(hb)
        assert got["metrics"]["fps"]["interval_sec"] == 1.0, "метрика boot исчезла"
        assert got["metrics"]["latency_ms"]["interval_sec"] == 0.2, "правка слоя не легла"


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__, "-v"])
