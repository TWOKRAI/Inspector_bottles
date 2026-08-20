# -*- coding: utf-8 -*-
"""Предохранитель троттла накрывает НОВЫЙ адрес плагинной метрики (Ф1, Task 1.4).

**Чем этот тест отличается от соседей и зачем он вообще.** Уже существующие
``test_integration.py`` и ``test_rt2_config_flip_acceptance.py`` сверяют СЛОВАРЬ
правил с эталоном — поправь писателя, забудь glob, и оба останутся зелёными при
снятом предохранителе. Здесь сверяется другое: правило из НАСТОЯЩЕГО выхлопа
``build_throttle_rules()`` прогоняется ТЕМ ЖЕ матчером, которым пользуется
``ThrottleMiddleware``, против пути, который РЕАЛЬНО публикуется после Ф1.

Пара-контроль обязателен и стоит рядом: агрегат ``state.fps`` не переезжал, и
его покрытие доказывает, что пустой список у мигранта (если он вдруг случится)
означает промах глоба, а не сломанную фикстуру.
"""

from __future__ import annotations

import pytest

from multiprocess_framework.modules.state_store_module.core import match_pattern, split_pattern
from multiprocess_prototype.backend.state.manager_setup import build_throttle_rules

#: Метрики, уехавшие в поддерево писателя на Ф1 (`Plugins/sources/capture/plugin.py`).
_MIGRATED = ("capture_fps", "frame_count", "drops")


def _applicable(rules: dict[str, float], path: str) -> list[str]:
    """Паттерны из ``rules``, матчащие ``path`` — публичным матчером движка."""
    segments = tuple(path.split("."))
    return [p for p in rules if match_pattern(split_pattern(p), segments)]


class TestDefaultRulesCoverTheWriterSubtree:
    @pytest.mark.parametrize("metric", _MIGRATED)
    def test_new_plugin_path_is_covered(self, metric: str) -> None:
        rules = build_throttle_rules()
        path = f"processes.camera_0.state.plugins.capture.{metric}"
        assert _applicable(rules, path), f"предохранитель не накрывает {path!r} — правила: {sorted(rules)!r}"

    @pytest.mark.parametrize("metric", _MIGRATED)
    def test_an_unknown_writer_name_is_covered_too(self, metric: str) -> None:
        """Имя писателя в правилах не зашито — иначе новый плагин приедет голым."""
        rules = build_throttle_rules()
        path = f"processes.camera_0.state.plugins.some_future_writer_zz.{metric}"
        assert _applicable(rules, path), f"предохранитель знает только знакомых писателей: {path!r}"

    def test_control_unmigrated_aggregate_stays_covered(self) -> None:
        """Пара-контроль: ``state.fps`` не переезжал и обязан остаться покрытым."""
        rules = build_throttle_rules()
        assert _applicable(rules, "processes.camera_0.state.fps") == ["processes.**.state.fps"]

    def test_control_a_path_nobody_guards_is_not_covered(self) -> None:
        """Второй контроль: матчер не отвечает «да» на что попало.

        Без него «покрыто» доказано только положительными примерами, а
        всеядный матчер выдал бы их все.
        """
        rules = build_throttle_rules()
        assert _applicable(rules, "processes.camera_0.state.status") == []

    @pytest.mark.parametrize("metric", _MIGRATED)
    def test_the_interval_of_the_new_form_matches_the_flat_one(self, metric: str) -> None:
        """Обе формы держат ОДИН интервал — и это не косметика.

        ``detect_throttle_caps`` (``process_module/managers/telemetry_reload.py``)
        ищет правило метрики по ПОСЛЕДНЕМУ сегменту паттерна и берёт строжайшее.
        Пока интервалы равны, рапортуемый оператору потолок совпадает с
        действующим независимо от того, какую форму выберет поиск. Разойдутся —
        оператор увидит потолок с адреса, где не пишет никто.
        """
        rules = build_throttle_rules()
        flat = rules[f"processes.**.state.{metric}"]
        nested = rules[f"processes.**.state.plugins.*.{metric}"]
        assert flat == nested, (
            f"интервалы двух форм {metric} разошлись ({flat} vs {nested}) — "
            f"detect_throttle_caps начнёт рапортовать потолок мёртвого глоба"
        )
