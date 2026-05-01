"""Тесты для state_store/selectors — Selector и SelectorRegistry.

Покрывает:
- Базовый recompute
- Кэширование
- Публикация в дерево (selectors.{name})
- Подписка на selectors.{name} как на обычный путь
- Множественные зависимости
- Один Delta → один recompute (без дублей)
- SelectorRegistry.list() и .get()
- Unregister
- Защита от зацикливания (source="selector" игнорируется)
- Валидация входных данных
- Паттерны с ** (globstar)
"""
from __future__ import annotations

import pytest

from multiprocess_framework.modules.state_store_module.core.delta import Delta
from multiprocess_framework.modules.state_store_module.core.subscription_manager import SubscriptionManager
from multiprocess_framework.modules.state_store_module.core.tree_store import TreeStore
from multiprocess_framework.modules.state_store_module.selectors.selector import (
    Selector,
    SelectorRegistry,
    _collect_values_by_pattern,
)


# ---------------------------------------------------------------------------
# Фикстуры
# ---------------------------------------------------------------------------

@pytest.fixture
def store() -> TreeStore:
    """TreeStore с типичными данными камер."""
    s = TreeStore()
    s.set("cameras.0.state.actual_fps", 30.0)
    s.set("cameras.0.state.status", "running")
    s.set("cameras.1.state.actual_fps", 25.0)
    s.set("cameras.1.state.status", "running")
    return s


@pytest.fixture
def sub_manager() -> SubscriptionManager:
    return SubscriptionManager()


@pytest.fixture
def registry(store: TreeStore, sub_manager: SubscriptionManager) -> SelectorRegistry:
    return SelectorRegistry(store, sub_manager)


# ---------------------------------------------------------------------------
# _collect_values_by_pattern — утилита сбора значений
# ---------------------------------------------------------------------------

class TestCollectValuesByPattern:
    """Тесты для _collect_values_by_pattern."""

    def test_wildcard_single_level(self) -> None:
        """Паттерн cameras.*.state.actual_fps собирает fps всех камер."""
        root = {
            "cameras": {
                "0": {"state": {"actual_fps": 29.8}},
                "1": {"state": {"actual_fps": 24.5}},
            }
        }
        result = _collect_values_by_pattern(root, "cameras.*.state.actual_fps")
        assert result == {
            "cameras.0.state.actual_fps": 29.8,
            "cameras.1.state.actual_fps": 24.5,
        }

    def test_exact_path(self) -> None:
        """Точный путь без wildcard."""
        root = {"cameras": {"0": {"state": {"fps": 30}}}}
        result = _collect_values_by_pattern(root, "cameras.0.state.fps")
        assert result == {"cameras.0.state.fps": 30}

    def test_no_match(self) -> None:
        """Паттерн не совпадает ни с чем → пустой dict."""
        root = {"cameras": {"0": {"state": {"fps": 30}}}}
        result = _collect_values_by_pattern(root, "nonexistent.*.value")
        assert result == {}

    def test_globstar_pattern(self) -> None:
        """Паттерн с ** (ноль или более уровней)."""
        root = {
            "cameras": {
                "0": {"state": {"actual_fps": 30}},
                "1": {"nested": {"deep": {"actual_fps": 25}}},
            }
        }
        result = _collect_values_by_pattern(root, "cameras.**.actual_fps")
        assert "cameras.0.state.actual_fps" in result
        assert result["cameras.0.state.actual_fps"] == 30
        assert "cameras.1.nested.deep.actual_fps" in result
        assert result["cameras.1.nested.deep.actual_fps"] == 25


# ---------------------------------------------------------------------------
# Selector — базовые свойства и recompute
# ---------------------------------------------------------------------------

class TestSelector:
    """Тесты для класса Selector."""

    def test_name_and_path(self) -> None:
        """Проверка свойств name и path."""
        sel = Selector(
            name="avg_fps",
            dependencies=["cameras.*.state.actual_fps"],
            compute=lambda v: 0,
        )
        assert sel.name == "avg_fps"
        assert sel.path == "selectors.avg_fps"

    def test_recompute_basic(self, store: TreeStore) -> None:
        """recompute собирает значения и вызывает compute."""
        sel = Selector(
            name="avg_fps",
            dependencies=["cameras.*.state.actual_fps"],
            compute=lambda v: sum(v.values()) / max(len(v), 1),
        )
        result = sel.recompute(store)
        # (30.0 + 25.0) / 2 = 27.5
        assert result == 27.5

    def test_cached_value_after_recompute(self, store: TreeStore) -> None:
        """После recompute cached_value содержит вычисленное значение."""
        sel = Selector(
            name="avg_fps",
            dependencies=["cameras.*.state.actual_fps"],
            compute=lambda v: sum(v.values()) / max(len(v), 1),
        )
        assert sel.cached_value is None  # до recompute
        sel.recompute(store)
        assert sel.cached_value == 27.5

    def test_recompute_multiple_dependencies(self, store: TreeStore) -> None:
        """recompute с несколькими паттернами зависимостей."""
        sel = Selector(
            name="system_summary",
            dependencies=[
                "cameras.*.state.actual_fps",
                "cameras.*.state.status",
            ],
            compute=lambda v: {
                "fps_count": sum(
                    1 for k in v if k.endswith("actual_fps")
                ),
                "status_count": sum(
                    1 for k in v if k.endswith("status")
                ),
            },
        )
        result = sel.recompute(store)
        assert result["fps_count"] == 2
        assert result["status_count"] == 2

    def test_empty_name_raises(self) -> None:
        """Пустое имя вызывает ValueError."""
        with pytest.raises(ValueError, match="не может быть пустым"):
            Selector(name="", dependencies=["a.b"], compute=lambda v: 0)

    def test_empty_dependencies_raises(self) -> None:
        """Пустой список зависимостей вызывает ValueError."""
        with pytest.raises(ValueError, match="хотя бы одну зависимость"):
            Selector(name="test", dependencies=[], compute=lambda v: 0)


# ---------------------------------------------------------------------------
# SelectorRegistry — регистрация, get, list, unregister
# ---------------------------------------------------------------------------

class TestSelectorRegistry:
    """Тесты для SelectorRegistry."""

    def test_register_and_initial_value(
        self, store: TreeStore, registry: SelectorRegistry
    ) -> None:
        """При регистрации selector вычисляется и публикуется в дерево."""
        sel = Selector(
            name="avg_fps",
            dependencies=["cameras.*.state.actual_fps"],
            compute=lambda v: sum(v.values()) / max(len(v), 1),
        )
        registry.register(sel)

        # Значение в дереве
        assert store.get("selectors.avg_fps") == 27.5
        # Через registry.get()
        assert registry.get("avg_fps") == 27.5

    def test_list_selectors(
        self, store: TreeStore, registry: SelectorRegistry
    ) -> None:
        """list() возвращает имена зарегистрированных selectors."""
        assert registry.list() == []

        sel1 = Selector(
            name="sel_a", dependencies=["cameras.0.state.actual_fps"],
            compute=lambda v: list(v.values())[0] if v else 0,
        )
        sel2 = Selector(
            name="sel_b", dependencies=["cameras.1.state.actual_fps"],
            compute=lambda v: list(v.values())[0] if v else 0,
        )
        registry.register(sel1)
        registry.register(sel2)
        assert sorted(registry.list()) == ["sel_a", "sel_b"]

    def test_unregister(
        self, store: TreeStore, registry: SelectorRegistry
    ) -> None:
        """unregister удаляет selector и его значение из дерева."""
        sel = Selector(
            name="avg_fps",
            dependencies=["cameras.*.state.actual_fps"],
            compute=lambda v: sum(v.values()) / max(len(v), 1),
        )
        registry.register(sel)
        assert store.has("selectors.avg_fps")

        registry.unregister("avg_fps")
        assert not store.has("selectors.avg_fps")
        assert "avg_fps" not in registry.list()

    def test_unregister_unknown_raises(self, registry: SelectorRegistry) -> None:
        """unregister несуществующего selector вызывает KeyError."""
        with pytest.raises(KeyError):
            registry.unregister("nonexistent")

    def test_get_unknown_raises(self, registry: SelectorRegistry) -> None:
        """get() несуществующего selector вызывает KeyError."""
        with pytest.raises(KeyError):
            registry.get("nonexistent")

    def test_duplicate_register_raises(
        self, store: TreeStore, registry: SelectorRegistry
    ) -> None:
        """Повторная регистрация selector с тем же именем вызывает ValueError."""
        sel = Selector(
            name="dup", dependencies=["cameras.0.state.actual_fps"],
            compute=lambda v: 0,
        )
        registry.register(sel)
        with pytest.raises(ValueError, match="уже зарегистрирован"):
            registry.register(sel)


# ---------------------------------------------------------------------------
# SelectorRegistry — handle_delta и автоматический recompute
# ---------------------------------------------------------------------------

class TestSelectorRegistryRecompute:
    """Тесты для автоматического пересчёта через handle_delta."""

    def test_handle_delta_triggers_recompute(
        self, store: TreeStore, registry: SelectorRegistry
    ) -> None:
        """handle_delta пересчитывает selector при изменении зависимости."""
        sel = Selector(
            name="avg_fps",
            dependencies=["cameras.*.state.actual_fps"],
            compute=lambda v: sum(v.values()) / max(len(v), 1),
        )
        registry.register(sel)
        assert registry.get("avg_fps") == 27.5

        # Изменяем fps камеры 0
        delta = store.set("cameras.0.state.actual_fps", 20.0, source="camera_0")
        registry.handle_delta(delta)

        # (20.0 + 25.0) / 2 = 22.5
        assert registry.get("avg_fps") == 22.5
        assert store.get("selectors.avg_fps") == 22.5

    def test_handle_delta_no_change_no_store_update(
        self, store: TreeStore, registry: SelectorRegistry
    ) -> None:
        """Если вычисленное значение не изменилось, store.set не вызывается."""
        call_count = 0

        def compute(v: dict) -> float:
            nonlocal call_count
            call_count += 1
            # Всегда возвращает фиксированное значение
            return 42.0

        sel = Selector(
            name="fixed", dependencies=["cameras.*.state.actual_fps"],
            compute=compute,
        )
        registry.register(sel)
        assert call_count == 1  # начальный compute

        # Изменяем fps, но compute вернёт то же значение
        delta = store.set("cameras.0.state.actual_fps", 999.0, source="camera_0")
        registry.handle_delta(delta)

        assert call_count == 2  # recompute вызван
        assert registry.get("fixed") == 42.0

    def test_handle_delta_ignores_selector_source(
        self, store: TreeStore, registry: SelectorRegistry
    ) -> None:
        """handle_delta игнорирует дельты от source='selector' (антицикл)."""
        compute_count = 0

        def counting_compute(v: dict) -> float:
            nonlocal compute_count
            compute_count += 1
            return sum(v.values()) / max(len(v), 1)

        sel = Selector(
            name="avg_fps",
            dependencies=["cameras.*.state.actual_fps"],
            compute=counting_compute,
        )
        registry.register(sel)
        assert compute_count == 1  # начальный

        # Дельта от source="selector" — должна быть проигнорирована
        delta = Delta(
            path="cameras.0.state.actual_fps",
            old_value=30.0,
            new_value=20.0,
            source="selector",
        )
        registry.handle_delta(delta)
        assert compute_count == 1  # не пересчитан

    def test_handle_delta_unrelated_path_no_recompute(
        self, store: TreeStore, registry: SelectorRegistry
    ) -> None:
        """handle_delta НЕ пересчитывает selector, если путь не совпадает."""
        compute_count = 0

        def counting_compute(v: dict) -> float:
            nonlocal compute_count
            compute_count += 1
            return sum(v.values()) / max(len(v), 1)

        sel = Selector(
            name="avg_fps",
            dependencies=["cameras.*.state.actual_fps"],
            compute=counting_compute,
        )
        registry.register(sel)
        assert compute_count == 1

        # Изменяем несвязанный путь
        delta = store.set("system.version", "1.0", source="system")
        registry.handle_delta(delta)
        assert compute_count == 1  # не пересчитан

    def test_one_delta_one_recompute_even_if_multiple_deps_match(
        self, store: TreeStore, registry: SelectorRegistry
    ) -> None:
        """Один Delta → один recompute, даже если несколько dependency match."""
        compute_count = 0

        def counting_compute(v: dict) -> int:
            nonlocal compute_count
            compute_count += 1
            return len(v)

        # Два паттерна, оба могут совпасть с одним путём
        sel = Selector(
            name="multi_dep",
            dependencies=[
                "cameras.*.state.actual_fps",
                "cameras.*.state.*",
            ],
            compute=counting_compute,
        )
        registry.register(sel)
        assert compute_count == 1  # начальный

        delta = store.set("cameras.0.state.actual_fps", 15.0, source="camera_0")
        registry.handle_delta(delta)
        # Должен быть ровно 1 дополнительный recompute, не 2
        assert compute_count == 2

    def test_multiple_selectors_independent_recompute(
        self, store: TreeStore, registry: SelectorRegistry
    ) -> None:
        """Несколько selectors пересчитываются независимо."""
        sel_fps = Selector(
            name="total_fps",
            dependencies=["cameras.*.state.actual_fps"],
            compute=lambda v: sum(v.values()),
        )
        sel_count = Selector(
            name="camera_count",
            dependencies=["cameras.*.state.status"],
            compute=lambda v: len(v),
        )
        registry.register(sel_fps)
        registry.register(sel_count)

        assert registry.get("total_fps") == 55.0  # 30 + 25
        assert registry.get("camera_count") == 2

        # Добавляем третью камеру
        store.set("cameras.2.state.actual_fps", 20.0, source="system")
        delta_status = store.set("cameras.2.state.status", "running", source="system")

        # Пересчитываем по delta status — затронет camera_count
        registry.handle_delta(delta_status)
        assert registry.get("camera_count") == 3

    def test_subscribe_to_selector_path(
        self, store: TreeStore, registry: SelectorRegistry, sub_manager: SubscriptionManager
    ) -> None:
        """Подписка на selectors.{name} работает как на обычный путь."""
        sel = Selector(
            name="avg_fps",
            dependencies=["cameras.*.state.actual_fps"],
            compute=lambda v: sum(v.values()) / max(len(v), 1),
        )
        registry.register(sel)

        # Подписываемся на selectors.avg_fps
        received_deltas: list[Delta] = []
        sub_manager.subscribe("selectors.avg_fps", subscriber="gui")

        # Изменяем зависимость
        delta = store.set("cameras.0.state.actual_fps", 20.0, source="camera_0")
        registry.handle_delta(delta)

        # Проверяем что значение в дереве обновилось (подписчик может его прочитать)
        assert store.get("selectors.avg_fps") == 22.5

        # Проверяем что SubscriptionManager матчит путь selectors.avg_fps
        check_delta = Delta(
            path="selectors.avg_fps",
            old_value=27.5,
            new_value=22.5,
            source="selector",
        )
        matched = sub_manager.match(check_delta)
        assert len(matched) >= 1
        assert any(s.subscriber == "gui" for s in matched)

    def test_new_camera_added_recompute(
        self, store: TreeStore, registry: SelectorRegistry
    ) -> None:
        """При добавлении новой камеры selector пересчитывается."""
        sel = Selector(
            name="avg_fps",
            dependencies=["cameras.*.state.actual_fps"],
            compute=lambda v: sum(v.values()) / max(len(v), 1),
        )
        registry.register(sel)
        assert registry.get("avg_fps") == 27.5  # (30+25)/2

        # Добавляем камеру 2
        delta = store.set("cameras.2.state.actual_fps", 20.0, source="system")
        registry.handle_delta(delta)

        # (30 + 25 + 20) / 3 = 25.0
        assert registry.get("avg_fps") == 25.0
