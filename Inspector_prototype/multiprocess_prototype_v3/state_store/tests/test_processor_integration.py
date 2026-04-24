"""Интеграционные тесты: ProcessorProcess <-> StateProxy.

Проверяем что:
1. build_state_config_handlers возвращает маппинг для всех 6 полей
2. Каждый handler вызывает правильный метод сервиса
3. _on_config_changed роутит дельты к правильным обработчикам
4. _on_regions_changed вызывает rebuild_runnables один раз (transaction batching)
5. Dual-mode: register_update путь в _processing_worker НЕ удалён

Все тесты БЕЗ реальных процессов — мокаем сервис и StateProxy.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch, call

from multiprocess_prototype_v3.backend.processes.processor.commands import (
    build_state_config_handlers,
    _apply_vision_pipeline,
)


# ---------------------------------------------------------------------------
# Вспомогательные фабрики
# ---------------------------------------------------------------------------

class FakeDelta:
    """Мок Delta с path, new_value, old_value."""

    def __init__(self, path: str, new_value=None, old_value=None):
        self.path = path
        self.new_value = new_value
        self.old_value = old_value


def _make_service() -> MagicMock:
    """Создать мок ProcessorService со всеми нужными методами."""
    svc = MagicMock()
    svc.set_color_range.return_value = {"status": "ok"}
    svc.set_min_area.return_value = 500
    svc.set_max_area.return_value = 50000
    svc.resize_pool.return_value = None
    svc.rebuild_runnables.return_value = None
    return svc


def _make_on_config_changed(camera_id: int = 0):
    """Создать функцию _on_config_changed с замоканными зависимостями.

    Возвращает (callback, service_mock, handlers_dict).
    """
    svc = _make_service()
    handlers = build_state_config_handlers(svc)

    def _on_config_changed(deltas: list) -> None:
        """Реплика метода ProcessorProcess._on_config_changed для тестов."""
        prefix = f"processor.{camera_id}.config."
        for delta in deltas:
            if not delta.path.startswith(prefix):
                continue
            field = delta.path[len(prefix):]
            handler = handlers.get(field)
            if handler:
                handler(delta.new_value)

    return _on_config_changed, svc, handlers


def _make_on_regions_changed(camera_id: int = 0):
    """Создать функцию _on_regions_changed с замоканными зависимостями.

    Возвращает (callback, service_mock, state_proxy_mock).
    """
    svc = _make_service()
    state_proxy = MagicMock()

    def _on_regions_changed(deltas: list) -> None:
        """Реплика метода ProcessorProcess._on_regions_changed для тестов."""
        if not deltas:
            return
        regions = state_proxy.get_subtree(f"cameras.{camera_id}.regions")
        if regions is not None:
            pipeline_data = {"cameras": {str(camera_id): {"regions": regions}}}
            _apply_vision_pipeline(svc, pipeline_data)

    return _on_regions_changed, svc, state_proxy


# ===========================================================================
# Тесты build_state_config_handlers
# ===========================================================================

class TestBuildStateConfigHandlers:
    """Проверяем корректность маппинга build_state_config_handlers."""

    EXPECTED_KEYS = {
        "color_lower",
        "color_upper",
        "min_area",
        "max_area",
        "vision_pipeline",
        "workers_per_processor",
    }

    def test_build_state_config_handlers_keys(self):
        """build_state_config_handlers возвращает dict с ровно 6 ожидаемыми полями."""
        svc = _make_service()
        handlers = build_state_config_handlers(svc)

        assert set(handlers.keys()) == self.EXPECTED_KEYS, (
            f"Ожидались ключи {self.EXPECTED_KEYS}, получили {set(handlers.keys())}"
        )

    def test_handler_color_lower(self):
        """handler['color_lower']([0, 50, 100]) -> service.set_color_range(lower=[0, 50, 100])."""
        svc = _make_service()
        handlers = build_state_config_handlers(svc)

        handlers["color_lower"]([0, 50, 100])

        svc.set_color_range.assert_called_once_with(lower=[0, 50, 100])

    def test_handler_color_upper(self):
        """handler['color_upper']([100, 200, 255]) -> service.set_color_range(upper=[100, 200, 255])."""
        svc = _make_service()
        handlers = build_state_config_handlers(svc)

        handlers["color_upper"]([100, 200, 255])

        svc.set_color_range.assert_called_once_with(upper=[100, 200, 255])

    def test_handler_min_area(self):
        """handler['min_area'](300) -> service.set_min_area(300)."""
        svc = _make_service()
        handlers = build_state_config_handlers(svc)

        handlers["min_area"](300)

        svc.set_min_area.assert_called_once_with(300)

    def test_handler_max_area(self):
        """handler['max_area'](60000) -> service.set_max_area(60000)."""
        svc = _make_service()
        handlers = build_state_config_handlers(svc)

        handlers["max_area"](60000)

        svc.set_max_area.assert_called_once_with(60000)

    def test_handler_vision_pipeline(self):
        """handler['vision_pipeline'](dict) -> _apply_vision_pipeline вызывается."""
        svc = _make_service()
        handlers = build_state_config_handlers(svc)

        pipeline_data = {"cameras": {"0": {"regions": {"r1": {"nodes": {"n1": {}}}}}}}
        handlers["vision_pipeline"](pipeline_data)

        # _apply_vision_pipeline вызовет rebuild_runnables если есть nodes
        svc.rebuild_runnables.assert_called_once_with(pipeline_data)

    def test_handler_workers_per_processor(self):
        """handler['workers_per_processor'](4) -> service.resize_pool(4)."""
        svc = _make_service()
        handlers = build_state_config_handlers(svc)

        handlers["workers_per_processor"](4)

        svc.resize_pool.assert_called_once_with(4)

    def test_handler_workers_per_processor_converts_to_int(self):
        """handler['workers_per_processor']('3') -> service.resize_pool(3) (строка -> int)."""
        svc = _make_service()
        handlers = build_state_config_handlers(svc)

        handlers["workers_per_processor"]("3")

        svc.resize_pool.assert_called_once_with(3)


# ===========================================================================
# Тесты _on_config_changed
# ===========================================================================

class TestOnConfigChanged:
    """Проверяем роутинг дельт в _on_config_changed."""

    def test_on_config_changed_routes_correctly(self):
        """delta с path processor.0.config.min_area -> service.set_min_area вызван."""
        callback, svc, _ = _make_on_config_changed(camera_id=0)

        delta = FakeDelta("processor.0.config.min_area", new_value=400)
        callback([delta])

        svc.set_min_area.assert_called_once_with(400)

    def test_on_config_changed_wrong_prefix_ignored(self):
        """delta processor.1.config.min_area -> ничего (camera_id=0)."""
        callback, svc, _ = _make_on_config_changed(camera_id=0)

        delta = FakeDelta("processor.1.config.min_area", new_value=400)
        callback([delta])

        svc.set_min_area.assert_not_called()

    def test_on_config_changed_unknown_field_ignored(self):
        """delta processor.0.config.unknown_field -> ничего не вызвано."""
        callback, svc, _ = _make_on_config_changed(camera_id=0)

        delta = FakeDelta("processor.0.config.unknown_field", new_value="x")
        callback([delta])

        svc.set_color_range.assert_not_called()
        svc.set_min_area.assert_not_called()
        svc.set_max_area.assert_not_called()
        svc.resize_pool.assert_not_called()

    def test_on_config_changed_multiple_deltas(self):
        """3 дельты -> 3 вызова соответствующих обработчиков."""
        callback, svc, _ = _make_on_config_changed(camera_id=0)

        deltas = [
            FakeDelta("processor.0.config.color_lower", new_value=[0, 0, 100]),
            FakeDelta("processor.0.config.min_area", new_value=300),
            FakeDelta("processor.0.config.max_area", new_value=70000),
        ]
        callback(deltas)

        svc.set_color_range.assert_called_once_with(lower=[0, 0, 100])
        svc.set_min_area.assert_called_once_with(300)
        svc.set_max_area.assert_called_once_with(70000)

    def test_on_config_changed_ignores_state_path(self):
        """delta processor.0.state.status (не config) -> ничего не вызвано."""
        callback, svc, _ = _make_on_config_changed(camera_id=0)

        delta = FakeDelta("processor.0.state.status", new_value="running")
        callback([delta])

        svc.set_min_area.assert_not_called()
        svc.set_color_range.assert_not_called()

    def test_on_config_changed_empty_deltas(self):
        """Пустой список дельт -> ничего не вызвано, нет исключений."""
        callback, svc, _ = _make_on_config_changed(camera_id=0)

        callback([])

        svc.set_min_area.assert_not_called()
        svc.set_color_range.assert_not_called()


# ===========================================================================
# Тесты _on_regions_changed
# ===========================================================================

class TestOnRegionsChanged:
    """Проверяем _on_regions_changed: regions tree -> rebuild_runnables."""

    def test_on_regions_changed_triggers_rebuild(self):
        """regions changed -> get_subtree + rebuild_runnables вызван."""
        callback, svc, proxy = _make_on_regions_changed(camera_id=0)
        proxy.get_subtree.return_value = {
            "r1": {"nodes": {"n1": {"type": "color_detect", "params": {}}}}
        }

        delta = FakeDelta("cameras.0.regions.r1.nodes.n1.params.threshold", new_value=50)
        callback([delta])

        proxy.get_subtree.assert_called_once_with("cameras.0.regions")
        svc.rebuild_runnables.assert_called_once()

    def test_on_regions_changed_transaction_batching(self):
        """50 дельт в одном callback = ОДИН rebuild_runnables (не 50)."""
        callback, svc, proxy = _make_on_regions_changed(camera_id=0)
        proxy.get_subtree.return_value = {
            "r1": {"nodes": {"n1": {"type": "color_detect", "params": {"threshold": 50}}}}
        }

        # 50 дельт — имитация загрузки рецепта
        deltas = [
            FakeDelta(f"cameras.0.regions.r1.nodes.n{i}.params.val", new_value=i)
            for i in range(50)
        ]
        callback(deltas)

        # get_subtree один раз, rebuild один раз
        assert proxy.get_subtree.call_count == 1
        assert svc.rebuild_runnables.call_count == 1

    def test_on_regions_changed_empty_deltas(self):
        """Пустой список дельт -> no-op (get_subtree не вызывается)."""
        callback, svc, proxy = _make_on_regions_changed(camera_id=0)

        callback([])

        proxy.get_subtree.assert_not_called()
        svc.rebuild_runnables.assert_not_called()

    def test_on_regions_changed_reads_subtree(self):
        """Проверка что get_subtree вызывается с правильным путём."""
        callback, svc, proxy = _make_on_regions_changed(camera_id=2)
        proxy.get_subtree.return_value = {"r1": {}}

        delta = FakeDelta("cameras.2.regions.r1.bbox", new_value=[0, 0, 100, 100])
        callback([delta])

        proxy.get_subtree.assert_called_once_with("cameras.2.regions")

    def test_on_regions_changed_with_nodes(self):
        """regions с nodes формат -> rebuild_runnables получает pipeline_data."""
        callback, svc, proxy = _make_on_regions_changed(camera_id=0)
        regions_data = {
            "r1": {
                "nodes": {
                    "detect": {"type": "color_detect", "params": {"min_area": 500}},
                    "filter": {"type": "size_filter", "params": {"max_area": 10000}},
                }
            },
            "r2": {
                "nodes": {
                    "detect": {"type": "color_detect", "params": {"min_area": 200}},
                }
            },
        }
        proxy.get_subtree.return_value = regions_data

        delta = FakeDelta("cameras.0.regions.r1.nodes.detect.params.min_area", new_value=600)
        callback([delta])

        # rebuild_runnables вызван с pipeline_data, содержащим regions
        svc.rebuild_runnables.assert_called_once()
        call_args = svc.rebuild_runnables.call_args[0][0]
        assert "cameras" in call_args
        assert "0" in call_args["cameras"]
        assert call_args["cameras"]["0"]["regions"] == regions_data

    def test_on_regions_changed_none_subtree(self):
        """get_subtree вернул None -> rebuild_runnables НЕ вызывается."""
        callback, svc, proxy = _make_on_regions_changed(camera_id=0)
        proxy.get_subtree.return_value = None

        delta = FakeDelta("cameras.0.regions.r1.bbox", new_value=[10, 10, 200, 200])
        callback([delta])

        proxy.get_subtree.assert_called_once()
        svc.rebuild_runnables.assert_not_called()

    def test_on_regions_changed_add_region(self):
        """Добавление нового региона -> rebuild_runnables вызывается."""
        callback, svc, proxy = _make_on_regions_changed(camera_id=0)
        proxy.get_subtree.return_value = {
            "r1": {"nodes": {}},
            "r2_new": {"nodes": {"detect": {"type": "blob", "params": {}}}},
        }

        delta = FakeDelta("cameras.0.regions.r2_new", new_value={"nodes": {}})
        callback([delta])

        svc.rebuild_runnables.assert_called_once()

    def test_on_regions_changed_delete_region(self):
        """Удаление региона -> rebuild_runnables (regions без удалённого)."""
        callback, svc, proxy = _make_on_regions_changed(camera_id=0)
        # После удаления r2 остался только r1
        proxy.get_subtree.return_value = {
            "r1": {"nodes": {"detect": {"type": "blob", "params": {}}}},
        }

        delta = FakeDelta("cameras.0.regions.r2", new_value=None, old_value={"nodes": {}})
        callback([delta])

        svc.rebuild_runnables.assert_called_once()


# ===========================================================================
# Тест dual-mode: register_update НЕ удалён
# ===========================================================================

def _read_process_source() -> str:
    """Прочитать исходный код process.py без импорта (избегаем зависимостей framework)."""
    from pathlib import Path

    process_file = (
        Path(__file__).resolve().parent.parent.parent
        / "backend" / "processes" / "processor" / "process.py"
    )
    return process_file.read_text(encoding="utf-8")


class TestStateProxyOnly:
    """Проверяем что register_update удалён: только StateProxy путь (Phase 4f)."""

    def test_processing_worker_no_register_update(self):
        """_processing_worker НЕ содержит register_update (убран в 4f.3)."""
        source = _read_process_source()
        assert "apply_register_update" not in source, (
            "apply_register_update удалён в Phase 4f.3 — только StateProxy"
        )

    def test_process_has_on_config_changed_method(self):
        """ProcessorProcess имеет метод _on_config_changed."""
        source = _read_process_source()
        assert "def _on_config_changed(self" in source, (
            "ProcessorProcess должен иметь метод _on_config_changed"
        )

    def test_process_has_on_regions_changed_method(self):
        """ProcessorProcess имеет метод _on_regions_changed."""
        source = _read_process_source()
        assert "def _on_regions_changed(self" in source, (
            "ProcessorProcess должен иметь метод _on_regions_changed"
        )

    def test_dual_mode_both_paths(self):
        """Проверяем что и register_update и StateProxy пути присутствуют в коде."""
        source = _read_process_source()

        # StateProxy путь — в init
        assert "StateProxy" in source, "StateProxy должен создаваться в _init_application_threads"
        assert "_state_proxy" in source, "_state_proxy должен инициализироваться"
        assert ".subscribe(" in source, "subscribe должен вызываться для подписок"

        # register_update путь — в worker (legacy fallback)
        assert "register_update" in source, (
            "register_update должен оставаться в _processing_worker как fallback"
        )
