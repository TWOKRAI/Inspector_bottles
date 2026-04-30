"""test_middleware.py — Тесты для middleware pipeline (Task 4b+.1).

Проверяет:
- Базовый pipeline (пустой, один middleware, несколько)
- before_set: отклонение, модификация value
- after_set: получение Delta и context
- before_merge / after_merge
- Интеграция через StateStoreManager
"""

from __future__ import annotations

from typing import Any

import pytest
from state_store.core.delta import Delta
from state_store.manager.state_store_manager import StateStoreManager
from state_store.middleware.base import MiddlewarePipeline, StateMiddleware

# ---------------------------------------------------------------------------
# Тестовые middleware
# ---------------------------------------------------------------------------


class PassthroughMiddleware(StateMiddleware):
    """Пропускает всё без изменений. Считает вызовы."""

    def __init__(self, mw_name: str = "passthrough") -> None:
        self._name = mw_name
        self.before_set_calls: list[tuple[str, Any]] = []
        self.after_set_calls: list[Delta] = []
        self.before_merge_calls: list[tuple[str, dict]] = []
        self.after_merge_calls: list[list[Delta]] = []

    @property
    def name(self) -> str:
        return self._name

    def before_set(self, path: str, value: Any, source: str, context: dict) -> tuple[bool, Any]:
        self.before_set_calls.append((path, value))
        return True, value

    def after_set(self, delta: Delta, context: dict) -> None:
        self.after_set_calls.append(delta)

    def before_merge(self, path: str, data: dict, source: str, context: dict) -> tuple[bool, dict]:
        self.before_merge_calls.append((path, data))
        return True, data

    def after_merge(self, deltas: list[Delta], context: dict) -> None:
        self.after_merge_calls.append(deltas)


class RejectingMiddleware(StateMiddleware):
    """Отклоняет все операции set."""

    @property
    def name(self) -> str:
        return "rejector"

    def before_set(self, path: str, value: Any, source: str, context: dict) -> tuple[bool, Any]:
        context["rejection_reason"] = "rejected_by_test"
        return False, value

    def before_merge(self, path: str, data: dict, source: str, context: dict) -> tuple[bool, dict]:
        context["rejection_reason"] = "merge_rejected_by_test"
        return False, data


class ModifyingMiddleware(StateMiddleware):
    """Модифицирует value: умножает числа на 2."""

    @property
    def name(self) -> str:
        return "modifier"

    def before_set(self, path: str, value: Any, source: str, context: dict) -> tuple[bool, Any]:
        if isinstance(value, (int, float)):
            return True, value * 2
        return True, value


class ContextWriterMiddleware(StateMiddleware):
    """Пишет данные в context, чтобы after_set мог их прочитать."""

    @property
    def name(self) -> str:
        return "context_writer"

    def before_set(self, path: str, value: Any, source: str, context: dict) -> tuple[bool, Any]:
        context["before_source"] = source
        context["before_path"] = path
        return True, value

    def after_set(self, delta: Delta, context: dict) -> None:
        # Проверяем что context дошёл от before_set
        context["after_received"] = True


# ---------------------------------------------------------------------------
# Тесты MiddlewarePipeline
# ---------------------------------------------------------------------------


class TestMiddlewarePipeline:
    """Тесты для MiddlewarePipeline."""

    def test_empty_pipeline_set(self):
        """Пустой pipeline пропускает set без overhead."""
        pipeline = MiddlewarePipeline()
        proceed, value, context = pipeline.run_before_set("a.b", 42, "src")
        assert proceed is True
        assert value == 42
        assert context == {}

    def test_empty_pipeline_merge(self):
        """Пустой pipeline пропускает merge без overhead."""
        pipeline = MiddlewarePipeline()
        proceed, data, context = pipeline.run_before_merge("a", {"x": 1}, "src")
        assert proceed is True
        assert data == {"x": 1}

    def test_empty_pipeline_is_empty(self):
        """is_empty верно отражает состояние."""
        pipeline = MiddlewarePipeline()
        assert pipeline.is_empty is True
        pipeline.use(PassthroughMiddleware())
        assert pipeline.is_empty is False

    def test_single_middleware_called(self):
        """Один middleware вызывается для set."""
        pipeline = MiddlewarePipeline()
        mw = PassthroughMiddleware()
        pipeline.use(mw)

        pipeline.run_before_set("cameras.0.config.fps", 30, "gui")
        assert len(mw.before_set_calls) == 1
        assert mw.before_set_calls[0] == ("cameras.0.config.fps", 30)

    def test_middleware_order(self):
        """Middleware вызываются в порядке регистрации."""
        pipeline = MiddlewarePipeline()
        order: list[str] = []

        class First(StateMiddleware):
            @property
            def name(self) -> str:
                return "first"

            def before_set(self, path, value, source, context):
                order.append("first")
                return True, value

        class Second(StateMiddleware):
            @property
            def name(self) -> str:
                return "second"

            def before_set(self, path, value, source, context):
                order.append("second")
                return True, value

        pipeline.use(First())
        pipeline.use(Second())
        pipeline.run_before_set("x", 1, "s")

        assert order == ["first", "second"]

    def test_reject_stops_chain(self):
        """before_set с False прерывает цепочку."""
        pipeline = MiddlewarePipeline()
        second = PassthroughMiddleware("second_mw")

        pipeline.use(RejectingMiddleware())
        pipeline.use(second)

        proceed, _value, context = pipeline.run_before_set("x", 1, "s")
        assert proceed is False
        assert context["rejection_reason"] == "rejected_by_test"
        # Второй middleware НЕ вызван
        assert len(second.before_set_calls) == 0

    def test_modify_value(self):
        """before_set может модифицировать value."""
        pipeline = MiddlewarePipeline()
        pipeline.use(ModifyingMiddleware())

        proceed, value, _ctx = pipeline.run_before_set("fps", 15, "gui")
        assert proceed is True
        assert value == 30

    def test_chained_modification(self):
        """Два middleware: первый модифицирует, второй видит модифицированное."""
        pipeline = MiddlewarePipeline()
        observer = PassthroughMiddleware("observer")

        pipeline.use(ModifyingMiddleware())
        pipeline.use(observer)

        pipeline.run_before_set("fps", 10, "gui")
        # observer видит уже удвоенное значение
        assert observer.before_set_calls[0] == ("fps", 20)

    def test_after_set_receives_delta(self):
        """after_set получает финальную Delta."""
        pipeline = MiddlewarePipeline()
        mw = PassthroughMiddleware()
        pipeline.use(mw)

        delta = Delta(path="a.b", old_value=1, new_value=2, source="test")
        pipeline.run_after_set(delta, {})

        assert len(mw.after_set_calls) == 1
        assert mw.after_set_calls[0].path == "a.b"

    def test_context_shared_between_before_and_after(self):
        """context передаётся от before_set к after_set."""
        pipeline = MiddlewarePipeline()
        cw = ContextWriterMiddleware()
        pipeline.use(cw)

        proceed, _val, context = pipeline.run_before_set("p", 1, "src")
        assert context["before_source"] == "src"
        assert context["before_path"] == "p"

        delta = Delta(path="p", old_value=None, new_value=1, source="src")
        pipeline.run_after_set(delta, context)
        assert context["after_received"] is True

    def test_remove_middleware(self):
        """remove() удаляет по имени."""
        pipeline = MiddlewarePipeline()
        pipeline.use(PassthroughMiddleware("a"))
        pipeline.use(PassthroughMiddleware("b"))
        assert pipeline.remove("a") is True
        assert pipeline.remove("nonexistent") is False
        assert not pipeline.is_empty

    def test_duplicate_name_raises(self):
        """Нельзя зарегистрировать два middleware с одним именем."""
        pipeline = MiddlewarePipeline()
        pipeline.use(PassthroughMiddleware("dup"))
        with pytest.raises(ValueError, match="dup"):
            pipeline.use(PassthroughMiddleware("dup"))

    def test_merge_before_and_after(self):
        """before_merge и after_merge вызываются для merge."""
        pipeline = MiddlewarePipeline()
        mw = PassthroughMiddleware()
        pipeline.use(mw)

        proceed, data, ctx = pipeline.run_before_merge("cameras", {"fps": 30}, "gui")
        assert proceed is True

        deltas = [Delta(path="cameras.fps", old_value=25, new_value=30, source="gui")]
        pipeline.run_after_merge(deltas, ctx)
        assert len(mw.after_merge_calls) == 1

    def test_merge_reject(self):
        """before_merge с False отклоняет merge."""
        pipeline = MiddlewarePipeline()
        pipeline.use(RejectingMiddleware())

        proceed, _data, context = pipeline.run_before_merge("x", {"a": 1}, "s")
        assert proceed is False
        assert context["rejection_reason"] == "merge_rejected_by_test"

    def test_delete_before_and_after(self):
        """before_delete и after_delete работают."""
        pipeline = MiddlewarePipeline()
        mw = PassthroughMiddleware()
        pipeline.use(mw)

        proceed, ctx = pipeline.run_before_delete("a.b", "src")
        assert proceed is True

        delta = Delta(path="a.b", old_value=42, new_value=None, source="src")
        pipeline.run_after_delete(delta, ctx)
        # PassthroughMiddleware не переопределяет delete — просто проверяем что не падает


# ---------------------------------------------------------------------------
# Интеграционные тесты: StateStoreManager + Middleware
# ---------------------------------------------------------------------------


class TestStateStoreManagerMiddleware:
    """Интеграция middleware в StateStoreManager."""

    def test_use_adds_middleware(self):
        """StateStoreManager.use() добавляет middleware в pipeline."""
        mgr = StateStoreManager(initial_state={"a": 1})
        assert mgr.pipeline.is_empty
        mgr.use(PassthroughMiddleware())
        assert not mgr.pipeline.is_empty

    def test_set_through_middleware(self):
        """handle_state_set проходит через middleware."""
        mgr = StateStoreManager(initial_state={"a": 1})
        mw = PassthroughMiddleware()
        mgr.use(mw)

        result = mgr.handle_state_set({"data": {"path": "a", "value": 2, "source": "test"}})
        assert result["status"] == "ok"
        assert result["changed"] is True
        assert len(mw.before_set_calls) == 1
        assert len(mw.after_set_calls) == 1

    def test_set_rejected_by_middleware(self):
        """handle_state_set возвращает rejected при отклонении middleware."""
        mgr = StateStoreManager(initial_state={"a": 1})
        mgr.use(RejectingMiddleware())

        result = mgr.handle_state_set({"data": {"path": "a", "value": 2, "source": "test"}})
        assert result["status"] == "rejected"
        assert result["reason"] == "rejected_by_test"
        # Значение НЕ изменилось
        assert mgr.store.get("a") == 1

    def test_set_value_modified_by_middleware(self):
        """Middleware модифицирует value перед записью в TreeStore."""
        mgr = StateStoreManager(initial_state={"fps": 10})
        mgr.use(ModifyingMiddleware())

        mgr.handle_state_set({"data": {"path": "fps", "value": 15, "source": "gui"}})
        # ModifyingMiddleware удваивает числа
        assert mgr.store.get("fps") == 30

    def test_merge_through_middleware(self):
        """handle_state_merge проходит через middleware."""
        mgr = StateStoreManager(initial_state={"cam": {"fps": 25}})
        mw = PassthroughMiddleware()
        mgr.use(mw)

        result = mgr.handle_state_merge(
            {"data": {"path": "cam", "data": {"fps": 30}, "source": "gui"}}
        )
        assert result["status"] == "ok"
        assert len(mw.before_merge_calls) == 1
        assert len(mw.after_merge_calls) == 1

    def test_merge_rejected_by_middleware(self):
        """handle_state_merge возвращает rejected при отклонении."""
        mgr = StateStoreManager(initial_state={"cam": {"fps": 25}})
        mgr.use(RejectingMiddleware())

        result = mgr.handle_state_merge(
            {"data": {"path": "cam", "data": {"fps": 30}, "source": "gui"}}
        )
        assert result["status"] == "rejected"
        assert mgr.store.get("cam.fps") == 25

    def test_no_middleware_no_overhead(self):
        """Без middleware — обычное поведение (без rejected/context)."""
        mgr = StateStoreManager(initial_state={"a": 1})
        result = mgr.handle_state_set({"data": {"path": "a", "value": 2, "source": "test"}})
        assert result["status"] == "ok"
        assert result["changed"] is True
