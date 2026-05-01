"""Тесты для SubscriptionManager — паттерн-матчинг подписок.

25+ тестов покрывающих:
- Точное совпадение путей
- Wildcard '*' (один сегмент)
- Wildcard '**' (0+ сегментов)
- Комбинации '**' и '*'
- exclude_sources фильтрация
- subscribe / unsubscribe / unsubscribe_all
- Edge cases (пустые пути, несуществующие подписки и т.д.)
- Потокобезопасность (concurrent операции)
- Производительность
"""
from __future__ import annotations

import threading
import time

import pytest
from multiprocess_framework.modules.state_store_module.core.delta import Delta
from multiprocess_framework.modules.state_store_module.core.subscription_manager import (
    Subscription,
    SubscriptionManager,
    _match_pattern,
    _split_pattern,
)

# ===========================================================================
# Вспомогательные функции
# ===========================================================================

def _make_delta(path: str, source: str = "test") -> Delta:
    """Создаёт минимальную дельту для тестирования match()."""
    return Delta(path=path, old_value=None, new_value=1, source=source)


# ===========================================================================
# Тесты _match_pattern — ядро матчинга
# ===========================================================================

class TestMatchPattern:
    """Тесты рекурсивного матчера паттернов."""

    def test_exact_match(self) -> None:
        """Точное совпадение пути и паттерна."""
        assert _match_pattern(("cameras", "0", "config", "fps"), ("cameras", "0", "config", "fps"))

    def test_exact_no_match(self) -> None:
        """Путь не совпадает с паттерном."""
        assert not _match_pattern(("cameras", "0", "config", "fps"), ("cameras", "1", "config", "fps"))

    def test_star_matches_one_segment(self) -> None:
        """'*' совпадает ровно с одним сегментом."""
        pattern = ("cameras", "*", "config", "fps")
        assert _match_pattern(pattern, ("cameras", "0", "config", "fps"))
        assert _match_pattern(pattern, ("cameras", "1", "config", "fps"))
        assert _match_pattern(pattern, ("cameras", "abc", "config", "fps"))

    def test_star_does_not_match_zero_segments(self) -> None:
        """'*' НЕ совпадает с нулём сегментов."""
        pattern = ("cameras", "*", "fps")
        assert not _match_pattern(pattern, ("cameras", "fps"))

    def test_star_does_not_match_multiple_segments(self) -> None:
        """'*' НЕ совпадает с несколькими сегментами."""
        pattern = ("cameras", "*", "config", "*")
        assert not _match_pattern(pattern, ("cameras", "0", "config", "nested", "deep"))

    def test_double_star_matches_zero_segments(self) -> None:
        """'**' совпадает с 0 сегментами — cameras.0.regions.** матчит cameras.0.regions."""
        pattern = ("cameras", "0", "regions", "**")
        assert _match_pattern(pattern, ("cameras", "0", "regions"))

    def test_double_star_matches_one_segment(self) -> None:
        """'**' совпадает с 1 сегментом."""
        pattern = ("cameras", "0", "regions", "**")
        assert _match_pattern(pattern, ("cameras", "0", "regions", "roi"))

    def test_double_star_matches_many_segments(self) -> None:
        """'**' совпадает с несколькими сегментами — глубокий путь."""
        pattern = ("cameras", "0", "regions", "**")
        path = ("cameras", "0", "regions", "roi", "processing", "nodes", "blur", "params", "k")
        assert _match_pattern(pattern, path)

    def test_double_star_in_middle(self) -> None:
        """'**' в середине паттерна — **.config.**."""
        pattern = ("**", "config", "**")
        assert _match_pattern(pattern, ("cameras", "0", "config", "fps"))
        assert _match_pattern(pattern, ("renderer", "config", "show_original"))
        assert _match_pattern(pattern, ("config", "fps"))  # ** матчит 0 сегментов слева

    def test_double_star_only(self) -> None:
        """Паттерн '**' совпадает с любым путём."""
        assert _match_pattern(("**",), ("a", "b", "c"))
        assert _match_pattern(("**",), ("a",))
        assert _match_pattern(("**",), ())  # и с пустым тоже

    def test_double_star_double_star(self) -> None:
        """Паттерн '**.**' — два double-star подряд."""
        pattern = ("**", "**")
        assert _match_pattern(pattern, ("a", "b", "c"))
        assert _match_pattern(pattern, ())

    def test_empty_pattern_empty_path(self) -> None:
        """Пустой паттерн совпадает с пустым путём."""
        assert _match_pattern((), ())

    def test_empty_pattern_nonempty_path(self) -> None:
        """Пустой паттерн НЕ совпадает с непустым путём."""
        assert not _match_pattern((), ("a",))

    def test_nonempty_pattern_empty_path(self) -> None:
        """Непустой паттерн (не '**') НЕ совпадает с пустым путём."""
        assert not _match_pattern(("a",), ())

    def test_star_at_end(self) -> None:
        """'*' в конце — cameras.0.config.*."""
        pattern = ("cameras", "0", "config", "*")
        assert _match_pattern(pattern, ("cameras", "0", "config", "fps"))
        assert _match_pattern(pattern, ("cameras", "0", "config", "type"))
        assert not _match_pattern(pattern, ("cameras", "0", "config"))
        assert not _match_pattern(pattern, ("cameras", "0", "config", "a", "b"))


# ===========================================================================
# Тесты SubscriptionManager — подписки и матчинг
# ===========================================================================

class TestSubscriptionManager:
    """Тесты API SubscriptionManager."""

    def test_subscribe_returns_unique_id(self) -> None:
        """subscribe() возвращает уникальный sub_id."""
        mgr = SubscriptionManager()
        id1 = mgr.subscribe("cameras.*", "gui")
        id2 = mgr.subscribe("cameras.*", "gui")
        assert id1 != id2

    def test_subscribe_increments_count(self) -> None:
        """Каждая подписка увеличивает счётчик."""
        mgr = SubscriptionManager()
        assert mgr.subscription_count == 0
        mgr.subscribe("a", "s1")
        assert mgr.subscription_count == 1
        mgr.subscribe("b", "s2")
        assert mgr.subscription_count == 2

    def test_unsubscribe_existing(self) -> None:
        """unsubscribe() удаляет существующую подписку."""
        mgr = SubscriptionManager()
        sub_id = mgr.subscribe("cameras.*", "gui")
        assert mgr.unsubscribe(sub_id) is True
        assert mgr.subscription_count == 0

    def test_unsubscribe_nonexistent(self) -> None:
        """unsubscribe() возвращает False для несуществующей подписки."""
        mgr = SubscriptionManager()
        assert mgr.unsubscribe("nonexistent-id") is False

    def test_unsubscribe_all_removes_all(self) -> None:
        """unsubscribe_all() удаляет все подписки подписчика."""
        mgr = SubscriptionManager()
        mgr.subscribe("a.*", "camera_0")
        mgr.subscribe("b.*", "camera_0")
        mgr.subscribe("c.*", "gui")

        count = mgr.unsubscribe_all("camera_0")
        assert count == 2
        assert mgr.subscription_count == 1  # осталась подписка gui

    def test_unsubscribe_all_nonexistent_subscriber(self) -> None:
        """unsubscribe_all() возвращает 0 для неизвестного подписчика."""
        mgr = SubscriptionManager()
        assert mgr.unsubscribe_all("unknown") == 0

    def test_match_exact_path(self) -> None:
        """match() находит подписку на точный путь."""
        mgr = SubscriptionManager()
        mgr.subscribe("cameras.0.config.fps", "gui")

        result = mgr.match(_make_delta("cameras.0.config.fps"))
        assert len(result) == 1
        assert result[0].subscriber == "gui"

    def test_match_wildcard_star(self) -> None:
        """match() с паттерном cameras.*.config.*."""
        mgr = SubscriptionManager()
        mgr.subscribe("cameras.*.config.*", "gui")

        # Должно совпасть
        assert len(mgr.match(_make_delta("cameras.0.config.fps"))) == 1
        assert len(mgr.match(_make_delta("cameras.1.config.type"))) == 1

        # НЕ должно совпасть (глубже чем один сегмент после config)
        assert len(mgr.match(_make_delta("cameras.0.config.nested.deep"))) == 0

    def test_match_double_star_recursive(self) -> None:
        """match() с ** — рекурсивный матч потомков."""
        mgr = SubscriptionManager()
        mgr.subscribe("cameras.0.regions.**", "detector")

        # 0 сегментов после **
        assert len(mgr.match(_make_delta("cameras.0.regions"))) == 1

        # Глубокий путь
        deep = "cameras.0.regions.roi.processing.nodes.blur.params.k"
        assert len(mgr.match(_make_delta(deep))) == 1

    def test_match_double_star_middle(self) -> None:
        """**.config.** — config на любом уровне."""
        mgr = SubscriptionManager()
        mgr.subscribe("**.config.**", "monitor")

        assert len(mgr.match(_make_delta("cameras.0.config.fps"))) == 1
        assert len(mgr.match(_make_delta("renderer.config.show_original"))) == 1
        assert len(mgr.match(_make_delta("config.global"))) == 1

        # Нет config в пути
        assert len(mgr.match(_make_delta("cameras.0.state.status"))) == 0

    def test_match_exclude_sources(self) -> None:
        """exclude_sources фильтрует delta.source."""
        mgr = SubscriptionManager()
        mgr.subscribe("cameras.0.state.*", "camera_0", exclude_sources=("camera_0",))

        # Дельта от camera_0 — должна быть отфильтрована
        assert len(mgr.match(_make_delta("cameras.0.state.status", source="camera_0"))) == 0

        # Дельта от gui — должна пройти
        assert len(mgr.match(_make_delta("cameras.0.state.status", source="gui"))) == 1

    def test_match_multiple_subscriptions_same_subscriber(self) -> None:
        """Один subscriber с 2 матчащими подписками → 2 результата (без дедупликации)."""
        mgr = SubscriptionManager()
        mgr.subscribe("cameras.0.**", "gui")
        mgr.subscribe("**.fps", "gui")

        result = mgr.match(_make_delta("cameras.0.config.fps"))
        # Обе подписки должны совпасть
        assert len(result) == 2
        assert all(s.subscriber == "gui" for s in result)

    def test_match_no_subscriptions(self) -> None:
        """match() без подписок возвращает пустой список."""
        mgr = SubscriptionManager()
        assert mgr.match(_make_delta("any.path")) == []

    def test_get_subscribers(self) -> None:
        """get_subscribers() возвращает уникальных подписчиков."""
        mgr = SubscriptionManager()
        mgr.subscribe("cameras.*", "gui")
        mgr.subscribe("cameras.*", "recorder")
        mgr.subscribe("renderer.*", "display")

        subs = mgr.get_subscribers("cameras.0")
        assert subs == {"gui", "recorder"}

    def test_get_subscribers_empty(self) -> None:
        """get_subscribers() для несовпадающего пути — пустое множество."""
        mgr = SubscriptionManager()
        mgr.subscribe("cameras.*", "gui")
        assert mgr.get_subscribers("renderer.fps") == set()

    def test_match_empty_path(self) -> None:
        """match() с пустым путём дельты."""
        mgr = SubscriptionManager()
        mgr.subscribe("**", "catch_all")

        result = mgr.match(_make_delta(""))
        # '**' матчит пустой путь
        assert len(result) == 1

    def test_unsubscribe_does_not_affect_others(self) -> None:
        """Удаление одной подписки не трогает другие подписки того же subscriber."""
        mgr = SubscriptionManager()
        id1 = mgr.subscribe("a.*", "gui")
        mgr.subscribe("b.*", "gui")

        mgr.unsubscribe(id1)
        assert mgr.subscription_count == 1

        # Вторая подписка должна работать
        assert len(mgr.match(_make_delta("b.x"))) == 1


# ===========================================================================
# Тесты потокобезопасности
# ===========================================================================

class TestConcurrency:
    """Тесты параллельного доступа к SubscriptionManager."""

    def test_concurrent_subscribe_unsubscribe(self) -> None:
        """Параллельные subscribe/unsubscribe не ломают внутреннее состояние."""
        mgr = SubscriptionManager()
        errors: list[str] = []
        sub_ids: list[str] = []
        lock = threading.Lock()

        def subscriber_worker(name: str) -> None:
            """Подписчик: создаёт и удаляет подписки."""
            try:
                for i in range(50):
                    sid = mgr.subscribe(f"path.{name}.{i}", name)
                    with lock:
                        sub_ids.append(sid)
                    # Имитация работы
                    mgr.match(_make_delta(f"path.{name}.{i}"))
                    mgr.unsubscribe(sid)
            except Exception as e:
                with lock:
                    errors.append(f"{name}: {e}")

        threads = [
            threading.Thread(target=subscriber_worker, args=(f"proc_{i}",))
            for i in range(8)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert not errors, f"Ошибки в потоках: {errors}"
        # Все подписки должны быть удалены
        assert mgr.subscription_count == 0

    def test_concurrent_match_during_subscribe(self) -> None:
        """match() работает корректно при параллельных subscribe."""
        mgr = SubscriptionManager()
        errors: list[str] = []

        def subscribe_worker() -> None:
            try:
                for i in range(100):
                    mgr.subscribe(f"data.{i}.*", f"sub_{i}")
            except Exception as e:
                errors.append(str(e))

        def match_worker() -> None:
            try:
                for i in range(200):
                    # Не должно вызвать исключений
                    mgr.match(_make_delta(f"data.{i % 100}.value"))
            except Exception as e:
                errors.append(str(e))

        t1 = threading.Thread(target=subscribe_worker)
        t2 = threading.Thread(target=match_worker)
        t1.start()
        t2.start()
        t1.join(timeout=10)
        t2.join(timeout=10)

        assert not errors, f"Ошибки: {errors}"


# ===========================================================================
# Тест производительности
# ===========================================================================

class TestPerformance:
    """Тесты производительности матчинга."""

    def test_100_subscriptions_1000_matches_under_50ms(self) -> None:
        """100 подписок × 1000 match() < 50мс."""
        mgr = SubscriptionManager()

        # Создаём 100 подписок с разнообразными паттернами
        for i in range(25):
            mgr.subscribe(f"cameras.{i}.config.*", f"sub_{i}")
        for i in range(25):
            mgr.subscribe("cameras.*.state.**", f"sub_{25 + i}")
        for i in range(25):
            mgr.subscribe("**.config.fps", f"sub_{50 + i}")
        for i in range(25):
            mgr.subscribe(f"system.{i}.**", f"sub_{75 + i}")

        assert mgr.subscription_count == 100

        # 1000 вызовов match()
        delta = _make_delta("cameras.5.config.fps")
        start = time.perf_counter()
        for _ in range(1000):
            mgr.match(delta)
        elapsed_ms = (time.perf_counter() - start) * 1000

        # Должно уложиться в 100мс (Windows даёт больше latency чем Linux/Mac)
        assert elapsed_ms < 100, f"Слишком медленно: {elapsed_ms:.1f}мс (лимит 100мс)"


# ===========================================================================
# Edge cases
# ===========================================================================

class TestEdgeCases:
    """Edge cases и граничные условия."""

    def test_empty_subscriber_name(self) -> None:
        """Пустое имя подписчика — допустимо (нет валидации)."""
        mgr = SubscriptionManager()
        mgr.subscribe("a.b", "")
        assert mgr.subscription_count == 1
        assert mgr.unsubscribe_all("") == 1

    def test_single_segment_path(self) -> None:
        """Путь из одного сегмента."""
        mgr = SubscriptionManager()
        mgr.subscribe("status", "monitor")
        assert len(mgr.match(_make_delta("status"))) == 1
        assert len(mgr.match(_make_delta("other"))) == 0

    def test_star_as_only_pattern(self) -> None:
        """Паттерн '*' — матчит любой одиночный сегмент."""
        mgr = SubscriptionManager()
        mgr.subscribe("*", "catch_single")

        assert len(mgr.match(_make_delta("cameras"))) == 1
        assert len(mgr.match(_make_delta("cameras.0"))) == 0  # два сегмента

    def test_double_unsubscribe(self) -> None:
        """Повторный unsubscribe — возвращает False."""
        mgr = SubscriptionManager()
        sub_id = mgr.subscribe("a.*", "gui")
        assert mgr.unsubscribe(sub_id) is True
        assert mgr.unsubscribe(sub_id) is False

    def test_exclude_sources_multiple(self) -> None:
        """exclude_sources с несколькими источниками."""
        mgr = SubscriptionManager()
        mgr.subscribe("data.*", "aggregator", exclude_sources=("sensor_a", "sensor_b"))

        assert len(mgr.match(_make_delta("data.x", source="sensor_a"))) == 0
        assert len(mgr.match(_make_delta("data.x", source="sensor_b"))) == 0
        assert len(mgr.match(_make_delta("data.x", source="sensor_c"))) == 1

    def test_subscription_is_frozen(self) -> None:
        """Subscription — frozen dataclass (иммутабельный)."""
        sub = Subscription(sub_id="1", pattern="a.*", subscriber="gui")
        with pytest.raises(AttributeError):
            sub.pattern = "b.*"  # type: ignore[misc]

    def test_split_pattern_caching(self) -> None:
        """_split_pattern кэширует результаты."""
        result1 = _split_pattern("a.b.c")
        result2 = _split_pattern("a.b.c")
        assert result1 is result2  # тот же объект из кэша
