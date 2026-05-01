"""test_inspector.py — Тесты для StateInspector (DevTools).

Покрывает:
- inspect() — дерево, поддерево, скалярное значение, несуществующий путь
- subscriptions() — список активных подписок с паттернами
- history() — ring buffer, фильтрация по пути, ограничение limit
- stats() — с MetricsMiddleware и без
- summary() — краткая сводка
- record_delta() — запись в ring buffer
- Ring buffer ограничен history_size
"""
import pytest

from multiprocess_framework.modules.state_store_module.core.tree_store import TreeStore
from multiprocess_framework.modules.state_store_module.core.delta import Delta, MISSING
from multiprocess_framework.modules.state_store_module.core.subscription_manager import SubscriptionManager
from multiprocess_framework.modules.state_store_module.middleware.metrics import MetricsMiddleware
from multiprocess_framework.modules.state_store_module.devtools.inspector import StateInspector


# ---------------------------------------------------------------------------
# Фикстуры
# ---------------------------------------------------------------------------

@pytest.fixture
def store() -> TreeStore:
    """TreeStore с базовыми данными для тестов."""
    s = TreeStore()
    s.set("cameras.0.config.fps", 25, source="test")
    s.set("cameras.0.config.type", "webcam", source="test")
    s.set("cameras.0.state.status", "running", source="test")
    s.set("cameras.1.config.fps", 30, source="test")
    s.set("system.version", "1.0.0", source="test")
    return s


@pytest.fixture
def sub_manager() -> SubscriptionManager:
    """SubscriptionManager с несколькими подписками."""
    sm = SubscriptionManager()
    sm.subscribe("cameras.*.config.*", subscriber="gui")
    sm.subscribe("cameras.*.state.*", subscriber="monitor")
    sm.subscribe("system.**", subscriber="logger")
    return sm


@pytest.fixture
def metrics() -> MetricsMiddleware:
    """MetricsMiddleware с несколькими операциями."""
    m = MetricsMiddleware()
    # Симулируем несколько операций
    dummy_delta = Delta(path="x", old_value=1, new_value=2, source="gui")
    m.after_set(dummy_delta, {})
    m.after_set(dummy_delta, {})
    m.increment_rejected()
    return m


@pytest.fixture
def inspector(store, sub_manager, metrics) -> StateInspector:
    """StateInspector с полным набором зависимостей."""
    return StateInspector(store, sub_manager, metrics=metrics, history_size=10)


@pytest.fixture
def inspector_no_metrics(store, sub_manager) -> StateInspector:
    """StateInspector без MetricsMiddleware."""
    return StateInspector(store, sub_manager, metrics=None, history_size=10)


# ---------------------------------------------------------------------------
# Тесты inspect()
# ---------------------------------------------------------------------------

class TestInspect:
    def test_inspect_full_tree_returns_dict(self, inspector):
        """inspect() без аргументов возвращает полное дерево."""
        result = inspector.inspect()
        assert isinstance(result, dict)
        assert "cameras" in result
        assert "system" in result

    def test_inspect_subtree(self, inspector):
        """inspect("cameras.0") возвращает поддерево камеры 0."""
        result = inspector.inspect("cameras.0")
        assert isinstance(result, dict)
        assert "config" in result
        assert "state" in result

    def test_inspect_nested_subtree(self, inspector):
        """inspect("cameras.0.config") возвращает конфигурацию."""
        result = inspector.inspect("cameras.0.config")
        assert result == {"fps": 25, "type": "webcam"}

    def test_inspect_scalar_value(self, inspector):
        """inspect("cameras.0.config.fps") возвращает dict с последним ключом."""
        result = inspector.inspect("cameras.0.config.fps")
        assert isinstance(result, dict)
        assert result.get("fps") == 25

    def test_inspect_none_equals_full_tree(self, inspector):
        """inspect(None) эквивалентно inspect()."""
        assert inspector.inspect(None) == inspector.inspect()

    def test_inspect_nonexistent_path_raises_key_error(self, inspector):
        """inspect() для несуществующего пути пробрасывает KeyError."""
        with pytest.raises(KeyError):
            inspector.inspect("nonexistent.path.to.nowhere")


# ---------------------------------------------------------------------------
# Тесты subscriptions()
# ---------------------------------------------------------------------------

class TestSubscriptions:
    def test_subscriptions_returns_list(self, inspector):
        """subscriptions() возвращает список."""
        result = inspector.subscriptions()
        assert isinstance(result, list)

    def test_subscriptions_count(self, inspector):
        """subscriptions() возвращает все подписки."""
        result = inspector.subscriptions()
        assert len(result) == 3

    def test_subscriptions_have_required_fields(self, inspector):
        """Каждая подписка содержит pattern, subscriber, sub_id."""
        result = inspector.subscriptions()
        for sub in result:
            assert "pattern" in sub
            assert "subscriber" in sub
            assert "sub_id" in sub
            assert "exclude_sources" in sub

    def test_subscriptions_patterns_correct(self, inspector):
        """Паттерны подписок соответствуют зарегистрированным."""
        result = inspector.subscriptions()
        patterns = {s["pattern"] for s in result}
        assert "cameras.*.config.*" in patterns
        assert "cameras.*.state.*" in patterns
        assert "system.**" in patterns

    def test_subscriptions_subscribers_correct(self, inspector):
        """Подписчики соответствуют зарегистрированным."""
        result = inspector.subscriptions()
        subscribers = {s["subscriber"] for s in result}
        assert "gui" in subscribers
        assert "monitor" in subscribers
        assert "logger" in subscribers

    def test_subscriptions_empty_when_no_subs(self, store):
        """subscriptions() возвращает пустой список если нет подписок."""
        sm = SubscriptionManager()
        insp = StateInspector(store, sm)
        assert insp.subscriptions() == []


# ---------------------------------------------------------------------------
# Тесты record_delta() и history()
# ---------------------------------------------------------------------------

class TestHistory:
    def _make_delta(self, path: str, old: object, new: object, source: str = "test") -> Delta:
        return Delta(path=path, old_value=old, new_value=new, source=source)

    def test_record_delta_adds_to_history(self, inspector):
        """record_delta() добавляет запись в историю."""
        delta = self._make_delta("cameras.0.config.fps", 25, 30)
        inspector.record_delta(delta)
        result = inspector.history()
        assert len(result) == 1

    def test_history_record_fields(self, inspector):
        """История содержит все необходимые поля."""
        delta = self._make_delta("cameras.0.config.fps", 25, 30, source="gui")
        inspector.record_delta(delta)
        record = inspector.history()[0]
        assert record["path"] == "cameras.0.config.fps"
        assert record["old"] == 25
        assert record["new"] == 30
        assert record["source"] == "gui"
        assert "timestamp" in record
        assert "transaction_id" in record

    def test_history_missing_serialized(self, inspector):
        """MISSING сериализуется в строку '<MISSING>'."""
        delta = self._make_delta("new.key", MISSING, 42)
        inspector.record_delta(delta)
        record = inspector.history()[0]
        assert record["old"] == "<MISSING>"
        assert record["new"] == 42

    def test_history_ring_buffer_limit(self):
        """Ring buffer ограничен history_size."""
        store = TreeStore()
        sm = SubscriptionManager()
        insp = StateInspector(store, sm, history_size=3)

        for i in range(5):
            delta = Delta(path=f"key.{i}", old_value=i, new_value=i + 1, source="test")
            insp.record_delta(delta)

        result = insp.history()
        # Должны остаться только последние 3 записи
        assert len(result) == 3
        assert result[0]["path"] == "key.2"
        assert result[-1]["path"] == "key.4"

    def test_history_path_filter(self, inspector):
        """history(path_filter=...) фильтрует по подстроке пути."""
        inspector.record_delta(self._make_delta("cameras.0.config.fps", 25, 30))
        inspector.record_delta(self._make_delta("cameras.1.config.fps", 25, 30))
        inspector.record_delta(self._make_delta("system.version", "1.0", "1.1"))

        cameras_0 = inspector.history(path_filter="cameras.0")
        assert len(cameras_0) == 1
        assert cameras_0[0]["path"] == "cameras.0.config.fps"

        all_cameras = inspector.history(path_filter="cameras")
        assert len(all_cameras) == 2

    def test_history_limit(self, inspector):
        """history(limit=N) возвращает последние N записей."""
        for i in range(5):
            delta = Delta(path=f"key.{i}", old_value=i, new_value=i + 1, source="test")
            inspector.record_delta(delta)

        result = inspector.history(limit=2)
        assert len(result) == 2
        # Должны быть последние 2
        assert result[0]["path"] == "key.3"
        assert result[1]["path"] == "key.4"

    def test_history_empty_initially(self, inspector):
        """История пуста при инициализации."""
        assert inspector.history() == []

    def test_history_combined_filter_and_limit(self, inspector):
        """history(limit=N, path_filter=...) применяет оба ограничения."""
        for i in range(4):
            inspector.record_delta(self._make_delta(f"cameras.0.fps.{i}", i, i + 1))
        inspector.record_delta(self._make_delta("system.version", "1.0", "1.1"))

        result = inspector.history(limit=2, path_filter="cameras.0")
        assert len(result) == 2
        # Фильтрация: 4 cameras.0 записи, limit=2 → последние 2
        assert result[0]["path"] == "cameras.0.fps.2"
        assert result[1]["path"] == "cameras.0.fps.3"


# ---------------------------------------------------------------------------
# Тесты stats()
# ---------------------------------------------------------------------------

class TestStats:
    def test_stats_with_metrics(self, inspector):
        """stats() возвращает метрики если MetricsMiddleware установлен."""
        result = inspector.stats()
        assert result is not None
        assert "operations_total" in result
        assert "operations_by_source" in result
        assert "operations_rejected" in result
        assert "last_operation_time" in result

    def test_stats_without_metrics(self, inspector_no_metrics):
        """stats() возвращает None если MetricsMiddleware не установлен."""
        result = inspector_no_metrics.stats()
        assert result is None

    def test_stats_values_correct(self, inspector):
        """stats() содержит корректные значения из MetricsMiddleware."""
        result = inspector.stats()
        # В фикстуре metrics: 2 set операции + 1 rejected
        assert result["operations_total"]["set"] == 2
        assert result["operations_rejected"] == 1


# ---------------------------------------------------------------------------
# Тесты summary()
# ---------------------------------------------------------------------------

class TestSummary:
    def test_summary_returns_dict(self, inspector):
        """summary() возвращает dict."""
        result = inspector.summary()
        assert isinstance(result, dict)

    def test_summary_required_fields(self, inspector):
        """summary() содержит все необходимые поля."""
        result = inspector.summary()
        assert "tree_root_keys" in result
        assert "subscriptions_total" in result
        assert "history_size" in result
        assert "history_capacity" in result

    def test_summary_tree_root_keys(self, inspector, store):
        """tree_root_keys соответствует количеству ключей в корне дерева."""
        result = inspector.summary()
        # В фикстуре store: cameras и system = 2 ключа
        assert result["tree_root_keys"] == 2

    def test_summary_subscriptions_total(self, inspector):
        """subscriptions_total соответствует количеству активных подписок."""
        result = inspector.summary()
        assert result["subscriptions_total"] == 3

    def test_summary_history_size_updates(self, inspector):
        """history_size обновляется после record_delta()."""
        assert inspector.summary()["history_size"] == 0
        delta = Delta(path="x", old_value=1, new_value=2, source="test")
        inspector.record_delta(delta)
        assert inspector.summary()["history_size"] == 1

    def test_summary_history_capacity(self, inspector):
        """history_capacity соответствует history_size при создании."""
        result = inspector.summary()
        assert result["history_capacity"] == 10
