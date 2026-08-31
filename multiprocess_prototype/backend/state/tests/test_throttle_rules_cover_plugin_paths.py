# -*- coding: utf-8 -*-
"""Предохранитель троттла накрывает НОВЫЙ адрес плагинной метрики (Ф1, Task 1.4).

**Чем этот файл отличается от соседей и зачем он вообще.** Уже существующие
``test_integration.py`` и ``test_rt2_config_flip_acceptance.py`` сверяют СЛОВАРЬ
правил с эталоном — поправь писателя, забудь glob, и оба останутся зелёными при
снятом предохранителе. Здесь сверяется другое: правило из НАСТОЯЩЕГО выхлопа
``build_throttle_rules`` прогоняется ТЕМ ЖЕ матчером, которым пользуется
``ThrottleMiddleware``, против пути, который РЕАЛЬНО публикуется после Ф1.

**Ред. по ревью Task 1.4 (находка 3): сторож был уже ловушки.** Он смотрел
только в ``build_throttle_rules()`` БЕЗ конфига, а ``build_throttle_rules(sys_config)``
дефолты ПОЛНОСТЬЮ ЗАМЕНЯЕТ. Воспроизведено ревьюером: раскомментированный пример
из самого ``system.yaml`` даёт 3 правила вместо 11 и НОЛЬ покрытия нового пути,
а конфиг ``{'processes.**.state.drops': 5.0}`` заставляет
``_central_rule_for_metric('drops')`` рапортовать потолок ``5.0`` с адреса, куда
после Ф1 не пишет никто. Сторож при этом был зелен. Теперь помощник принимает
СЛОВАРЬ ПРАВИЛ параметром, и покрытие проверяется по обеим плоскостям —
дефолтам и боевому конфигу.
"""

from __future__ import annotations

import pytest

from multiprocess_framework.modules.process_module.managers.telemetry_reload import (
    _central_rule_for_metric,
)
from multiprocess_framework.modules.state_store_module.core import match_pattern, split_pattern
from multiprocess_prototype.backend.config.schemas import load_system_config
from multiprocess_prototype.backend.state.manager_setup import build_throttle_rules

#: Метрики, уехавшие в поддерево писателя на Ф1 (`Plugins/sources/capture/plugin.py`).
_MIGRATED = ("capture_fps", "frame_count", "drops")

#: Закомментированный пример из ``system.yaml`` (подсекция ``telemetry.throttle``).
#: Переписан сюда ВРУЧНУЮ при чтении конфига, а не загружен из него: он там
#: закомментирован, то есть машинно недоступен, а проверить надо именно его.
_YAML_EXAMPLE = {
    "processes.**.state.fps": 1.0,
    "processes.**.state.latency_ms": 1.0,
    "processes.**.workers.*.effective_hz": 1.0,
}


def _applicable(rules: dict[str, float], path: str) -> list[str]:
    """Паттерны из ``rules``, матчащие ``path`` — публичным матчером движка."""
    segments = tuple(path.split("."))
    return [p for p in rules if match_pattern(split_pattern(p), segments)]


def _both_planes() -> list[tuple[str, dict[str, float]]]:
    """Обе плоскости, из которых реально приезжают правила троттла.

    ``build_throttle_rules(sys_config)`` — боевая дорога (``launch.py``);
    ``build_throttle_rules()`` — fallback без конфига. Сегодня подсекция
    ``telemetry.throttle`` в ``system.yaml`` закомментирована, поэтому обе дают
    одно и то же — и это ровно то, что тест обязан ПОДТВЕРЖДАТЬ, а не
    предполагать: раскомментируют её, и плоскости разойдутся.
    """
    return [
        ("дефолты (без конфига)", build_throttle_rules()),
        ("боевой system.yaml", build_throttle_rules(load_system_config())),
    ]


@pytest.mark.parametrize("plane", _both_planes(), ids=lambda x: x[0])
class TestBothPlanesCoverTheWriterSubtree:
    @pytest.mark.parametrize("metric", _MIGRATED)
    def test_new_plugin_path_is_covered(self, plane, metric: str) -> None:
        name, rules = plane
        path = f"processes.camera_0.state.plugins.capture.{metric}"
        assert _applicable(rules, path), f"[{name}] предохранитель не накрывает {path!r} — правила: {sorted(rules)!r}"

    @pytest.mark.parametrize("metric", _MIGRATED)
    def test_an_unknown_writer_name_is_covered_too(self, plane, metric: str) -> None:
        """Имя писателя в правилах не зашито — иначе новый плагин приедет голым."""
        name, rules = plane
        path = f"processes.camera_0.state.plugins.some_future_writer_zz.{metric}"
        assert _applicable(rules, path), f"[{name}] знает только знакомых писателей: {path!r}"

    def test_control_unmigrated_aggregate_stays_covered(self, plane) -> None:
        """Пара-контроль: ``state.fps`` не переезжал и обязан остаться покрытым."""
        name, rules = plane
        assert _applicable(rules, "processes.camera_0.state.fps"), f"[{name}] агрегат fps не покрыт"

    def test_control_a_path_nobody_guards_is_not_covered(self, plane) -> None:
        """Второй контроль: матчер не отвечает «да» на что попало.

        Без него «покрыто» доказано только положительными примерами, а всеядный
        матчер выдал бы их все.
        """
        name, rules = plane
        assert _applicable(rules, "processes.camera_0.state.status") == [], f"[{name}] всеядный матч"

    @pytest.mark.parametrize("metric", _MIGRATED)
    def test_the_interval_of_the_new_form_matches_the_flat_one(self, plane, metric: str) -> None:
        """Обе формы держат ОДИН интервал — и это не косметика.

        ``detect_throttle_caps`` ищет правило метрики по ПОСЛЕДНЕМУ сегменту
        паттерна и берёт строжайшее. Пока интервалы равны, рапортуемый оператору
        потолок совпадает с действующим независимо от того, какую форму выберет
        поиск. Разойдутся — оператор увидит потолок с адреса, где не пишет никто.
        """
        name, rules = plane
        flat = rules[f"processes.**.state.{metric}"]
        nested = rules[f"processes.**.state.plugins.*.{metric}"]
        assert flat == nested, (
            f"[{name}] интервалы двух форм {metric} разошлись ({flat} vs {nested}) — "
            f"detect_throttle_caps начнёт рапортовать потолок мёртвого глоба"
        )


class TestNonEmptyThrottleConfigIsATrap:
    """Ловушка, которую прежний сторож не видел: конфиг ЗАМЕНЯЕТ дефолты целиком.

    Ревью Task 1.4, находка 3. Тесты ниже ПРИШПИЛИВАЮТ ловушку, а не чинят её:
    автоматически дописывать плагинные формы в пользовательский конфиг нельзя —
    решение «заданный throttle полностью заменяет дефолты» принято осознанно
    (PC 2.1, явный контроль вместо скрытого слияния). Задача теста — сделать
    цену видимой и в коде, и в ``system.yaml``, где рядом стоит предупреждение.
    """

    @pytest.mark.parametrize("metric", _MIGRATED)
    def test_the_commented_example_from_system_yaml_leaves_the_new_path_bare(self, metric: str) -> None:
        """Раскомментируй пример из ``system.yaml`` — плагинные метрики без охраны."""
        path = f"processes.camera_0.state.plugins.capture.{metric}"
        assert _applicable(_YAML_EXAMPLE, path) == [], (
            "пример из system.yaml неожиданно покрывает новый путь — значит его "
            "уже дополнили, и предупреждение в конфиге пора снимать"
        )

    def test_control_the_same_example_does_cover_the_aggregate(self) -> None:
        """Пара-контроль: тот же пример агрегат ``state.fps`` покрывает.

        Значит пустой список выше — про промах формы адреса, а не про сломанный
        матчер или опечатку в примере.
        """
        assert _applicable(_YAML_EXAMPLE, "processes.camera_0.state.fps") == ["processes.**.state.fps"]

    def test_a_flat_only_config_makes_the_reported_ceiling_a_lie(self) -> None:
        """Конфиг только с плоской формой → рапортуется потолок мёртвого адреса.

        Это НЕ гипотеза: ``_central_rule_for_metric`` матчит по последнему
        сегменту и живого дерева не спрашивает. Литерал ``5.0`` — величина,
        которую оператор увидит как действующий потолок, притом что ни одно
        правило этого конфига не матчит реально публикуемый путь.
        """
        flat_only = {"processes.**.state.drops": 5.0}
        real_path = "processes.camera_0.state.plugins.capture.drops"

        assert _applicable(flat_only, real_path) == [], "конфиг вдруг покрывает живой путь"
        assert _central_rule_for_metric("drops", flat_only) == 5.0, (
            "рапорт потолка изменился — если detect_throttle_caps научили "
            "спрашивать живое дерево, это ПОЧИНКА: обнови ожидание и сними "
            "названный потолок в докстринге _central_rule_for_metric"
        )
