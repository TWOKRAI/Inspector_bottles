"""Тесты PipelinePresenter — обработчики target_process и display_id (Task 7a.3).

Проверяют:
- _on_target_process_changed: записывает target_process в topology.
- _on_display_id_changed: обновляет display_id и display_name в topology.
- Подключение сигналов через set_inspector().
"""

from __future__ import annotations

from unittest.mock import MagicMock

from multiprocess_prototype.frontend.widgets.tabs.pipeline.presenter import PipelinePresenter
from multiprocess_prototype.frontend.widgets.tabs.pipeline.inspector.inspector_panel import (
    NodeInspectorPanel,
)


# ------------------------------------------------------------------ #
#  Фикстуры                                                           #
# ------------------------------------------------------------------ #


def _make_ctx_for_presenter(topology=None, display_registry=None):
    """Создать mock AppContext для PipelinePresenter."""
    ctx = MagicMock()
    ctx.config = {
        "topology": topology
        or {
            "processes": [
                {"process_name": "p1", "plugins": [{"plugin_name": "capture"}]},
                {"process_name": "p2", "plugins": [{"plugin_name": "color_mask"}]},
            ],
            "wires": [],
            "displays": [
                {"node_id": "disp1", "display_id": "main_output", "display_name": "Основной"},
            ],
        }
    }
    ctx.plugin_registry.return_value = None
    ctx.action_bus.return_value = None
    ctx.topology_holder.return_value = None
    ctx.topology_bridge.return_value = None
    ctx.registers_manager.return_value = None
    ctx.form_context.return_value = None

    if display_registry is not None:
        ctx.display_registry = display_registry
    else:
        ctx.display_registry = None

    return ctx


def _make_display_entry(display_id: str, name: str):
    """Создать mock DisplayEntry."""
    entry = MagicMock()
    entry.id = display_id
    entry.name = name
    return entry


# ------------------------------------------------------------------ #
#  Тесты: _on_target_process_changed                                  #
# ------------------------------------------------------------------ #


class TestPresenterTargetProcessChanged:
    def test_target_process_change_updates_model(self):
        """_on_target_process_changed записывает target_process в topology."""
        ctx = _make_ctx_for_presenter()
        presenter = PipelinePresenter(ctx)

        # Загрузить topology
        presenter.load_topology_from_config()

        # Изменить target_process для узла "p1"
        presenter._on_target_process_changed("p1", "p2")

        topo = presenter.model.to_topology_dict()
        processes = topo.get("processes", [])

        # Найти p1 и проверить target_process
        p1 = next((p for p in processes if p.get("process_name") == "p1"), None)
        assert p1 is not None, "Процесс p1 должен существовать"
        assert p1.get("target_process") == "p2", "target_process должен быть обновлён"

    def test_target_process_can_point_to_existing_process(self):
        """target_process — мета-поле, может указывать на любой процесс (включая существующие)."""
        ctx = _make_ctx_for_presenter()
        presenter = PipelinePresenter(ctx)
        presenter.load_topology_from_config()

        # p2 уже существует, но target_process это просто метаданные — OK
        presenter._on_target_process_changed("p1", "p2")

        topo = presenter.model.to_topology_dict()
        p1 = next((p for p in topo["processes"] if p.get("process_name") == "p1"), None)
        assert p1 is not None
        # target_process должен быть установлен
        assert p1.get("target_process") == "p2"

    def test_target_process_change_nonexistent_node_logs_warning(self, caplog):
        """Если node_id не найден в topology — логируется warning, не падает."""
        import logging

        ctx = _make_ctx_for_presenter()
        presenter = PipelinePresenter(ctx)
        presenter.load_topology_from_config()

        with caplog.at_level(logging.WARNING):
            presenter._on_target_process_changed("nonexistent_node", "p2")

        assert any(r.levelno >= logging.WARNING for r in caplog.records)

    def test_target_process_suppressed_when_suppress_flag_set(self):
        """_on_target_process_changed игнорирует изменения при suppress=True."""
        ctx = _make_ctx_for_presenter()
        presenter = PipelinePresenter(ctx)
        presenter.load_topology_from_config()

        # Установить suppress вручную
        presenter._suppress = True
        presenter._on_target_process_changed("p1", "new_name")

        topo = presenter.model.to_topology_dict()
        p1 = next((p for p in topo["processes"] if p.get("process_name") == "p1"), None)
        # target_process не должен быть установлен
        assert p1.get("target_process", None) is None


# ------------------------------------------------------------------ #
#  Тесты: _on_display_id_changed                                      #
# ------------------------------------------------------------------ #


class TestPresenterDisplayIdChanged:
    def test_display_id_change_updates_model(self):
        """_on_display_id_changed обновляет display_id в topology."""
        ctx = _make_ctx_for_presenter()
        presenter = PipelinePresenter(ctx)
        presenter.load_topology_from_config()

        presenter._on_display_id_changed("disp1", "secondary")

        topo = presenter.model.to_topology_dict()
        disp1 = next(
            (d for d in topo.get("displays", []) if d.get("node_id") == "disp1"),
            None,
        )
        assert disp1 is not None, "Display disp1 должен существовать"
        assert disp1.get("display_id") == "secondary"

    def test_display_id_change_updates_display_name_from_registry(self):
        """_on_display_id_changed обновляет display_name если реестр доступен."""
        entries = [_make_display_entry("secondary", "Вторичный дисплей")]
        registry_mock = MagicMock()
        registry_mock.get.side_effect = lambda did: next((e for e in entries if e.id == did), None)

        ctx = _make_ctx_for_presenter(display_registry=registry_mock)
        presenter = PipelinePresenter(ctx)
        presenter.load_topology_from_config()

        presenter._on_display_id_changed("disp1", "secondary")

        topo = presenter.model.to_topology_dict()
        disp1 = next(
            (d for d in topo.get("displays", []) if d.get("node_id") == "disp1"),
            None,
        )
        assert disp1 is not None
        assert disp1.get("display_id") == "secondary"
        assert disp1.get("display_name") == "Вторичный дисплей"

    def test_display_id_change_nonexistent_node_logs_warning(self, caplog):
        """Если display node_id не найден — логируется warning, не падает."""
        import logging

        ctx = _make_ctx_for_presenter()
        presenter = PipelinePresenter(ctx)
        presenter.load_topology_from_config()

        with caplog.at_level(logging.WARNING):
            presenter._on_display_id_changed("nonexistent_disp", "main")

        assert any(r.levelno >= logging.WARNING for r in caplog.records)

    def test_display_id_suppressed_when_suppress_flag_set(self):
        """_on_display_id_changed игнорирует изменения при suppress=True."""
        ctx = _make_ctx_for_presenter()
        presenter = PipelinePresenter(ctx)
        presenter.load_topology_from_config()

        presenter._suppress = True
        presenter._on_display_id_changed("disp1", "new_display")

        topo = presenter.model.to_topology_dict()
        disp1 = next(
            (d for d in topo.get("displays", []) if d.get("node_id") == "disp1"),
            None,
        )
        # display_id не должен измениться
        assert disp1.get("display_id") == "main_output"


# ------------------------------------------------------------------ #
#  Тесты: set_inspector подключает сигналы                            #
# ------------------------------------------------------------------ #


class TestPresenterSetInspectorSignals:
    def test_set_inspector_connects_target_process_signal(self, qtbot):
        """set_inspector подключает target_process_changed → _on_target_process_changed."""
        ctx = _make_ctx_for_presenter()
        presenter = PipelinePresenter(ctx)
        presenter.load_topology_from_config()

        panel = NodeInspectorPanel()
        qtbot.addWidget(panel)
        presenter.set_inspector(panel)

        # Эмитируем сигнал — presenter должен обработать
        panel.target_process_changed.emit("p1", "p2")

        # Проверяем что topology обновлена
        topo = presenter.model.to_topology_dict()
        p1 = next((p for p in topo["processes"] if p.get("process_name") == "p1"), None)
        assert p1 is not None

    def test_set_inspector_connects_display_id_signal(self, qtbot):
        """set_inspector подключает display_id_changed → _on_display_id_changed."""
        ctx = _make_ctx_for_presenter()
        presenter = PipelinePresenter(ctx)
        presenter.load_topology_from_config()

        panel = NodeInspectorPanel()
        qtbot.addWidget(panel)
        presenter.set_inspector(panel)

        # Эмитируем сигнал
        panel.display_id_changed.emit("disp1", "new_display")

        topo = presenter.model.to_topology_dict()
        disp1 = next(
            (d for d in topo.get("displays", []) if d.get("node_id") == "disp1"),
            None,
        )
        assert disp1 is not None
        assert disp1.get("display_id") == "new_display"

    def test_set_inspector_passes_context_to_panel(self, qtbot):
        """set_inspector передаёт AppContext в NodeInspectorPanel."""
        ctx = _make_ctx_for_presenter()
        presenter = PipelinePresenter(ctx)

        panel = NodeInspectorPanel()
        qtbot.addWidget(panel)
        presenter.set_inspector(panel)

        assert panel._ctx is ctx
