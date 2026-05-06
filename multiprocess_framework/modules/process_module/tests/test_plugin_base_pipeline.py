"""Тесты Phase 5 расширений ProcessModulePlugin: process, produce, for_each, thread_safe."""

import pytest

from multiprocess_framework.modules.process_module.plugins.base import (
    ProcessModulePlugin,
    PluginContext,
    for_each,
)


# --- Конкретный плагин для тестов (ABC требует configure/start) ---

class DummyPlugin(ProcessModulePlugin):
    name = "dummy"
    category = "processing"

    def configure(self, ctx): ...
    def start(self, ctx): ...


class DummySourcePlugin(ProcessModulePlugin):
    name = "source_dummy"
    category = "source"

    def configure(self, ctx): ...
    def start(self, ctx): ...


class TestProcessDefault:
    """process() default — pass-through."""

    def test_pass_through(self):
        plugin = DummyPlugin()
        items = [{"frame": "a"}, {"frame": "b"}]
        result = plugin.process(items)
        assert result is items  # тот же объект, без копирования

    def test_empty_items(self):
        plugin = DummyPlugin()
        result = plugin.process([])
        assert result == []


class TestProduce:
    """produce() default — NotImplementedError."""

    def test_raises_not_implemented(self):
        plugin = DummyPlugin()
        with pytest.raises(NotImplementedError, match="dummy"):
            plugin.produce()


class TestIsSource:
    """is_source property."""

    def test_source_category(self):
        plugin = DummySourcePlugin()
        assert plugin.is_source is True

    def test_processing_category(self):
        plugin = DummyPlugin()
        assert plugin.is_source is False


class TestThreadSafe:
    """thread_safe ClassVar."""

    def test_default_false(self):
        plugin = DummyPlugin()
        assert plugin.thread_safe is False

    def test_override_true(self):
        class SafePlugin(DummyPlugin):
            thread_safe = True

        plugin = SafePlugin()
        assert plugin.thread_safe is True


class TestForEach:
    """@for_each декоратор."""

    def test_one_to_one(self):
        """dict return → 1:1."""
        class DoublePlugin(DummyPlugin):
            @for_each
            def process(self, item):
                return {**item, "doubled": True}

        plugin = DoublePlugin()
        result = plugin.process([{"x": 1}, {"x": 2}])
        assert len(result) == 2
        assert result[0] == {"x": 1, "doubled": True}
        assert result[1] == {"x": 2, "doubled": True}

    def test_one_to_many(self):
        """list return → 1:N (extend)."""
        class SplitPlugin(DummyPlugin):
            @for_each
            def process(self, item):
                return [{"part": "a", **item}, {"part": "b", **item}]

        plugin = SplitPlugin()
        result = plugin.process([{"x": 1}])
        assert len(result) == 2
        assert result[0]["part"] == "a"
        assert result[1]["part"] == "b"

    def test_filter_none(self):
        """None return → фильтрация (skip)."""
        class FilterPlugin(DummyPlugin):
            @for_each
            def process(self, item):
                if item.get("skip"):
                    return None
                return item

        plugin = FilterPlugin()
        items = [{"val": 1}, {"val": 2, "skip": True}, {"val": 3}]
        result = plugin.process(items)
        assert len(result) == 2
        assert result[0]["val"] == 1
        assert result[1]["val"] == 3

    def test_mixed_returns(self):
        """Смешанные возвраты: dict, list, None."""
        class MixedPlugin(DummyPlugin):
            @for_each
            def process(self, item):
                v = item["v"]
                if v == 0:
                    return None
                elif v == 1:
                    return {"v": v, "ok": True}
                else:
                    return [{"v": v, "copy": i} for i in range(v)]

        plugin = MixedPlugin()
        result = plugin.process([{"v": 0}, {"v": 1}, {"v": 2}])
        # v=0 → skip, v=1 → 1 item, v=2 → 2 items = total 3
        assert len(result) == 3
