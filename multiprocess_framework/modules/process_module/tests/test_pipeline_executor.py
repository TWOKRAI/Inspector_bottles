"""Тесты PipelineExecutor — chain of plugin.process() + error policy + routing."""

import queue
import threading
import time

import pytest

from multiprocess_framework.modules.process_module.generic.pipeline_executor import (
    PipelineExecutor,
)
from multiprocess_framework.modules.process_module.plugins.base import (
    ProcessModulePlugin,
    for_each,
)


# --- Тестовые плагины ---

class PassPlugin(ProcessModulePlugin):
    name = "pass"
    category = "processing"
    def configure(self, ctx): ...
    def start(self, ctx): ...


class DoublePlugin(ProcessModulePlugin):
    name = "double"
    category = "processing"
    thread_safe = True
    def configure(self, ctx): ...
    def start(self, ctx): ...

    @for_each
    def process(self, item):
        return {**item, "doubled": True}


class FailPlugin(ProcessModulePlugin):
    name = "fail"
    category = "processing"
    def configure(self, ctx): ...
    def start(self, ctx): ...

    def process(self, items):
        raise ValueError("intentional failure")


class FilterPlugin(ProcessModulePlugin):
    name = "filter"
    category = "processing"
    def configure(self, ctx): ...
    def start(self, ctx): ...

    @for_each
    def process(self, item):
        if item.get("skip"):
            return None
        return item


class TestChainExecution:
    """Линейный chain через plugin.process()."""

    def test_single_plugin(self):
        sent = []
        executor = PipelineExecutor(
            plugins=[DoublePlugin()],
            chain_targets=["gui"],
            shm_middleware=None,
            send_fn=lambda target, msg: sent.append((target, msg)),
        )
        items = [{"frame": "data", "val": 1}]
        result = executor._execute_chain(items)
        assert len(result) == 1
        assert result[0]["doubled"] is True

    def test_multiple_plugins(self):
        """Chain: filter → double."""
        plugins = [FilterPlugin(), DoublePlugin()]
        sent = []
        executor = PipelineExecutor(
            plugins=plugins,
            chain_targets=["out"],
            shm_middleware=None,
            send_fn=lambda t, m: sent.append((t, m)),
        )
        items = [{"val": 1}, {"val": 2, "skip": True}, {"val": 3}]
        result = executor._execute_chain(items)
        # filter: 2 items (skip removed), double: doubled=True
        assert len(result) == 2
        assert all(r["doubled"] for r in result)

    def test_empty_items_after_chain(self):
        """Если chain вернёт пустой list → _send_results не вызывается."""
        plugins = [FilterPlugin()]
        sent = []
        executor = PipelineExecutor(
            plugins=plugins,
            chain_targets=["out"],
            shm_middleware=None,
            send_fn=lambda t, m: sent.append((t, m)),
        )
        items = [{"skip": True}]
        result = executor._execute_chain(items)
        assert result == []


class TestRouting:
    """Routing: item['target'] override + chain_targets default (Q1)."""

    def test_chain_targets_default(self):
        """Без item['target'] → отправка в chain_targets."""
        sent = []
        executor = PipelineExecutor(
            plugins=[PassPlugin()],
            chain_targets=["proc_a", "proc_b"],
            shm_middleware=None,
            send_fn=lambda t, m: sent.append((t, m)),
        )
        executor._send_results([{"val": 1}])
        # Один item → два targets
        assert len(sent) == 2
        assert sent[0][0] == "proc_a"
        assert sent[1][0] == "proc_b"

    def test_per_item_target_override(self):
        """item['target'] → отправка в указанный target."""
        sent = []
        executor = PipelineExecutor(
            plugins=[PassPlugin()],
            chain_targets=["default_target"],
            shm_middleware=None,
            send_fn=lambda t, m: sent.append((t, m)),
        )
        executor._send_results([{"val": 1, "target": "special"}])
        assert len(sent) == 1
        assert sent[0][0] == "special"


class TestErrorPolicy:
    """Error policy (Q7): pass-through + circuit breaker."""

    def test_single_error_pass_through(self):
        """Одна ошибка → items pass-through + inspection_status=not_inspected."""
        executor = PipelineExecutor(
            plugins=[FailPlugin()],
            chain_targets=["out"],
            shm_middleware=None,
            send_fn=lambda t, m: None,
        )
        items = [{"val": 1}, {"val": 2}]
        result = executor._execute_chain(items)
        assert len(result) == 2
        assert all(r["inspection_status"] == "not_inspected" for r in result)

    def test_circuit_breaker(self):
        """N consecutive fails → plugin bypassed."""
        executor = PipelineExecutor(
            plugins=[FailPlugin()],
            chain_targets=["out"],
            shm_middleware=None,
            send_fn=lambda t, m: None,
            max_consecutive_fails=3,
        )
        # 3 вызова → circuit breaker
        for _ in range(3):
            executor._execute_chain([{"val": 1}])

        assert executor.is_bypassed("fail")

        # Следующий вызов — плагин пропущен, items pass-through без error mark
        result = executor._execute_chain([{"val": 99}])
        assert len(result) == 1
        # Нет inspection_status т.к. плагин bypassed (не critical)
        assert "inspection_status" not in result[0]

    def test_critical_plugin_bypassed_marks_suspect(self):
        """Critical plugin bypassed → items marked 'suspect'."""
        executor = PipelineExecutor(
            plugins=[FailPlugin()],
            chain_targets=["out"],
            shm_middleware=None,
            send_fn=lambda t, m: None,
            max_consecutive_fails=2,
            critical_plugins=["fail"],
        )
        # Trigger circuit breaker
        for _ in range(2):
            executor._execute_chain([{"val": 1}])

        assert executor.is_bypassed("fail")

        # Следующий вызов → suspect
        result = executor._execute_chain([{"val": 99}])
        assert result[0]["inspection_status"] == "suspect"

    def test_auto_reset(self):
        """Auto-reset после timeout."""
        executor = PipelineExecutor(
            plugins=[FailPlugin()],
            chain_targets=["out"],
            shm_middleware=None,
            send_fn=lambda t, m: None,
            max_consecutive_fails=1,
            auto_reset_sec=0.05,
        )
        executor._execute_chain([{"val": 1}])
        assert executor.is_bypassed("fail")

        time.sleep(0.08)
        executor._check_auto_reset()
        assert not executor.is_bypassed("fail")


class TestRunLoop:
    """run_loop интеграция."""

    def test_run_loop_processes_queue(self):
        """run_loop берёт items из queue и отправляет."""
        sent = []
        executor = PipelineExecutor(
            plugins=[DoublePlugin()],
            chain_targets=["out"],
            shm_middleware=None,
            send_fn=lambda t, m: sent.append((t, m)),
        )
        chain_queue = queue.Queue()
        stop_event = threading.Event()
        pause_event = threading.Event()

        chain_queue.put([{"val": 1}])
        chain_queue.put([{"val": 2}])

        # Запустить в потоке, дать обработать
        t = threading.Thread(
            target=executor.run_loop,
            args=(chain_queue, stop_event, pause_event),
        )
        t.start()
        time.sleep(0.2)
        stop_event.set()
        t.join(timeout=1)

        assert len(sent) == 2
        assert sent[0][1]["data"]["doubled"] is True
